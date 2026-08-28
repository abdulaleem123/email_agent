"""Mail Records — a single, paginated, filterable audit of every email
(inbound + outbound + spam) with which agent handled it. Optimized for scale:
handles 50k+ rows via keyset-friendly indexes and hard page-size caps.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
    q: str = Query(""),
    include_spam: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Paginated list. Filters combine (AND). Total count returned so the
    frontend can render a "Page 3 of 47" style pager."""
    query = db.query(models.EmailMessage)
    if not include_spam:
        query = query.filter(models.EmailMessage.is_spam.is_(False))
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

    def serialize(r: models.EmailMessage):
        lead = leads_by.get(r.lead_id)
        agent = agents_by.get(r.agent_id)
        return {
            "id": r.id,
            "direction": r.direction,
            "sent_by": r.sent_by,
            "from_addr": r.from_addr,
            "subject": (r.subject or "").strip()[:200],
            "preview": (r.body or "").strip()[:180],
            "html_used": r.html_used,
            "is_spam": r.is_spam,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "lead_id": r.lead_id,
            "lead_email": lead.email if lead else "",
            "lead_name": (lead.name if lead else "") or "",
            "lead_company": (lead.company if lead else "") or "",
            "agent_id": r.agent_id,
            "agent_name": agent.name if agent else "",
        }

    return {
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
        "items": [serialize(r) for r in rows],
    }


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
              .filter(models.EmailMessage.is_spam.is_(False))
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
    """Delete a batch of selected records at once (checkbox multi-select)."""
    if not data.ids:
        raise HTTPException(400, "No records selected")
    n = (db.query(models.EmailMessage)
         .filter(models.EmailMessage.id.in_(data.ids))
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
    the database lean at 50k+ scale."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    n = (db.query(models.EmailMessage)
           .filter(models.EmailMessage.created_at < cutoff)
           .delete(synchronize_session=False))
    db.commit()
    audit.log(db, user, "mail_records.purge", "email_message", "", f"{n} record(s) older than {days}d",
             request.client.host if request.client else "")
    return {"deleted": n, "cutoff": cutoff.isoformat()}