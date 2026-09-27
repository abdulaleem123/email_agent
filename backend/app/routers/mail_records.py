"""Mail Records — a single, paginated, filterable audit of every email that
was actually HANDLED (inbound + outbound) with which agent handled it, plus the
batch / campaign each send belonged to. Optimized for scale: handles 50k+ rows
via keyset-friendly indexes and hard page-size caps.

Two buckets are deliberately NOT here, each because it has its own page:
- spam / junk          -> /api/garbage
- escalations          -> /api/escalations  (meeting links, promotions,
                          role-account replies, delivery failures, blocked
                          outbound — a human decides, the agent never replies)
Pass include_escalation=true only if you really want them mixed in here.
"""
from datetime import datetime, timedelta
from io import BytesIO
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, audit
from ..security import current_user

router = APIRouter(prefix="/api/mail-records", tags=["mail-records"])

MAX_PAGE_SIZE = 100


@router.get("")
def list_records(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=5, le=MAX_PAGE_SIZE),
    direction: str = Query("", pattern="^(in|out|)$"),
    agent_id: int | None = Query(None),
    lead_id: int | None = Query(None),
    batch_id: int | None = Query(None),
    source_file: str = Query(""),
    q: str = Query(""),
    include_spam: bool = Query(False),
    include_escalation: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Paginated list. Filters combine (AND). Total count returned so the
    frontend can render a "Page 3 of 47" style pager."""
    query = db.query(models.EmailMessage)
    if not include_spam:
        query = query.filter(models.EmailMessage.is_spam.is_(False))
    if not include_escalation:
        query = query.filter(models.EmailMessage.is_escalation.is_(False))
    if direction:
        query = query.filter(models.EmailMessage.direction == direction)
    if agent_id is not None:
        query = query.filter(models.EmailMessage.agent_id == agent_id)
    if lead_id is not None:
        query = query.filter(models.EmailMessage.lead_id == lead_id)
    if batch_id is not None:
        # Resolve through Lead -> Batch. The batch filter is on the lead, not on
        # the message, because that is where the batch actually lives.
        query = query.filter(models.EmailMessage.lead_id.in_(
            db.query(models.Lead.id).filter(models.Lead.batch_id == batch_id)))
    if source_file:
        query = query.filter(models.EmailMessage.lead_id.in_(
            db.query(models.Lead.id)
              .filter(models.Lead.batch_id.in_(
                  db.query(models.Batch.id)
                    .filter(models.Batch.source_filename == source_file)))))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            models.EmailMessage.subject.ilike(like),
            models.EmailMessage.body.ilike(like),
            models.EmailMessage.from_addr.ilike(like),
        ))

    total = query.with_entities(func.count(models.EmailMessage.id)).scalar() or 0
    rows = (query.order_by(models.EmailMessage.created_at.desc())
                 .offset((page - 1) * per_page)
                 .limit(per_page).all())

    # eager join lead + agent names for the UI (avoids N+1)
    lead_ids = {r.lead_id for r in rows if r.lead_id}
    agent_ids = {r.agent_id for r in rows if r.agent_id}
    leads_by = {l.id: l for l in db.query(models.Lead)
                                    .filter(models.Lead.id.in_(lead_ids)).all()} if lead_ids else {}
    agents_by = {a.id: a for a in db.query(models.Agent)
                                     .filter(models.Agent.id.in_(agent_ids)).all()} if agent_ids else {}
    batch_ids = {l.batch_id for l in leads_by.values() if l.batch_id}
    batches_by = {b.id: b for b in db.query(models.Batch)
                                      .filter(models.Batch.id.in_(batch_ids)).all()} if batch_ids else {}
    camp_ids = {l.campaign_id for l in leads_by.values() if l.campaign_id}
    camps_by = {c.id: c.name for c in db.query(models.Campaign.id, models.Campaign.name)
                 .filter(models.Campaign.id.in_(camp_ids)).all()} if camp_ids else {}

    def serialize(r: models.EmailMessage):
        lead = leads_by.get(r.lead_id)
        agent = agents_by.get(r.agent_id)
        batch = batches_by.get(lead.batch_id) if lead else None
        # Fall back to the lead's own upload tag for records whose batch predates
        # the source_filename column, so a file name is always showable.
        src_file = ((batch.source_filename if batch else "")
                    or (lead.upload_tag if lead else "") or "")
        return {
            "id": r.id,
            "direction": r.direction,
            "sent_by": r.sent_by,
            "from_addr": r.from_addr,
            "subject": (r.subject or "").strip()[:200],
            "preview": (r.body or "").strip()[:180],
            "html_used": r.html_used,
            "is_spam": r.is_spam,
            "spam_reason": r.spam_reason or "",
            "is_escalation": r.is_escalation,
            "escalation_reason": r.escalation_reason or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "lead_id": r.lead_id,
            "lead_email": lead.email if lead else "",
            "lead_name": (lead.name if lead else "") or "",
            "lead_company": (lead.company if lead else "") or "",
            "batch_id": batch.id if batch else None,
            "batch_no": f"B#{batch.number}" if batch else "",
            "batch_size": batch.total if batch else 0,
            "batch_sent": batch.sent if batch else 0,
            "batch_status": batch.status.value if batch and batch.status else "",
            "source_file": src_file,
            "campaign_name": (camps_by.get(lead.campaign_id, "") if lead else "") or "",
            "agent_id": r.agent_id,
            "agent_name": agent.name if agent else "",
        }

    return {
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
        "items": [serialize(r) for r in rows],
        "source_files": source_files(db),
    }


@router.get("/batches")
def list_batches(
    campaign_id: int | None = Query(None),
    source_file: str = Query(""),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Every batch, newest first, with the Excel it came from and how far it
    got. This is the page behind "Mail Records shows batches of 20/30/40/50 per
    file" and the source of truth for enrolling one batch."""
    q = db.query(models.Batch)
    if campaign_id is not None:
        q = q.filter(models.Batch.campaign_id == campaign_id)
    if source_file:
        q = q.filter(models.Batch.source_filename == source_file)
    rows = (q.order_by(models.Batch.created_at.desc(), models.Batch.id.desc())
             .limit(limit).all())
    camp_ids = {b.campaign_id for b in rows if b.campaign_id}
    camps = {c.id: c.name for c in db.query(models.Campaign.id, models.Campaign.name)
                             .filter(models.Campaign.id.in_(camp_ids)).all()} if camp_ids else {}
    return {
        "items": [{
            "id": b.id,
            "number": b.number,
            "total": b.total,
            "sent": b.sent,
            "failed": b.failed,
            "status": b.status.value if b.status else "",
            "source_file": b.source_filename or "",
            "campaign_id": b.campaign_id,
            "campaign_name": camps.get(b.campaign_id, "") or "",
            "created_at": b.created_at.isoformat() if b.created_at else "",
        } for b in rows],
        "source_files": source_files(db),
    }


