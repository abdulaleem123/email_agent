"""Leads: flexible upload (any excel/csv shape), enroll (select-all supported),
research, manual send, delete. Hardened: 5 MB cap, extension allowlist."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas, audit
from ..security import current_user
from ..services import excel_import, tavily, mailer, keys as keysvc

router = APIRouter(prefix="/api/leads", tags=["leads"])
ALLOWED_EXT = (".xlsx", ".xls", ".csv")
MAX_UPLOAD = 5 * 1024 * 1024


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


def _apply_lead_filters(qy, status, agent_id, unverified_only, unassigned_only, q):
    """Shared filter builder so the paged list, the filtered count, and the
    'enroll all matching' action always agree on exactly which rows match."""
    from sqlalchemy import or_
    qy = qy.filter(models.Lead.status != models.LeadStatus.garbage)
    if status:
        qy = qy.filter(models.Lead.status == status)
    if agent_id:
        qy = qy.filter(models.Lead.agent_id == agent_id)
    if unverified_only:
        qy = qy.filter(models.Lead.email_verified.is_(False))
    if unassigned_only:
        qy = qy.filter(models.Lead.agent_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(or_(models.Lead.email.ilike(like),
                           models.Lead.name.ilike(like),
                           models.Lead.company.ilike(like)))
    return qy


@router.get("/paged")
def list_leads_paged(status: str | None = Query(default=None),
                     agent_id: int | None = Query(default=None),
                     unverified_only: bool = Query(default=False),
                     unassigned_only: bool = Query(default=False),
                     q: str = Query(""),
                     page: int = Query(default=1, ge=1),
                     per_page: int = Query(default=30, ge=5, le=200),
                     db: Session = Depends(get_db)):
    """Paginated with total — the UI uses this for proper 'Page X of Y' pagers.
    Handles 50k+ leads cleanly."""
    from sqlalchemy import func, or_
    qy = _apply_lead_filters(db.query(models.Lead), status, agent_id,
                             unverified_only, unassigned_only, q)
    total = qy.with_entities(func.count(models.Lead.id)).scalar() or 0
    rows = (qy.order_by(models.Lead.priority.desc(), models.Lead.created_at.desc())
              .offset((page - 1) * per_page).limit(per_page).all())
    agent_names = {a.id: a.name for a in db.query(models.Agent.id, models.Agent.name).all()}

    # Same-day dedupe: for leads on THIS page, find any outbound email sent
    # TODAY by a DIFFERENT agent than the one assigned — that locks the lead
    # until midnight UTC (the exact restriction the celery worker enforces).
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
    sent_today_by = {}   # lead_id -> set of agent_ids who emailed it today
    for lead_id, agent_id in locked_rows:
        sent_today_by.setdefault(lead_id, set()).add(agent_id)
    unlock_at = today_start + timedelta(days=1)

    items = []
    for l in rows:
        d = schemas.LeadOut.model_validate(l, from_attributes=True).model_dump()
        d["agent_name"] = agent_names.get(l.agent_id, "")
        senders_today = sent_today_by.get(l.id, set())
        if senders_today and (senders_today - {l.agent_id}):
            d["locked_until"] = unlock_at   # a DIFFERENT agent already sent today
        items.append(d)
    return {
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
        "items": items,
    }


@router.post("/bulk-delete")
def bulk_delete(ids: list[int], request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(current_user)):
    """Delete many leads at once (used by the 'select multiple + delete' UI)."""
    if not ids:
        return {"deleted": 0}
    ids = list(dict.fromkeys(ids))[:1000]      # cap at 1000/req
    db.query(models.EmailMessage).filter(models.EmailMessage.lead_id.in_(ids))\
      .delete(synchronize_session=False)
    n = db.query(models.Lead).filter(models.Lead.id.in_(ids))\
          .delete(synchronize_session=False)
    db.commit()
    audit.log(db, user, "leads.bulk_delete", "lead", "", f"{n} lead(s)",
             request.client.host if request.client else "")
    return {"deleted": n}


@router.post("/bulk-garbage")
def bulk_garbage(ids: list[int], db: Session = Depends(get_db)):
    """Move many selected leads straight to Garbage (not deleted — reviewable).
    Powers 'Suspicious (unverified) only -> select all -> Move to Garbage'."""
    if not ids:
        return {"moved": 0}
    ids = list(dict.fromkeys(ids))[:5000]
    n = (db.query(models.Lead).filter(models.Lead.id.in_(ids))
         .update({models.Lead.status: models.LeadStatus.garbage},
                 synchronize_session=False))
    db.commit()
    return {"moved": n}


@router.post("/unverified-to-garbage")
def unverified_to_garbage(db: Session = Depends(get_db)):
    """Move every UNVERIFIED lead (email_verified is False) that isn't already
    in garbage into garbage in one click. They aren't deleted — they sit in
    Garbage where you can review, restore, or purge them. Genuine leads are no
    longer wrongly flagged (see mailer.classify_recipient), so what lands here
    is now a much cleaner 'actually bad' set."""
    n = (db.query(models.Lead)
         .filter(models.Lead.email_verified.is_(False),
                 models.Lead.status != models.LeadStatus.garbage)
         .update({models.Lead.status: models.LeadStatus.garbage},
                 synchronize_session=False))
    db.commit()
    return {"moved": n}


@router.post("/purge-completed")
def purge_completed(days: int = Query(60, ge=7, le=365), db: Session = Depends(get_db)):
    """FIFO cleanup: delete completed/closed leads that haven't had ANY
    activity in N days — plus all their messages. Keeps the DB lean at
    50k+ scale.

    'No activity' means the most recent of: upload date, last outbound
    email, last inbound reply — is older than the cutoff. This matters:
    a lead uploaded 70 days ago but enrolled/closed yesterday must NOT be
    purged just because its original upload date is old. Only leads that
    are BOTH closed/garbage AND genuinely untouched for N days go."""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    olds = (db.query(models.Lead.id)
              .filter(models.Lead.status.in_([models.LeadStatus.closed,
                                              models.LeadStatus.garbage]),
                      models.Lead.created_at < cutoff,
                      # last_outbound_at / last_inbound_at, if set, must ALSO predate cutoff
                      (models.Lead.last_outbound_at.is_(None)) | (models.Lead.last_outbound_at < cutoff),
                      (models.Lead.last_inbound_at.is_(None)) | (models.Lead.last_inbound_at < cutoff))
              .all())
    ids = [i for (i,) in olds]
    if not ids:
        return {"deleted": 0}
    db.query(models.EmailMessage).filter(models.EmailMessage.lead_id.in_(ids))\
      .delete(synchronize_session=False)
    n = db.query(models.Lead).filter(models.Lead.id.in_(ids))\
          .delete(synchronize_session=False)
    db.commit()
    return {"deleted": n, "cutoff": cutoff.isoformat()}


@router.get("/stats")
def leads_stats(db: Session = Depends(get_db)):
    """Counts by status PLUS the summary keys the Leads banner reads
    (total/new/enrolled/contacted/replied/garbage). The banner was showing 0
    because it read stats.total while this only returned per-status keys."""
    from sqlalchemy import func
    rows = (db.query(models.Lead.status, func.count(models.Lead.id))
              .group_by(models.Lead.status).all())
    by_status = {(s.value if hasattr(s, "value") else str(s)): n for s, n in rows}
    total = sum(by_status.values())
    out = {
        "total": total,
        "new": by_status.get("new", 0),
        "enrolled": by_status.get("enrolled", 0),
        "contacted": by_status.get("contacted", 0),
        "replied": by_status.get("replied", 0),
        "garbage": by_status.get("garbage", 0),
    }
    out.update(by_status)   # keep raw per-status keys too (back-compat)
    return out


@router.post("/upload")
async def upload_leads(file: UploadFile = File(...),
                      agent_id: int | None = Form(None),
                      campaign_id: int | None = Form(None),
                      db: Session = Depends(get_db)):
    """FAST bulk upload. The old version ran one DB query AND one live DNS
    lookup PER ROW (≈2 blocking calls × N rows). Now: one query for all
    existing emails, no DNS at upload (email_verified stays NULL = 'not checked
    yet'), and a single bulk insert. DNS/SMTP happens later on 'Verify
    mailboxes'. If agent_id + campaign_id are passed, leads land already
    enrolled with that agent — no more one-by-one 'Pick agent'."""
    if not file.filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, "Only .xlsx, .xls or .csv files are allowed")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, "File too large (max 5 MB)")
    try:
        rows = excel_import.parse_leads(file.filename, raw)
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")

    incoming = {(r.get("email") or "").strip().lower() for r in rows if r.get("email")}
    seen = set()
    if incoming:
        for (e,) in db.query(models.Lead.email).filter(models.Lead.email.in_(incoming)):
            seen.add((e or "").lower())

    status = models.LeadStatus.enrolled if (agent_id and campaign_id) else models.LeadStatus.new
    objs, skipped = [], 0
    for row in rows:
        email = (row.get("email") or "").strip().lower()
        if not email or "@" not in email or email in seen:
            skipped += 1
            continue
        seen.add(email)
        objs.append(models.Lead(**row, source="excel", email_verified=None,
                                agent_id=agent_id, campaign_id=campaign_id, status=status))
    db.bulk_save_objects(objs)
    db.commit()
    return {"created": len(objs), "skipped_duplicates": skipped,
            "unverified": 0, "parsed": len(rows),
            "assigned_to_agent": agent_id, "campaign_id": campaign_id}


@router.post("/verify")
def verify_mailboxes(db: Session = Depends(get_db)):
    """Full mailbox check (email-verify API if a key is configured, else SMTP
    RCPT probe) for every non-garbage lead — not just ones already flagged
    red. This matters: MX-only checking (used at upload for speed when no
    verify API key is set) only proves the DOMAIN can receive mail — e.g.
    'anything@gmail.com' passes MX because gmail.com has mail servers, even
    if that exact mailbox doesn't exist. The API check (Super Admin -> API
    Keys -> Email Verify) actually confirms the specific mailbox; the raw
    SMTP fallback is best-effort since many networks block port 25 outbound
    and Gmail specifically often won't give a clean answer at RCPT time.
    Capped at 500/call — click again to sweep further on very large lists."""
    pending = (db.query(models.Lead)
               .filter(models.Lead.status != models.LeadStatus.garbage)
               .limit(500).all())
    confirmed, still_bad = 0, 0
    for lead in pending:
        ok, _reason = mailer.verify_recipient(lead.email, smtp=True)
        lead.email_verified = ok
        if ok:
            confirmed += 1
        else:
            still_bad += 1
    db.commit()
    return {"checked": len(pending), "confirmed": confirmed, "still_unverified": still_bad}


@router.delete("/all", status_code=200)
def delete_all_leads(request: Request, db: Session = Depends(get_db),
                     user: models.User = Depends(current_user)):
    """Wipe the entire lead list + their messages (full sheet delete)."""
    ids = [l.id for l in db.query(models.Lead.id).all()]
    n = db.query(models.Lead).count()
    db.query(models.EmailMessage).filter(models.EmailMessage.lead_id.isnot(None))\
      .delete(synchronize_session=False)
    db.query(models.Lead).delete(synchronize_session=False)
    db.commit()
    audit.log(db, user, "leads.delete_all", "lead", "", f"{n} lead(s) wiped",
             request.client.host if request.client else "")
    return {"deleted": n}


@router.post("/enroll")
def enroll(data: schemas.EnrollIn, db: Session = Depends(get_db)):
    """Enroll selected leads into a campaign.

    Lock rule (matches what actually happens at send-time): once an agent
    has EMAILED a lead, no OTHER agent can enroll/claim that lead for 24
    hours from that send. Just being enrolled with nothing sent yet does
    NOT lock it — only a real email does. After 24 hours the lock lifts
    automatically and any agent can enroll it again."""
    campaign = db.get(models.Campaign, data.campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    requested_agent_id = data.agent_id or campaign.agent_id
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    unlock_at = today_start + timedelta(days=1)

    n, blocked = 0, []
    for lid in data.lead_ids:
        lead = db.get(models.Lead, lid)
        if not lead or lead.status not in (models.LeadStatus.new, models.LeadStatus.enrolled):
            continue
        last_sent = (db.query(models.EmailMessage)
                     .filter(models.EmailMessage.lead_id == lid,
                             models.EmailMessage.direction == "out",
                             models.EmailMessage.agent_id.isnot(None),
                             models.EmailMessage.created_at >= today_start)
                     .order_by(models.EmailMessage.created_at.desc()).first())
        if last_sent and last_sent.agent_id != requested_agent_id:
            other = db.get(models.Agent, last_sent.agent_id)
            blocked.append({"lead_id": lid, "email": lead.email,
                            "owned_by": other.name if other else f"agent #{last_sent.agent_id}",
                            "unlock_at": unlock_at.isoformat()})
            continue
        lead.campaign_id = campaign.id
        lead.agent_id = requested_agent_id
        lead.status = models.LeadStatus.enrolled
        n += 1
    db.commit()
    return {"enrolled": n, "campaign_id": campaign.id, "blocked": blocked}


@router.post("/enroll-by-filter")
def enroll_by_filter(data: schemas.EnrollByFilter, db: Session = Depends(get_db)):
    """SELECT-ALL-MATCHING enroll+launch. Instead of shipping 50k lead IDs from
    the browser, the UI sends the current filter (status / agent / unverified /
    unassigned / search) and the target campaign + agent. Every matching
    launchable lead (status new|enrolled) is enrolled and split into batches of
    campaign.batch_size, staggered per-agent — the same pipeline as /launch.

    This is what powers 'Select all N matching leads → Enroll & launch' on the
    Leads page, and 'assign all unassigned leads to <agent>'.

    Leads already emailed TODAY by a different agent are skipped (24h lock) and
    reported back in `blocked_count`. Capped at `max_leads` per call so a single
    click can't queue an unbounded job."""
    import random
    from ..tasks import start_campaign_lead

    campaign = db.get(models.Campaign, data.campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    requested_agent_id = data.agent_id or campaign.agent_id
    if not requested_agent_id:
        raise HTTPException(400, "No agent selected (and campaign has no default agent)")
    agent = db.get(models.Agent, requested_agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    qy = _apply_lead_filters(db.query(models.Lead), data.status, data.filter_agent_id,
                             data.unverified_only, data.unassigned_only, data.q)
    qy = qy.filter(models.Lead.status.in_([models.LeadStatus.new,
                                           models.LeadStatus.enrolled]))
    cap = max(1, min(data.max_leads or 20000, 50000))
    leads = qy.order_by(models.Lead.priority.desc()).limit(cap).all()
    if not leads:
        return {"enrolled": 0, "queued": 0, "blocked_count": 0, "batches": []}

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    # bulk-load which of these leads a DIFFERENT agent already emailed today
    ids = [l.id for l in leads]
    locked = {}
    for lid, aid in (db.query(models.EmailMessage.lead_id, models.EmailMessage.agent_id)
                     .filter(models.EmailMessage.lead_id.in_(ids),
                             models.EmailMessage.direction == "out",
                             models.EmailMessage.agent_id.isnot(None),
                             models.EmailMessage.created_at >= today_start).all()):
        locked.setdefault(lid, set()).add(aid)

    launchable = [l for l in leads
                  if not (locked.get(l.id, set()) - {requested_agent_id})]
    blocked_count = len(leads) - len(launchable)
    if not launchable:
        return {"enrolled": 0, "queued": 0, "blocked_count": blocked_count, "batches": []}

    size = max(10, min(2000, campaign.batch_size or 50))
    existing = db.query(models.Batch).filter(models.Batch.campaign_id == campaign.id).count()
    lo = agent.outbound_delay_min or 180
    hi = agent.outbound_delay_max or 720
    batches_made, batch_offset = [], 0

    for i in range(0, len(launchable), size):
        chunk = launchable[i:i + size]
        batch = models.Batch(campaign_id=campaign.id,
                             number=existing + len(batches_made) + 1,
                             total=len(chunk), status=models.BatchStatus.pending)
        db.add(batch)
        db.flush()
        cursor = 0
        for lead in chunk:
            lead.campaign_id = campaign.id
            lead.agent_id = requested_agent_id
            lead.batch_id = batch.id
            lead.status = models.LeadStatus.enrolled
            delay = batch_offset + random.randint(min(lo, hi), max(lo, hi)) \
                    + cursor * random.randint(20, 60)
            start_campaign_lead.apply_async(args=[lead.id], countdown=delay)
            cursor += 1
        batches_made.append(batch.id)
        batch_offset += len(chunk) * ((lo + hi) // 2)
    db.commit()
    return {"enrolled": len(launchable), "queued": len(launchable),
            "blocked_count": blocked_count, "batches": batches_made,
            "batch_size": size}


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


@router.delete("/{lead_id}", status_code=204)
def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(models.Lead, lead_id)
    if lead:
        db.delete(lead)
        db.commit()