"""Leads: upload (queued, with live progress), enroll, research, send, delete,
manual Pitch-Decker add, and the bulk housekeeping buttons.

Capacity notes — this router is the one that met an 80k-row sheet:
- Upload is a BACKGROUND JOB (POST returns 202 + job id in milliseconds). The
  old version parsed, de-duplicated, MX-checked and inserted every row inside
  the request, which is minutes of work and a guaranteed timeout / 500.
- Every bulk action is set-based or chunked, never a per-row ORM loop.
- FK children (messages, template uses, pitch records) are always cleared
  before deleting leads, or Postgres raises an IntegrityError -> 500.
"""
import re
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas, audit
from ..security import current_user
from ..services import (excel_import, tavily, mailer, enroller,
                        keys as keysvc, spam_filter, importer, jobs,
                        ownership as ownership_service)
from pydantic import BaseModel
router = APIRouter(prefix="/api/leads", tags=["leads"])
ALLOWED_EXT = (".xlsx", ".xls", ".csv")
# 5 MB was sized for a 2 000-row sheet. A real 80 000-row export (email + name +
# company + title + notes columns) is 8-20 MB, so the old cap rejected exactly
# the files this queue exists for. 50 MB covers ~250k rows; the job is chunked
# and commits per 1 000 rows, so a big file never holds a transaction open.
MAX_UPLOAD = 50 * 1024 * 1024
CHUNK = 2000          # ids per statement in bulk deletes (Postgres param limit)


