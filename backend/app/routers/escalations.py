"""ESCALATION — the "a human has to look at this" queue.

Separate from Mail Records and separate from Garbage, on purpose:

- Mail Records = mail that was actually handled (in or out, real conversation).
- Garbage = worthless junk, auto-purged on the garbage clock.
- Escalation = everything in between that an agent must NOT act on by itself:
  meeting / scheduling links, promotions, role-account replies (info@,
  support@, noreply@), system notifications, delivery failures, and any
  outbound that was stopped (blocked address, unverified recipient, send
  failure).

Nothing here is ever auto-replied to, and the related lead is auto-paused
(leads.escalated) so follow-ups stop too. Rows self-purge after
ESCALATION_RETENTION_DAYS (30 by default) — see tasks.purge_escalations.

Built for 50k+ rows: index-backed is_escalation filter, hard page-size cap,
grouped reason chips, single bulk-query join for the lead/agent names.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, audit
from ..security import current_user
from ..config import settings

router = APIRouter(prefix="/api/escalations", tags=["escalations"])

MAX_PAGE_SIZE = 100

# Reason groups shown as filter chips. Stored reasons are "<group>" or
# "<group>: <detail>" (e.g. "role-account: info@acme.com"), so every query
# matches the group with an equality OR a prefix match.
REASON_GROUPS = (
    "needs-human",
    "meeting-link",
    "promotion",
    "delivery-failed",
    "role-account",
    "system-notification",
    "disposable-address",
    "blocked-outbound",
    "unverified-recipient",
    "send-failed",
)

REASON_LABELS = {
    # The user asked for this one: the prospect asked about pricing, a contract,
    # legal, security or who the company is. The AI never answers those, the
    # thread stays in Messages so a human can, and it shows up here too.
    "needs-human": "Asked price / contract / legal / security",
    "meeting-link": "Meeting / scheduling link",
    "promotion": "Promotion / marketing",
    "delivery-failed": "Delivery failed",
    "role-account": "Role account (info@ / support@ / noreply@)",
    "system-notification": "System notification",
    "disposable-address": "Disposable mailbox",
    "blocked-outbound": "Outbound blocked",
    "unverified-recipient": "Unverified recipient",
    "send-failed": "Send failed",
}


def _group_filter(query, reason: str):
    group = (reason or "").strip()
    if not group:
        return query
    return query.filter(or_(
        models.EmailMessage.escalation_reason == group,
        models.EmailMessage.escalation_reason.ilike(f"{group}:%"),
    ))


def _decorate(rows, db: Session):
    """Attach lead + agent + batch + campaign names without an N+1 storm."""
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
    camps_by = dict(db.query(models.Campaign.id, models.Campaign.name)
                    .filter(models.Campaign.id.in_(camp_ids)).all()) if camp_ids else {}

    out = []
    for r in rows:
        lead = leads_by.get(r.lead_id)
        agent = agents_by.get(r.agent_id)
        batch = batches_by.get(lead.batch_id) if lead else None
        reason = r.escalation_reason or ""
        out.append({
            "id": r.id,
            "direction": r.direction,
            "from_addr": r.from_addr or "",
            "subject": (r.subject or "").strip()[:200],
            "preview": (r.body or "").strip()[:200],
            "reason": reason,
            "reason_group": reason.split(":", 1)[0] if reason else "",
            "reason_label": REASON_LABELS.get(reason.split(":", 1)[0], reason),
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "lead_id": r.lead_id,
            "lead_email": lead.email if lead else (r.from_addr or ""),
            "lead_name": (lead.name if lead else "") or "",
            "lead_company": (lead.company if lead else "") or "",
            "lead_status": (lead.status.value if lead and hasattr(lead.status, "value")
                            else (lead.status if lead else "")),
            "agent_paused": bool(lead.escalated or lead.needs_human) if lead else False,
            # needs-human rows keep their thread in Messages, so the operator can
            # jump straight to the conversation. Everything else is parked out of
            # Messages until Resume.
            "in_messages": bool(lead.needs_human and not lead.escalated) if lead else False,
            "needs_human": bool(lead.needs_human) if lead else False,
            "not_interested": bool(lead.not_interested) if lead else False,
            "agent_id": r.agent_id,
            "agent_name": agent.name if agent else "",
            "batch_no": f"B#{batch.number}" if batch else "",
            "campaign_name": (camps_by.get(lead.campaign_id, "") if lead else "") or "",
        })
    return out


@router.get("")
def list_escalations(page: int = Query(1, ge=1),
                     per_page: int = Query(25, ge=5, le=MAX_PAGE_SIZE),
                     reason: str = Query(""),
                     direction: str = Query("", pattern="^(in|out|)$"),
                     agent_id: Optional[int] = Query(None),
                     q: str = Query(""),
                     db: Session = Depends(get_db)):
    query = db.query(models.EmailMessage).filter(
        models.EmailMessage.is_escalation.is_(True))
    query = _group_filter(query, reason)
    if direction:
        query = query.filter(models.EmailMessage.direction == direction)
    if agent_id is not None:
        query = query.filter(models.EmailMessage.agent_id == agent_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            models.EmailMessage.subject.ilike(like),
            models.EmailMessage.body.ilike(like),
            models.EmailMessage.from_addr.ilike(like),
            models.EmailMessage.escalation_reason.ilike(like),
        ))
    total = query.with_entities(func.count(models.EmailMessage.id)).scalar() or 0
    rows = (query.order_by(models.EmailMessage.created_at.desc(),
                           models.EmailMessage.id.desc())
                 .offset((page - 1) * per_page)
                 .limit(per_page).all())
    return {
        "page": page, "per_page": per_page, "total": total,
        "pages": max(1, -(-total // per_page)),
        "items": _decorate(rows, db),
    }


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    """Counts per reason group for the filter chips + the header tiles."""
    rows = (db.query(models.EmailMessage.escalation_reason,
                     func.count(models.EmailMessage.id))
            .filter(models.EmailMessage.is_escalation.is_(True))
            .group_by(models.EmailMessage.escalation_reason).all())
    per = {g: 0 for g in REASON_GROUPS}
    for reason, cnt in rows:
        group = (reason or "").split(":", 1)[0]
        per[group] = per.get(group, 0) + cnt
    paused = (db.query(models.Lead)
              .filter(models.Lead.escalated.is_(True)).count())
    return {
        "total": sum(per.values()),
        "by_reason": per,
        "labels": REASON_LABELS,
        "agents_auto_paused": paused,
        "retention_days": settings.ESCALATION_RETENTION_DAYS,
    }


@router.get("/{mid}")
def get_escalation(mid: int, db: Session = Depends(get_db)):
    r = db.get(models.EmailMessage, mid)
    if not r or not r.is_escalation:
        raise HTTPException(404, "Escalation not found")
    return (_decorate([r], db) or [{}])[0] | {
        "body": r.body or "",
    }


@router.post("/{mid}/resume")
def resume_lead(mid: int, db: Session = Depends(get_db)):
    """Clear the auto-pause so the agent may talk to that lead again. Removes
    this escalation row too — the lead is the thing that stays stuck otherwise."""
    r = db.get(models.EmailMessage, mid)
    if not r or not r.is_escalation:
        raise HTTPException(404, "Escalation not found")
    # Read the FK BEFORE deleting - after commit the instance is gone and any
    # attribute read would raise ObjectDeletedError.
    lead_id = r.lead_id
    lead = db.get(models.Lead, lead_id) if lead_id else None
    if lead:
        lead.escalated = False
        lead.escalation_reason = ""
        # A needs-human thread stays in Messages and is marked, not escalated, so
        # Resume has to clear that marker too or the agent keeps skipping it.
        if lead.needs_human:
            lead.needs_human = False
            lead.needs_human_reason = ""
            lead.ai_paused = False
        if lead.status == models.LeadStatus.garbage:
            lead.status = models.LeadStatus.contacted
    db.delete(r)
    db.commit()
    return {"resumed": True, "lead_id": lead_id}


class BulkIds(BaseModel):
    ids: list[int]


@router.post("/bulk-delete")
def bulk_delete(data: BulkIds, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(current_user)):
    if not data.ids:
        raise HTTPException(400, "No escalations selected")
    # Chunked: "select all" across a long backlog is thousands of ids, and a
    # single IN (...) that size exceeds Postgres' bind-parameter limit and
    # surfaces as a 500 on a button that clearly worked on smaller lists.
    ids = list(dict.fromkeys(data.ids))[:100000]
    n = 0
    for i in range(0, len(ids), 2000):
        n += (db.query(models.EmailMessage)
              .filter(models.EmailMessage.id.in_(ids[i:i + 2000]),
                      models.EmailMessage.is_escalation.is_(True))
              .delete(synchronize_session=False))
    db.commit()
    audit.log(db, user, "escalations.bulk_delete", "email_message", "",
              f"{n} escalation(s)", request.client.host if request.client else "")
    return {"deleted": n}


@router.delete("/{mid}", status_code=204)
def delete_one(mid: int, request: Request, db: Session = Depends(get_db),
               user: models.User = Depends(current_user)):
    r = db.get(models.EmailMessage, mid)
    if r and r.is_escalation:
        db.delete(r)
        db.commit()
        audit.log(db, user, "escalations.delete", "email_message", mid, "",
                  request.client.host if request.client else "")


@router.post("/clear")
def clear_all(request: Request, db: Session = Depends(get_db),
              user: models.User = Depends(current_user)):
    n = (db.query(models.EmailMessage)
         .filter(models.EmailMessage.is_escalation.is_(True))
         .delete(synchronize_session=False))
    db.commit()
    audit.log(db, user, "escalations.clear", "email_message", "",
              f"{n} escalation(s)", request.client.host if request.client else "")
    return {"deleted": n}


@router.post("/purge-older-than")
def purge_older(request: Request, days: int = Query(30, ge=1, le=365),
                db: Session = Depends(get_db),
                user: models.User = Depends(current_user)):
    """Manual version of the daily auto-purge — the beat does this on its own at
    ESCALATION_RETENTION_DAYS, so this is only for 'clean it up right now'."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    n = (db.query(models.EmailMessage)
         .filter(models.EmailMessage.is_escalation.is_(True),
                 models.EmailMessage.created_at < cutoff)
         .delete(synchronize_session=False))
    db.commit()
    audit.log(db, user, "escalations.purge", "email_message", "",
              f"{n} escalation(s) older than {days}d",
              request.client.host if request.client else "")
    return {"deleted": n, "cutoff": cutoff.isoformat()}


@router.get("/feed/new")
def feed_new(since_id: int = Query(0), db: Session = Depends(get_db)):
    """Real-time badge: how many escalations landed since the page was opened."""
    n = (db.query(func.count(models.EmailMessage.id))
         .filter(models.EmailMessage.is_escalation.is_(True),
                 models.EmailMessage.id > since_id).scalar() or 0)
    latest = (db.query(func.max(models.EmailMessage.id))
              .filter(models.EmailMessage.is_escalation.is_(True)).scalar() or 0)
    return {"new": n, "latest_id": latest}
