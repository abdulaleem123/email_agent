"""Leads: flexible upload (any excel/csv shape), enroll (select-all supported),
research, manual send, delete. Hardened: 5 MB cap, extension allowlist."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas, audit
from ..security import current_user
from ..services import excel_import, tavily, mailer, keys as keysvc
from pydantic import BaseModel
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


@router.get("/paged")
def list_leads_paged(status: str | None = Query(default=None),
                     agent_id: int | None = Query(default=None),
                     unverified_only: bool = Query(default=False),
                     pitch_pending: bool = Query(default=False),
                     q: str = Query(""),
                     page: int = Query(default=1, ge=1),
                     per_page: int = Query(default=30, ge=5, le=200),
                     db: Session = Depends(get_db)):
    """Paginated with total — the UI uses this for proper 'Page X of Y' pagers.
    Handles 50k+ leads cleanly."""
    from sqlalchemy import func, or_
    qy = db.query(models.Lead).filter(models.Lead.status != models.LeadStatus.garbage)
    if status:
        qy = qy.filter(models.Lead.status == status)
    if agent_id:
        qy = qy.filter(models.Lead.agent_id == agent_id)
    if unverified_only:
        qy = qy.filter(models.Lead.email_verified.is_(False))
    if pitch_pending:
        # only leads not marked done in Pitch Decker
        qy = qy.filter(models.Lead.pitch_done.is_(False))
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
    ids = list(dict.fromkeys(data.ids))[:1000] if data.ids else []

    if data.unverified:
        q = db.query(models.Lead).filter(
            models.Lead.status != models.LeadStatus.garbage,
            models.Lead.email_verified.is_(False),
        )
        n = 0
        for lead in q.all():
            lead.status = models.LeadStatus.garbage
            n += 1
        db.commit()
        audit.log(db, user, "leads.unverified_to_garbage", "lead", "", f"{n} lead(s)",
                  request.client.host if request.client else "")
        return {"moved": n, "deleted": 0}

    if not ids:
        return {"deleted": 0, "moved": 0}

    if data.to_garbage:
        n = 0
        for lead in db.query(models.Lead).filter(models.Lead.id.in_(ids)).all():
            lead.status = models.LeadStatus.garbage
            n += 1
        db.commit()
        audit.log(db, user, "leads.bulk_garbage", "lead", "", f"{n} lead(s)",
                  request.client.host if request.client else "")
        return {"moved": n, "deleted": 0}

    # Hard delete
    db.query(models.EmailMessage).filter(models.EmailMessage.lead_id.in_(ids))\
      .delete(synchronize_session=False)
    n = db.query(models.Lead).filter(models.Lead.id.in_(ids))\
          .delete(synchronize_session=False)
    db.commit()
    audit.log(db, user, "leads.bulk_delete", "lead", "", f"{n} lead(s)",
              request.client.host if request.client else "")
    return {"deleted": n, "moved": 0}


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
    """Counts by status (drives the FIFO / cleanup UI)."""
    from sqlalchemy import func
    rows = (db.query(models.Lead.status, func.count(models.Lead.id))
              .group_by(models.Lead.status).all())
    return {(s.value if hasattr(s, "value") else str(s)): n for s, n in rows}


@router.post("/upload")
async def upload_leads(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, "Only .xlsx, .xls or .csv files are allowed")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, "File too large (max 5 MB)")
    try:
        rows = excel_import.parse_leads(file.filename, raw)
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")

    created, skipped, unverified = 0, 0, 0
    for row in rows:
        if db.query(models.Lead).filter(models.Lead.email == row["email"]).first():
            skipped += 1
            continue
        # MX-only at upload for speed (50k+ scale) — click "Verify mailboxes"
        # for the deeper SMTP-level check.
        ok, _reason = mailer.verify_recipient(row["email"], smtp=False)
        if not ok:
            unverified += 1
        db.add(models.Lead(**row, source="excel", email_verified=ok))
        created += 1
    db.commit()
    return {"created": created, "skipped_duplicates": skipped,
            "unverified": unverified, "parsed": len(rows)}


@router.post("/verify")
def verify_mailboxes(db: Session = Depends(get_db)):
    """MX-only check for every non-garbage lead. MX proves the DOMAIN can
    receive mail — fast, no port-25 needed, works perfectly for Zoho/Gmail/
    Outlook domains. SMTP RCPT probe removed: it's blocked by most modern mail
    servers anyway, causing false negatives on real leads. The domain check is
    enough to confirm the lead is at a real mail-receiving domain.
    Capped at 500/call — click again for larger lists."""
    pending = (db.query(models.Lead)
               .filter(models.Lead.status != models.LeadStatus.garbage,
                       models.Lead.email_verified.isnot(True))
               .limit(500).all())
    confirmed, still_bad = 0, 0
    for lead in pending:
        # MX-only: smtp=False means no SMTP RCPT probe, just DNS/MX lookup
        ok, _reason = mailer.verify_recipient(lead.email, smtp=False)
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