def _chunks(seq, n=CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


@router.get("", response_model=list[schemas.LeadOut])
def list_leads(status: str | None = Query(default=None),
               agent_id: int | None = Query(default=None),
               page: int = Query(default=1, ge=1),
               per_page: int = Query(default=100, ge=1, le=500),
               db: Session = Depends(get_db)):
    """Legacy flat list — kept for older calls."""
    q = db.query(models.Lead).filter(models.Lead.status != models.LeadStatus.garbage)
    if status:
        q = q.filter(models.Lead.status == status)
    if agent_id:
        q = q.filter(models.Lead.agent_id == agent_id)
    return (q.order_by(models.Lead.priority.desc(), models.Lead.created_at.desc())
             .offset((page - 1) * per_page).limit(per_page).all())


@router.get("/paged")
def list_leads_paged(status: str | None = Query(default=None),
                     agent_id: int | None = Query(default=None),
                     unverified_only: bool = Query(default=False),
                     unassigned_only: bool = Query(default=False),
                     pitch_pending: bool = Query(default=False),
                     needs_human_only: bool = Query(default=False),
                     not_interested_only: bool = Query(default=False),
                     source_file: str = Query(default=""),
                     batch_id: int | None = Query(default=None),
                     q: str = Query(""),
                     page: int = Query(default=1, ge=1),
                     per_page: int = Query(default=30, ge=5, le=200),
                     db: Session = Depends(get_db)):
    """Paginated with total - the UI uses this for proper 'Page X of Y' pagers.
    Handles 50k+ leads cleanly."""
    from sqlalchemy import func, or_
    qy = db.query(models.Lead).filter(models.Lead.status != models.LeadStatus.garbage)
    if status:
        qy = qy.filter(models.Lead.status == status)
    if agent_id:
        qy = qy.filter(models.Lead.agent_id == agent_id)
    if unverified_only:
        qy = qy.filter(models.Lead.email_verified.is_(False))
    if unassigned_only:
        qy = qy.filter(models.Lead.agent_id.is_(None))
    if batch_id:
        qy = qy.filter(models.Lead.batch_id == batch_id)
    if source_file:
        # Everything from one Excel: through the batch (a batch is one file) and
        # the lead's own upload tag for rows not in a batch yet.
        fname = source_file.strip()
        qy = qy.filter(or_(
            models.Lead.batch_id.in_(
                db.query(models.Batch.id)
                  .filter(models.Batch.source_filename == fname)),
            models.Lead.upload_tag == fname,
        ))
    if needs_human_only:
        # Threads where the agent refused to answer (price / contract / legal /
        # security) and a person has to. These stay in Messages, not Escalation.
        qy = qy.filter(models.Lead.needs_human.is_(True))
    if not_interested_only:
        # Said not interested. Normally these sit in the Garbage page, so this
        # only returns the ones not yet purged.
        qy = qy.filter(models.Lead.not_interested.is_(True))
    if pitch_pending:
        # only leads not marked done in Pitch Decker
        qy = qy.filter(models.Lead.pitch_done.is_(False), models.Lead.source == "pitch")
    else:
        # Leads outreach page — pitch uploads hide
        qy = qy.filter(models.Lead.source != "pitch")
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(or_(models.Lead.email.ilike(like),
                           models.Lead.name.ilike(like),
                           models.Lead.company.ilike(like)))

    total = qy.count()

    if pitch_pending:
        rows = (qy.order_by(models.Lead.created_at.asc())
                  .offset((page - 1) * per_page).limit(per_page).all())
    else:
        rows = (qy.order_by(models.Lead.priority.desc(), models.Lead.created_at.desc())
                  .offset((page - 1) * per_page).limit(per_page).all())

    # Pitch queue: flag leads whose email also lives in the Excel outreach
    # list (source != pitch). Excel leads may be anywhere in the table, not
    # just this page — so match by email across the whole table.
    dup_in_excel = set()
    if pitch_pending and rows:
        page_emails = [l.email for l in rows]
        dup_in_excel = {e for (e,) in db.query(models.Lead.email)
                        .filter(models.Lead.email.in_(page_emails),
                                models.Lead.source != "pitch").all()}

    agent_names = {a.id: a.name for a in db.query(models.Agent.id, models.Agent.name).all()}

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    page_ids = [l.id for l in rows]
    locked_rows = []
    if page_ids:
        locked_rows = (db.query(models.EmailMessage.lead_id, models.EmailMessage.agent_id)
                       .filter(models.EmailMessage.lead_id.in_(page_ids),
                               models.EmailMessage.direction == "out",
                               models.EmailMessage.agent_id.isnot(None),
                               models.EmailMessage.created_at >= today_start)
                       .all())
    sent_today_by = {}
    for lead_id, agent_id in locked_rows:
        sent_today_by.setdefault(lead_id, set()).add(agent_id)
    unlock_at = today_start + timedelta(days=1)

    items = []
    for l in rows:
        d = schemas.LeadOut.model_validate(l, from_attributes=True).model_dump()
        d["agent_name"] = agent_names.get(l.agent_id, "")
        d["dup_in_excel"] = pitch_pending and l.email in dup_in_excel
        senders_today = sent_today_by.get(l.id, set())
        if senders_today and (senders_today - {l.agent_id}):
            d["locked_until"] = unlock_at
        items.append(d)
    return {
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
        "items": items,
    }


@router.post("/{lead_id}/pitch-done")
def mark_pitch_done(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.pitch_done = True
    db.commit()
    return {"ok": True, "id": lead_id}


@router.delete("/{lead_id}/pitch-done")
def unmark_pitch_done(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.pitch_done = False
    db.commit()
    return {"ok": True, "id": lead_id}


class BulkIds(BaseModel):
    ids: list[int] = []
    to_garbage: bool = False
    unverified: bool = False


@router.post("/bulk-delete")
def bulk_delete(data: BulkIds, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(current_user)):
    # Every branch is set-based. The old "unverified → garbage" branch loaded
    # every unverified lead into the session and updated them one by one, which
    # on a 40k-unverified table meant a multi-minute request holding a
    # connection the whole way.
    if data.unverified:
        n = (db.query(models.Lead)
             .filter(models.Lead.status != models.LeadStatus.garbage,
                     models.Lead.email_verified.is_(False))
             .update({"status": models.LeadStatus.garbage},
                     synchronize_session=False))
        db.commit()
        audit.log(db, user, "leads.unverified_to_garbage", "lead", "", f"{n} lead(s)",
                  request.client.host if request.client else "")
        return {"moved": n, "deleted": 0}

    if data.to_garbage:
        ids = list(dict.fromkeys(data.ids or []))[:100000]
        if not ids:
            return {"deleted": 0, "moved": 0}
        moved = 0
        for part in _chunks(ids):
            moved += (db.query(models.Lead)
                      .filter(models.Lead.id.in_(part))
                      .update({"status": models.LeadStatus.garbage},
                              synchronize_session=False))
        db.commit()
        audit.log(db, user, "leads.bulk_garbage", "lead", "", f"{moved} lead(s)",
                  request.client.host if request.client else "")
        return {"moved": moved, "deleted": 0}

    ids = list(dict.fromkeys(data.ids or []))[:100000]
    if not ids:
        return {"deleted": 0, "moved": 0}

    # Hard delete — clear FK children first (bulk delete() bypasses ORM
    # cascades, so un-cleared template_uses / pitch_records / email_messages
    # would make the leads DELETE raise a foreign-key violation -> 500).
    deleted = 0
    for part in _chunks(ids):
        db.query(models.TemplateUse).filter(models.TemplateUse.lead_id.in_(part))\
            .delete(synchronize_session=False)
        db.query(models.PitchRecord).filter(models.PitchRecord.lead_id.in_(part))\
            .delete(synchronize_session=False)
        db.query(models.EmailMessage).filter(models.EmailMessage.lead_id.in_(part))\
            .delete(synchronize_session=False)
        deleted += (db.query(models.Lead).filter(models.Lead.id.in_(part))
                    .delete(synchronize_session=False))
        db.commit()
    audit.log(db, user, "leads.bulk_delete", "lead", "", f"{deleted} lead(s)",
              request.client.host if request.client else "")
    return {"deleted": deleted, "moved": 0}


@router.delete("/pitch-queue")
def delete_pitch_queue(request: Request, db: Session = Depends(get_db),
                       user: models.User = Depends(current_user)):
    """Empty the whole Pitch Decker queue in one statement.

    The page used to page through 200 leads at a time and delete them in
    500-id chunks: 80 000 pitch leads meant ~400 GETs and 160 DELETEs from the
    browser, and any single failure left the queue half-deleted. This walks the
    ids server-side, keyset-paged, and removes FK children with them."""
    last_id, total = 0, 0
    while True:
        ids = [i for (i,) in (db.query(models.Lead.id)
                              .filter(models.Lead.source == "pitch",
                                      models.Lead.id > last_id)
                              .order_by(models.Lead.id)
                              .limit(CHUNK).all())]
        if not ids:
            break
        db.query(models.TemplateUse).filter(models.TemplateUse.lead_id.in_(ids))\
            .delete(synchronize_session=False)
        db.query(models.PitchRecord).filter(models.PitchRecord.lead_id.in_(ids))\
            .delete(synchronize_session=False)
        db.query(models.EmailMessage).filter(models.EmailMessage.lead_id.in_(ids))\
            .delete(synchronize_session=False)
        total += (db.query(models.Lead)
                  .filter(models.Lead.id.in_(ids))
                  .delete(synchronize_session=False))
        last_id = ids[-1]
        db.commit()
    audit.log(db, user, "leads.pitch_queue_cleared", "lead", "",
              f"{total} lead(s)", request.client.host if request.client else "")
    return {"deleted": total}


@router.post("/purge-completed")
def purge_completed(days: int = Query(60, ge=7, le=3650), db: Session = Depends(get_db)):
    """FIFO cleanup: delete completed/closed leads that haven't had ANY
    activity in N days — plus all their messages. Keeps the DB lean at
    80k+ scale.

    'No activity' means the most recent of: upload date, last outbound
    email, last inbound reply — is older than the cutoff. This matters:
    a lead uploaded 70 days ago but enrolled/closed yesterday must NOT be
    purged just because its original upload date is old. Only leads that are
    BOTH closed/garbage AND genuinely untouched for N days go.

    Two bugs fixed here, both of which surfaced as 500s:
      1. template_uses / pitch_records were never cleared, so deleting a lead
         that had used a template or held a pitch raised an IntegrityError.
      2. all matching ids went into ONE `IN (...)`; at 80k rows that is a
         80k-parameter statement that Postgres refuses. Now chunked.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = 0
    # Keyset walk (id > last_seen, LIMIT 2000) instead of one giant IN list or
    # a cursor that we then delete underneath. Safe with concurrent traffic:
    # rows inserted during the sweep are simply not matched.
    last_id = 0
    while True:
        ids = [i for (i,) in (
            db.query(models.Lead.id)
            .filter(models.Lead.id > last_id,
                    models.Lead.status.in_([models.LeadStatus.closed,
                                            models.LeadStatus.garbage]),
                    models.Lead.created_at < cutoff,
                    (models.Lead.last_outbound_at.is_(None)) | (models.Lead.last_outbound_at < cutoff),
                    (models.Lead.last_inbound_at.is_(None)) | (models.Lead.last_inbound_at < cutoff))
            .order_by(models.Lead.id).limit(2000).all())]
        if not ids:
            break
        last_id = ids[-1]
        for part in _chunks(ids):
            db.query(models.TemplateUse).filter(models.TemplateUse.lead_id.in_(part))\
                .delete(synchronize_session=False)
            db.query(models.PitchRecord).filter(models.PitchRecord.lead_id.in_(part))\
                .delete(synchronize_session=False)
            db.query(models.EmailMessage).filter(models.EmailMessage.lead_id.in_(part))\
                .delete(synchronize_session=False)
            deleted += (db.query(models.Lead).filter(models.Lead.id.in_(part))
                        .delete(synchronize_session=False))
        db.commit()
    return {"deleted": deleted, "cutoff": cutoff.isoformat()}


@router.get("/stats")
def leads_stats(db: Session = Depends(get_db)):
    """Counts by status (drives the FIFO / cleanup UI)."""
    from sqlalchemy import func
    rows = (db.query(models.Lead.status, func.count(models.Lead.id))
              .group_by(models.Lead.status).all())
    return {(s.value if hasattr(s, "value") else str(s)): n for s, n in rows}


def _make_batch(db, campaign, number: int, leads: list) -> dict:
    """Kept for callers outside the import pipeline (single-lead tests). The
    import engine has its own copy so it can batch without a request-scoped
    session."""
    return importer._make_batch(db, campaign, number, leads)


@router.post("/upload", status_code=202)
async def upload_leads(request: Request,
                       file: UploadFile = File(...),
                       source: str | None = Form(default=None),
                       batch_size: int | None = Form(default=None),
                       auto_enroll: bool | None = Form(default=None),
                       campaign_id: int | None = Form(default=None),
                       agent_id: int | None = Form(default=None),
                       db: Session = Depends(get_db)):
    """Import an Excel/CSV sheet — QUEUED, returns immediately with a job id.

    The browser gets 202 + {job_id, status:'queued'} in milliseconds and then
    polls /upload/{job_id} for the progress bar. All the real work (parse,
    de-dupe against the DB, per-domain MX, chunked inserts, batching, enroll)
    happens in a background thread, so an 80k-row sheet no longer means a
    request that times out and returns 500 with half the file imported.

    campaign_id / agent_id are FORM fields (the page posts a FormData body).
    They used to be declared as query params, so they were silently dropped
    and auto-enroll never received them — every field therefore also falls
    back to the query string, which is where source/batch_size/auto_enroll
    are sent.

    source=excel → Leads (outreach) only.
    source=pitch → Pitch Decker only (never auto-emailed).

    batch_size is OPTIONAL. Left out — which is what the UI does — the server
    uses the Settings-page "email batch size" (20/30/40/50). Each sheet is cut
    into `Batch` rows of that size, and a batch never straddles two files, so
    Mail Records can answer "which batch, from which sheet" and one batch can be
    enrolled on its own.

    auto_enroll + campaign (+ agent) → imported leads are enrolled and queued on
    the same strict FIFO the manual launch uses."""
    qp = request.query_params

    def _both(key: str, cast, form_val):
        """Form field first, query string second — callers use either one."""
        if form_val is not None:
            return form_val
        raw = qp.get(key)
        if raw in (None, ""):
            return None
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return None

    src = str(_both("source", str, source) or "excel").strip().lower()
    if src == "csv":
        src = "excel"
    if src not in ("excel", "pitch", "manual"):
        src = "excel"
    batch_size = _both("batch_size", int, batch_size)
    if batch_size is not None:
        batch_size = max(10, min(2000, batch_size))
    if auto_enroll is None:
        auto_enroll = _both("auto_enroll",
                            lambda v: str(v).lower() in ("1", "true", "yes", "on"),
                            auto_enroll)
    if auto_enroll is None:
        auto_enroll = True
    campaign_id = _both("campaign_id", int, campaign_id)
    agent_id = _both("agent_id", int, agent_id)

    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, "Only .xlsx, .xls or .csv files are allowed")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "That file is empty")
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, f"File too large (max {MAX_UPLOAD // (1024 * 1024)} MB)")

    campaign = db.get(models.Campaign, campaign_id) if campaign_id else None
    agent = (db.get(models.Agent, agent_id) if agent_id
             else (db.get(models.Agent, campaign.agent_id) if campaign else None))
    if campaign_id and not campaign:
        raise HTTPException(400, "Campaign not found")
    if campaign_id and not agent:
        raise HTTPException(400, "That campaign has no agent to run the send")
    if src == "pitch":
        campaign = agent = None            # the Pitch queue is never auto-emailed

    do_enqueue = bool(auto_enroll and campaign and agent
                      and campaign.status == "active")
    tag = (file.filename or "").rsplit(".", 1)[0][:200]
    # No explicit size -> the Settings page decides.
    from ..services.enroller import resolve_batch_size
    batch_size = resolve_batch_size(db, batch_size)

    job_id = jobs.create_job(
        kind="upload", filename=file.filename[:300], source=src,
        status="queued", phase="Queued — starting in a moment", pct=1,
        batch_size=batch_size, campaign_id=campaign.id if campaign else None,
        agent_id=agent.id if agent else None, auto_enroll=do_enqueue,
        upload_tag=tag, payload=raw.hex(),
    )
    jobs.submit(job_id, importer.run_import)
    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "status": "queued", "source": src,
                 "batch_size": batch_size, "auto_enrolled": do_enqueue,
                 "upload_tag": tag,
                 "poll": f"/api/leads/upload/{job_id}"})


@router.get("/upload/{job_id}")
def upload_job(job_id: int, db: Session = Depends(get_db)):
    """Live progress for one import/verify job. The page polls this every
    ~700ms while the bar is moving; it is a handful of indexed row reads."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Import job not found")
    return job


@router.get("/jobs")
def list_jobs(kind: str | None = Query(default=None, le=40),
              db: Session = Depends(get_db)):
    """Recent import/verify jobs so a page refresh (or another tab) picks up
    an import that is still running instead of showing an empty screen."""
    return {"items": jobs.recent_jobs(kind)}


@router.post("/upload/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    """Flag the job cancelled. A queued/running import checks this between
    chunks and stops there, keeping everything it already committed."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Import job not found")
    if job["status"] in ("done", "error", "cancelled"):
        return {"cancelled": False, "status": job["status"]}
    jobs.update_job(job_id, status="cancelled",
                    phase="Cancelling — stopping after the current chunk…",
                    error="cancelled by user")
    return {"cancelled": True, "status": "cancelled"}


class ManualPitchLead(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""


@router.post("/manual-pitch")
def manual_pitch_lead(data: ManualPitchLead, db: Session = Depends(get_db)):
    """'Manual lead' button in Pitch Decker: add one pitch lead by hand.
    Same-source duplicates are not added twice; if the same email already
    exists in the Excel outreach list it is still added as a separate Pitch
    entry (they are different queues) and the UI shows it as a duplicate."""
    email = (data.email or "").strip().lower()
    if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email or ""):
        raise HTTPException(400, "Please enter a valid email address")

    existing = db.query(models.Lead).filter(models.Lead.email == email).first()
    if existing and existing.source == "pitch":
        return {"created": 0, "id": existing.id, "duplicate": True,
                "cross_duplicate": False, "email_verified": bool(existing.email_verified)}

    ok, _reason = mailer.verify_recipient(email, smtp=False)
    lead = models.Lead(
        name=(data.name or "").strip() or email.split("@")[0],
        email=email,
        phone=(data.phone or "").strip(),
        website=(data.website or "").strip(),
        source="pitch",
        email_verified=ok,
    )
    db.add(lead)
    db.commit()
    return {"created": 1, "id": lead.id, "duplicate": False,
            "cross_duplicate": bool(existing), "email_verified": ok}


class VerifyIn(BaseModel):
    ids: list[int] = []
    all: bool = True


@router.post("/verify", status_code=202)
def verify_mailboxes(data: VerifyIn | None = None, db: Session = Depends(get_db)):
    """MX-verify unverified mailboxes — now a BACKGROUND JOB.

    The old version did up to 500 blocking DNS lookups inside the request.
    On a list of real addresses that takes minutes, the proxy kills it, and the
    button shows a 500 with nothing verified. Now the POST returns a job id
    immediately and the page polls the same progress bar the upload uses.

    MX is a property of the DOMAIN, so the worker resolves each unique domain
    once and caches the verdict in ResearchCache."""
    ids = (data.ids if data else None) or []
    job_id = jobs.create_job(kind="verify", filename="Mailbox verification",
                             source="excel", status="queued",
                             phase="Queued — starting in a moment", pct=1)
    if ids:
        # Narrow job: only the selected leads. Stored on the job as a JSON-ish
        # comma list so the worker does not need a second table.
        jobs.update_job(job_id, upload_tag=",".join(str(i) for i in ids[:50000]))
    jobs.submit(job_id, importer.run_verify, ids or None)
    return JSONResponse(status_code=202,
                        content={"job_id": job_id, "status": "queued",
                                 "poll": f"/api/leads/upload/{job_id}"})


@router.delete("/all", status_code=200)
def delete_all_leads(request: Request, db: Session = Depends(get_db),
                     user: models.User = Depends(current_user)):
    """Wipe the entire lead list + their messages (full sheet delete).

    Fix: ORM bulk delete() does NOT fire relationship cascades, and Postgres
    enforces FK constraints into leads from email_messages, template_uses and
    pitch_records. Deleting the leads table without clearing those first
    raises an IntegrityError whenever ANY lead has a pitch record / used a
    template — so with ~1k+ leads the whole request intermittently 500s.
    We now TRUNCATE with CASCADE (one fast statement that clears leads and
    every FK-referencing table at any volume) and fall back to ordered
    deletes for restricted DB users.
    """
    n = db.query(models.Lead).count()
    if n:
        try:
            db.execute(text("TRUNCATE TABLE leads RESTART IDENTITY CASCADE"))
        except Exception:
            db.rollback()
            db.query(models.TemplateUse).delete(synchronize_session=False)
            db.query(models.PitchRecord).delete(synchronize_session=False)
            db.query(models.EmailMessage)\
              .filter(models.EmailMessage.lead_id.isnot(None))\
              .delete(synchronize_session=False)
            db.query(models.Lead).delete(synchronize_session=False)
        db.commit()
    audit.log(db, user, "leads.delete_all", "lead", "", f"{n} lead(s) wiped",
              request.client.host if request.client else "")
    return {"deleted": n}


class EnrollRequest(BaseModel):
    """Accepts BOTH shapes the UI sends:
      {lead_ids: [...]}              -> enroll exactly these
      {filter: {...}}                -> enroll every lead matching the current
                                        Leads-page filter, all pages
      {batch_ids: [...]}             -> enroll one or more whole batches
                                        (the 20/30/40/50 groups a sheet was split
                                        into) without re-selecting leads
      {source_file: "xlsx"}          -> enroll everything from one Excel
    Previously the endpoint only understood lead_ids, so 'Enroll all matching'
    came back as a 422 and the button looked broken."""
    lead_ids: list[int] = []
    campaign_id: int
    agent_id: int | None = None
    filter: dict | None = None
    batch_ids: list[int] = []
    source_file: str = ""


@router.post("/enroll")
def enroll(data: EnrollRequest, db: Session = Depends(get_db)):
    """Enroll leads into a campaign.

    Lock rule (matches what actually happens at send-time): once an agent has
    EMAILED a lead, no OTHER agent can enroll/claim that lead for 24 hours from
    that send. Just being enrolled with nothing sent yet does NOT lock it — only
    a real email does. After 24 hours the lock lifts automatically.

    The lock checks are SET queries now: three queries for the whole selection
    instead of three per lead, so enrolling 5 000 leads is 3 round trips
    instead of 15 000."""
    campaign = db.get(models.Campaign, data.campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    requested_agent_id = data.agent_id or campaign.agent_id
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    unlock_at = today_start + timedelta(days=1)

    ids = list(dict.fromkeys(data.lead_ids or []))
    if data.filter:
        ids = _ids_for_filter(db, data.filter)
    if data.batch_ids:
        # A whole batch, however it was made (upload or manual launch).
        batch_ids = [b for b in dict.fromkeys(data.batch_ids) if b][:1000]
        ids = [i for (i,) in (
            db.query(models.Lead.id)
            .filter(models.Lead.batch_id.in_(batch_ids),
                    models.Lead.status != models.LeadStatus.garbage)
            .order_by(models.Lead.id).all())]
    elif data.source_file:
        ids = _ids_for_filter(db, {"source_file": data.source_file,
                                    "unassigned_only": True})
    ids = [i for i in ids if i][:200000]
    if not ids:
        return {"enrolled": 0, "campaign_id": campaign.id, "blocked": [],
                "batch_size": 0, "batches": []}

    blocked = []
    takeover: list[models.Lead] = []
    # An explicit id selection may take a CONTACTED lead over (owner released);
    # bulk paths (filter / batch / source file) only ever see fresh leads.
    explicit_ids = bool(data.lead_ids)
    own_days = ownership_service.ownership_days(db)
    # ── who already got a real outbound (ever) ─────────────────────────────
    # Chunked: these two queries used to take the whole id list at once, and
    # Postgres caps a statement at 65 535 bind parameters — "enroll all
    # matching" on a few thousand leads blew past it and surfaced as a 500.
    prior_out: set[int] = set()
    for part in _chunks(ids):
        prior_out.update(lid for (lid,) in (
            db.query(models.EmailMessage.lead_id)
            .filter(models.EmailMessage.lead_id.in_(part),
                    models.EmailMessage.direction == "out",
                    models.EmailMessage.is_spam.is_(False))
            .distinct().all()))
    # ── who did an agent email TODAY (the 24h lock) ────────────────────────
    sent_today: dict[int, set] = {}
    for part in _chunks(ids):
        for lid, aid in (db.query(models.EmailMessage.lead_id, models.EmailMessage.agent_id)
                         .filter(models.EmailMessage.lead_id.in_(part),
                                 models.EmailMessage.direction == "out",
                                 models.EmailMessage.agent_id.isnot(None),
                                 models.EmailMessage.created_at >= today_start)
                         .all()):
            sent_today.setdefault(lid, set()).add(aid)

    # ── narrow to leads that are still enrollable, in chunks ───────────────
    wanted: set[int] = set()
    for part in _chunks(ids):
        for lid, st in (db.query(models.Lead.id, models.Lead.status)
                        .filter(models.Lead.id.in_(part)).all()):
            if st in (models.LeadStatus.new, models.LeadStatus.enrolled) or (
                    explicit_ids and st == models.LeadStatus.contacted):
                wanted.add(lid)

    enrollable = []
    from ..services import targeting as targeting_service
    from ..services import agent_settings
    target_agent = db.get(models.Agent, requested_agent_id)
    for part in _chunks(sorted(wanted)):
        for lead in (db.query(models.Lead)
                     .filter(models.Lead.id.in_(part))
                     .order_by(models.Lead.id).all()):
            email = lead.email
            prot = spam_filter.block_reason_for_recipient(email)
            if prot:
                blocked.append({"lead_id": lead.id, "email": email,
                                "owned_by": f"blocked ({prot})",
                                "unlock_at": "never contacts"})
                continue
            # AGENT TARGETING RULES: excluded job titles, excluded companies /
            # company types, plus the agent's own target titles & location.
            # Never enrolled, so they can never be emailed by mistake. The
            # campaign's selection box decides which halves are in force.
            rule = targeting_service.exclusion_reason(
                target_agent, lead,
                parts=(agent_settings.enabled_keys(campaign)
                       if campaign is not None else None))
            if rule:
                blocked.append({"lead_id": lead.id, "email": email,
                                "owned_by": rule,
                                "unlock_at": "never — agent targeting rule"})
                continue
            # OWNERSHIP — a lead with a real outbound stays with its owner
            # while they are communicating. Released when the owner is paused
            # or silent for `lead_ownership_days` (Settings); then any agent
            # may take it. Fresh leads (no outbound) are never blocked here.
            is_takeover = False
            if lead.id in prior_out or lead.status == models.LeadStatus.contacted:
                is_held, why = ownership_service.held(db, lead, days=own_days)
                if is_held:
                    blocked.append({"lead_id": lead.id, "email": email,
                                    "owned_by": why,
                                    "unlock_at": (f"owner releases it — pause, "
                                                  f"{own_days}d silence, or hand-over")})
                    continue
                # Released: a contacted lead becomes a TAKEOVER — it continues
                # as follow-ups under the new agent, no second cold email.
                is_takeover = lead.status == models.LeadStatus.contacted
            senders = sent_today.get(lead.id, set())
            others = senders - {requested_agent_id, lead.agent_id}
            if others:
                other = db.get(models.Agent, sorted(others)[0])
                blocked.append({"lead_id": lead.id, "email": email,
                                "owned_by": other.name if other else "another agent",
                                "unlock_at": unlock_at.isoformat()})
                continue
            if is_takeover:
                takeover.append(lead)
            else:
                enrollable.append(lead)

    takeover_ids = [l.id for l in takeover]
    if not enrollable and not takeover_ids:
        return {"enrolled": 0, "handed_over": 0, "campaign_id": campaign.id,
                "blocked": blocked[:200], "blocked_count": len(blocked),
                "batch_size": 0, "batches": []}

    ok_ids = [l.id for l in enrollable]
    # One UPDATE for the whole set, then read back the rows to queue them.
    for part in _chunks(ok_ids):
        db.query(models.Lead).filter(models.Lead.id.in_(part))\
          .update({"campaign_id": campaign.id,
                   "agent_id": requested_agent_id,
                   "status": models.LeadStatus.enrolled},
                  synchronize_session=False)
    # TAKEOVER (owner released): only the owner changes — status stays
    # 'contacted', so NO new initial email fires; the new agent simply
    # continues the sequence with its own follow-ups from the next sweep.
    for part in _chunks(takeover_ids):
        db.query(models.Lead).filter(models.Lead.id.in_(part))\
          .update({"campaign_id": campaign.id,
                   "agent_id": requested_agent_id},
                  synchronize_session=False)
    db.commit()

    if ok_ids:
        info = enroller.enqueue_fifo(db, campaign, db.get(models.Agent, requested_agent_id),
                                     _by_id_chunked(db, ok_ids))
    else:
        info = {"batch_numbers": [], "batch_sizes": [], "batch_size": 0,
                "source_filenames": []}
    db.commit()
    return {"enrolled": len(ok_ids), "handed_over": len(takeover_ids),
            "handed_over_ids": takeover_ids,
            "campaign_id": campaign.id,
            "blocked": blocked[:200], "blocked_count": len(blocked),
            "batch_size": info["batch_size"],
            "source_filenames": info.get("source_filenames", []),
            "batches": [{"number": n, "size": s}
                        for n, s in zip(info["batch_numbers"], info["batch_sizes"])]}


def _by_id_chunked(db, ids: list[int]) -> list[models.Lead]:
    out = []
    for part in _chunks(ids):
        out.extend(db.query(models.Lead)
                   .filter(models.Lead.id.in_(part))
                   .order_by(models.Lead.id).all())
    return out


def _ids_for_filter(db, f: dict) -> list[int]:
    """Resolve the Leads-page filter to lead ids (server-side, so the browser
    never has to send 80 000 ids for 'select all across pages')."""
    from sqlalchemy import or_
    qy = db.query(models.Lead.id).filter(
        models.Lead.status != models.LeadStatus.garbage)
    if f.get("pitch_pending"):
        qy = qy.filter(models.Lead.pitch_done.is_(False),
                       models.Lead.source == "pitch")
    else:
        qy = qy.filter(models.Lead.source != "pitch")
    if f.get("status"):
        qy = qy.filter(models.Lead.status == f["status"])
    if f.get("agent_id"):
        qy = qy.filter(models.Lead.agent_id == int(f["agent_id"]))
    if f.get("unverified_only"):
        qy = qy.filter(models.Lead.email_verified.is_(False))
    if f.get("unassigned_only"):
        qy = qy.filter(models.Lead.agent_id.is_(None))
    if f.get("needs_human_only"):
        qy = qy.filter(models.Lead.needs_human.is_(True))
    if f.get("not_interested_only"):
        qy = qy.filter(models.Lead.not_interested.is_(True))
    if f.get("batch_id"):
        qy = qy.filter(models.Lead.batch_id == int(f["batch_id"]))
    if f.get("source_file"):
        # "Everything from this one Excel". Resolved through the batch, because
        # a batch belongs to exactly one file; falls back to the lead's own
        # upload tag for rows imported before batches carried a file name.
        fname = str(f["source_file"])
        batched = qy.filter(models.Lead.batch_id.in_(
            db.query(models.Batch.id)
              .filter(models.Batch.source_filename == fname))).limit(200000)
        ids = [i for (i,) in batched.order_by(models.Lead.id).all()]
        return ids + [i for (i,) in qy.filter(
            models.Lead.batch_id.is_(None),
            models.Lead.upload_tag == fname).order_by(models.Lead.id).all()]
    if f.get("q"):
        like = f"%{str(f['q']).strip()}%"
        qy = qy.filter(or_(models.Lead.email.ilike(like),
                           models.Lead.name.ilike(like),
                           models.Lead.company.ilike(like)))
    return [i for (i,) in qy.order_by(models.Lead.id).limit(200000).all()]


@router.post("/{lead_id}/research", response_model=schemas.LeadOut)
def research(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    research_text, pains = tavily.research_lead(
        lead.company, lead.name, lead.website, lead.country,
        db=db, lead_email=lead.email)
    lead.company_research = research_text or lead.company_research
    lead.pain_points = pains or lead.pain_points
    db.commit()
    db.refresh(lead)
    return lead


@router.get("/{lead_id}/messages", response_model=list[schemas.MessageOut])
def thread(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return [m for m in lead.messages if not m.is_spam]


@router.post("/{lead_id}/send")
def manual_send(lead_id: int, data: schemas.ManualSend, db: Session = Depends(get_db)):
    """User sends manually from their own system (works even while agent paused)."""
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    # Manual send is also protected: worthless addresses (noreply@/info@/
    # support@/disposable) are never sent to.
    prot = spam_filter.block_reason_for_recipient(lead.email)
    if prot:
        raise HTTPException(400, f"Cannot send to this email ({prot}) — blocked")
    agent = db.get(models.Agent, lead.agent_id) if lead.agent_id else None
    last_in = next((m for m in reversed(lead.messages) if m.direction == "in"), None)
    try:
        msg_id = mailer.send_email(lead.email, data.subject, data.body,
                                   in_reply_to=last_in.message_id if last_in else "",
                                   agent_name=agent.name if agent else "",
                                   agent=agent)
    except mailer.UnverifiedRecipient as e:
        raise HTTPException(400, f"Recipient domain failed verification: {e}")
    db.add(models.EmailMessage(lead_id=lead.id, agent_id=lead.agent_id,
                               direction="out", sent_by="user",
                               subject=data.subject, body=data.body,
                               message_id=msg_id))
    lead.last_outbound_at = datetime.utcnow()
    if lead.status == models.LeadStatus.new:
        lead.status = models.LeadStatus.contacted
    db.commit()
    return {"sent": True}


@router.post("/{lead_id}/toggle-ai")
def toggle_ai(lead_id: int, db: Session = Depends(get_db)):
    """Play/pause the AI on THIS specific lead — human takeover for one
    conversation without pausing the whole agent. When paused, auto-reply
    and follow-ups skip this lead entirely; you handle it manually from
    Messages."""
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.ai_paused = not lead.ai_paused
    db.commit()
    return {"lead_id": lead.id, "ai_paused": lead.ai_paused}


@router.post("/{lead_id}/needs-human/resolve")
def resolve_needs_human(lead_id: int, data: dict, db: Session = Depends(get_db)):
    """Close out a "a human has to answer this" thread.

    Two outcomes, both explicit:
      - resume=true  → you handled it (or you want the agent to pick the thread
                       up again). Clears needs_human and hands the thread back.
      - resume=false → the answer is done and the agent must never write on this
                       thread again: auto-paused and back to normal follow-up
                       silence.
    The escalation row is left alone; purge_escalations drops it on its own
    retention clock so the Escalation page keeps its history."""
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    last = next((m for m in reversed(lead.messages)
                 if not m.is_escalation and not m.is_spam), None)
    resume = bool(data.get("resume", True))
    note = (data.get("note") or "").strip()[:300]
    lead.needs_human = False
    lead.needs_human_reason = ""
    if resume:
        lead.ai_paused = False
    else:
        lead.ai_paused = True
        # Ending a thread here means ending the sequence: no follow-ups either.
        lead.followups_sent = max(lead.followups_sent, 10 ** 6)
    db.add(models.EmailMessage(
        lead_id=lead.id, agent_id=lead.agent_id, direction="out", sent_by="you",
        subject=last.subject if last else "(human review closed)",
        body=(note or "You handled this thread yourself.")
             + (" Agent can reply again." if resume
                else " Agent will not write on this thread again."),
        message_id=f"human-{lead.id}-{int(datetime.utcnow().timestamp())}"))
    db.commit()
    return {"lead_id": lead.id, "needs_human": False, "ai_paused": lead.ai_paused,
            "resumed": resume}


@router.delete("/{lead_id}", status_code=204)
def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(models.Lead, lead_id)
    if lead:
        db.query(models.TemplateUse).filter(models.TemplateUse.lead_id == lead_id)\
          .delete(synchronize_session=False)
        db.query(models.PitchRecord).filter(models.PitchRecord.lead_id == lead_id)\
          .delete(synchronize_session=False)
        # cascade already handles messages
        db.delete(lead)
        db.commit()