def source_files(db: Session) -> list[str]:
    """Distinct Excel names that have batches. Cheap: one indexed group-by on
    a bounded distinct set, not a scan of every message."""
    rows = (db.query(models.Batch.source_filename)
            .filter(models.Batch.source_filename != "")
            .distinct().order_by(models.Batch.source_filename).all())
    return [r[0] for r in rows]



@router.get("/export")
def export_records(
    direction: str = Query("", pattern="^(in|out|)$"),
    agent_id: int | None = Query(None),
    lead_id: int | None = Query(None),
    q: str = Query(""),
    include_spam: bool = Query(False),
    include_escalation: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Download a real Excel sheet (.xlsx) of every mail record with the
    Batch # + Campaign it belongs to — 'which send went to which batch'.
    Uses the same filters as the page and exports up to 50 000 rows."""
    query = db.query(models.EmailMessage)
    if not include_spam:
        query = query.filter(models.EmailMessage.is_spam.is_(False))
    if not include_escalation:
        query = query.filter(models.EmailMessage.is_escalation.is_(False))
    if direction:
        query = query.filter(models.EmailMessage.direction == direction)
    if agent_id is not None:
        query = query.filter(models.EmailMessage.agent_id == agent_id)
    if lead_id is not None:
        query = query.filter(models.EmailMessage.lead_id == lead_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            models.EmailMessage.subject.ilike(like),
            models.EmailMessage.body.ilike(like),
            models.EmailMessage.from_addr.ilike(like),
        ))
    rows = (query.order_by(models.EmailMessage.created_at.desc())
                 .limit(50000).all())

    lead_ids = {r.lead_id for r in rows if r.lead_id}
    agent_ids = {r.agent_id for r in rows if r.agent_id}
    leads_by = {l.id: l for l in db.query(models.Lead)
                                    .filter(models.Lead.id.in_(lead_ids)).all()} if lead_ids else {}
    agents_by = {a.id: a for a in db.query(models.Agent)
                                    .filter(models.Agent.id.in_(agent_ids)).all()} if agent_ids else {}
    batch_ids = {l.batch_id for l in leads_by.values() if l.batch_id}
    batches_by = {b.id: b for b in db.query(models.Batch)
                                      .filter(models.Batch.id.in_(batch_ids)).all()} if batch_ids else {}
    camp_ids = {l.campaign_id for l in leads_by.values() if l.campaign_id}
    camps_by = {c.id: c.name for c in db.query(models.Campaign.id, models.Campaign.name)
                 .filter(models.Campaign.id.in_(camp_ids)).all()} if camp_ids else {}

    wb = Workbook()
    ws = wb.active
    ws.title = "Mail Records"
    ws.append(["Source File", "Batch #", "Batch Size", "Campaign", "Agent",
               "Direction", "Sent By", "Contact",
               "Email", "Company", "Subject", "Sent At", "HTML", "Spam", "Spam Reason",
               "Escalation", "Escalation Reason"])
    for r in rows:
        lead = leads_by.get(r.lead_id)
        agent = agents_by.get(r.agent_id)
        batch = batches_by.get(lead.batch_id) if lead else None
        ws.append([
            ((batch.source_filename if batch else "")
             or (lead.upload_tag if lead else "") or ""),
            f"B#{batch.number}" if batch else "",
            batch.total if batch else "",
            camps_by.get(lead.campaign_id, "") if lead else "",
            agent.name if agent else "",
            r.direction,
            r.sent_by or "",
            (lead.name if lead else "") or "",
            (lead.email if lead else "") or r.from_addr or "",
            (lead.company if lead else "") or "",
            (r.subject or "").strip()[:200],
            r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            "yes" if r.html_used else "no",
            "yes" if r.is_spam else "no",
            r.spam_reason or "",
            "yes" if r.is_escalation else "no",
            r.escalation_reason or "",
        ])
    for col in ("B", "C", "D", "E", "F", "G", "H", "I", "J", "L", "M", "N", "O", "P", "Q"):
        ws.column_dimensions[col].width = 16
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["K"].width = 40

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 'attachment; filename="mail-records-report.xlsx"'})


@router.get("/{mid}")
def get_record(mid: int, db: Session = Depends(get_db)):
    r = db.get(models.EmailMessage, mid)
    if not r:
        raise HTTPException(404, "Message not found")
    lead = db.get(models.Lead, r.lead_id) if r.lead_id else None
    agent = db.get(models.Agent, r.agent_id) if r.agent_id else None
    return {
        "id": r.id, "direction": r.direction, "sent_by": r.sent_by,
        "from_addr": r.from_addr, "subject": r.subject, "body": r.body,
        "html_used": r.html_used, "is_spam": r.is_spam,
        "spam_reason": r.spam_reason or "",
        "is_escalation": r.is_escalation,
        "escalation_reason": r.escalation_reason or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "lead_id": r.lead_id,
        "lead_email": lead.email if lead else "",
        "lead_name": (lead.name if lead else "") or "",
        "lead_company": (lead.company if lead else "") or "",
        "agent_id": r.agent_id,
        "agent_name": agent.name if agent else "",
    }


@router.get("/summary/agents")
def agent_summary(db: Session = Depends(get_db)):
    """Counts per agent — 'who did what' at a glance."""
    rows = (db.query(models.EmailMessage.agent_id,
                     models.EmailMessage.direction,
                     func.count(models.EmailMessage.id))
              .filter(models.EmailMessage.is_spam.is_(False),
                      models.EmailMessage.is_escalation.is_(False))
              .group_by(models.EmailMessage.agent_id, models.EmailMessage.direction).all())
    agents = {a.id: a for a in db.query(models.Agent).all()}
    per = {}
    for agent_id, direction, cnt in rows:
        if agent_id is None:
            continue
        d = per.setdefault(agent_id, {"agent_id": agent_id,
                                       "name": agents.get(agent_id).name if agents.get(agent_id) else f"#{agent_id}",
                                       "sent": 0, "received": 0})
        if direction == "out":
            d["sent"] += cnt
        elif direction == "in":
            d["received"] += cnt
    return sorted(per.values(), key=lambda x: (x["sent"] + x["received"]), reverse=True)


class BulkIds(BaseModel):
    ids: list[int]


@router.post("/bulk-delete")
def bulk_delete(data: BulkIds, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(current_user)):
    """Delete a batch of selected records at once (checkbox multi-select).

    Chunked so clearing a long history does not blow past Postgres' bind
    parameter limit and 500 on the button."""
    if not data.ids:
        raise HTTPException(400, "No records selected")
    ids = list(dict.fromkeys(data.ids))[:100000]
    n = 0
    for i in range(0, len(ids), 2000):
        n += (db.query(models.EmailMessage)
              .filter(models.EmailMessage.id.in_(ids[i:i + 2000]))
              .delete(synchronize_session=False))
    db.commit()
    audit.log(db, user, "mail_records.bulk_delete", "email_message", "", f"{n} record(s)",
              request.client.host if request.client else "")
    return {"deleted": n}


@router.delete("/{mid}", status_code=204)
def delete_record(mid: int, request: Request, db: Session = Depends(get_db),
                  user: models.User = Depends(current_user)):
    r = db.get(models.EmailMessage, mid)
    if r:
        db.delete(r)
        db.commit()
        audit.log(db, user, "mail_records.delete", "email_message", mid, "",
                 request.client.host if request.client else "")


@router.post("/purge-older-than")
def purge_older(request: Request, days: int = Query(90, ge=7, le=365), db: Session = Depends(get_db),
                user: models.User = Depends(current_user)):
    """Delete every mail record older than N days (default 90). Used to keep
    the database lean at 50k+ scale. Escalations are skipped — they age out on
    their own retention clock, not this one."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    n = (db.query(models.EmailMessage)
           .filter(models.EmailMessage.created_at < cutoff,
                   models.EmailMessage.is_escalation.is_(False))
           .delete(synchronize_session=False))
    db.commit()
    audit.log(db, user, "mail_records.purge", "email_message", "", f"{n} record(s) older than {days}d",
             request.client.host if request.client else "")
    return {"deleted": n, "cutoff": cutoff.isoformat()}


@router.get("/feed/new")
def feed_new(since_id: int = Query(0), agent_id: int | None = Query(None),
             db: Session = Depends(get_db)):
    """Real-time polling endpoint — returns only records created AFTER since_id.
    The frontend polls this every 8 seconds to update Mail Records without a
    full page reload. Returns max 50 newest; caller updates its since_id to
    the highest id seen."""
    q = (db.query(models.EmailMessage)
           .filter(models.EmailMessage.id > since_id,
                   models.EmailMessage.is_spam.is_(False),
                   models.EmailMessage.is_escalation.is_(False)))
    if agent_id:
        q = q.filter(models.EmailMessage.agent_id == agent_id)
    rows = q.order_by(models.EmailMessage.id.desc()).limit(50).all()
    lead_ids = {r.lead_id for r in rows if r.lead_id}
    agent_ids = {r.agent_id for r in rows if r.agent_id}
    leads_by = {l.id: l for l in db.query(models.Lead).filter(
        models.Lead.id.in_(lead_ids)).all()} if lead_ids else {}
    agents_by = {a.id: a for a in db.query(models.Agent).filter(
        models.Agent.id.in_(agent_ids)).all()} if agent_ids else {}
    return [{"id": r.id, "direction": r.direction,
             "subject": (r.subject or "")[:200],
             "preview": (r.body or "")[:180],
             "created_at": r.created_at.isoformat() if r.created_at else "",
             "lead_email": (leads_by.get(r.lead_id) or models.Lead()).email or "",
             "lead_name": (leads_by.get(r.lead_id) or models.Lead()).name or "",
             "lead_company": (leads_by.get(r.lead_id) or models.Lead()).company or "",
             "agent_name": (agents_by.get(r.agent_id) or models.Agent()).name or "",
             } for r in rows]


@router.get("/{mid}/full")
def get_record_full(mid: int, db: Session = Depends(get_db)):
    """Full email body for the detail drawer."""
    r = db.get(models.EmailMessage, mid)
    if not r:
        raise HTTPException(404, "Not found")
    lead = db.get(models.Lead, r.lead_id) if r.lead_id else None
    agent = db.get(models.Agent, r.agent_id) if r.agent_id else None
    return {"id": r.id, "direction": r.direction, "subject": r.subject or "",
            "body": r.body or "", "from_addr": r.from_addr or "",
            "html_used": r.html_used, "is_spam": r.is_spam,
            "is_escalation": r.is_escalation,
            "escalation_reason": r.escalation_reason or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "lead_email": lead.email if lead else "",
            "lead_name": lead.name if lead else "",
            "lead_company": lead.company if lead else "",
            "agent_name": agent.name if agent else "",
            "website": lead.website if lead else ""}