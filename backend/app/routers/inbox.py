"""Messages — the per-agent conversation list.

DEFAULT VIEW IS HOT-ONLY. A thread is "hot" when the prospect actually talked
back and the conversation is still alive:
  - the lead has replied at least once (an inbound is the newest message, or
    arrived after our last outbound), and
  - that activity is inside STALE_LEAD_DAYS (30) — the same window the daily
    stale_leads_sweep uses to retire dead threads into Garbage, and
  - the lead is not garbage / closed / escalated (escalated threads are parked
    on the Escalation page where a human decides).

Outbound-only threads (we emailed, silence), dead threads and escalated ones
are hidden. Pass all_threads=true to see every thread again — the toggle is
one click away because the audit history is still worth having.

Also excludes escalations and spam outright: neither is a conversation.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session
from ..config import settings
from ..database import get_db
from .. import models, schemas

router = APIRouter(prefix="/api/inbox", tags=["inbox"])

HOT_WINDOW_DAYS = settings.STALE_LEAD_DAYS


@router.get("")
def inbox(agent_id: Optional[int] = Query(default=None),
          page: int = Query(1, ge=1),
          per_page: int = Query(30, ge=5, le=100),
          q: str = Query(""),
          all_threads: bool = Query(False),
          hot_days: int = Query(HOT_WINDOW_DAYS, ge=1, le=365),
          db: Session = Depends(get_db)):
    """Conversations (leads with messages), newest activity first, paginated
    so 50k+ leads never dump into one response. all_threads=true turns off the
    hot-only filter."""
    base = (db.query(models.Lead.id,
                     func.max(models.EmailMessage.created_at).label("last_at"))
            .join(models.EmailMessage, models.EmailMessage.lead_id == models.Lead.id)
            .filter(models.EmailMessage.is_spam.is_(False),
                    models.EmailMessage.is_escalation.is_(False)))
    if agent_id:
        base = base.filter(models.Lead.agent_id == agent_id)
    if q:
        like = f"%{q.strip()}%"
        base = base.filter((models.Lead.email.ilike(like)) |
                           (models.Lead.name.ilike(like)) |
                           (models.Lead.company.ilike(like)))

    if not all_threads:
        # A lead is hot when it is alive in the pipeline, nobody has escalated
        # it, it has actually replied, and the newest message on the thread is
        # inside the hot window. Everything else is either a dead thread (the
        # daily sweep will garbage it) or already parked on the Escalation page.
        cutoff = datetime.utcnow() - timedelta(days=hot_days)
        last_at = (db.query(models.EmailMessage.lead_id.label("lead_id"),
                            func.max(models.EmailMessage.created_at).label("last_at"))
                   .filter(models.EmailMessage.is_spam.is_(False),
                           models.EmailMessage.is_escalation.is_(False))
                   .group_by(models.EmailMessage.lead_id)
                   .subquery())
        replied = (db.query(models.Lead.id)
                   .join(models.EmailMessage,
                         models.EmailMessage.lead_id == models.Lead.id)
                   .filter(models.EmailMessage.direction == "in",
                           models.EmailMessage.is_spam.is_(False),
                           models.EmailMessage.is_escalation.is_(False))
                   .group_by(models.Lead.id)
                   .subquery())
        base = (base
                .join(last_at, last_at.c.lead_id == models.Lead.id)
                .join(replied, replied.c.id == models.Lead.id)
                .filter(models.Lead.escalated.is_(False),
                        or_(
                            # a live, hot thread
                            and_(models.Lead.status.in_([
                                     models.LeadStatus.enrolled,
                                     models.LeadStatus.contacted,
                                     models.LeadStatus.replied,
                                     models.LeadStatus.meeting]),
                                 last_at.c.last_at >= cutoff),
                            # NOT INTERESTED: the lead is in Trash, but the
                            # requirement is that the conversation stays
                            # readable here — never hidden, never deleted.
                            models.Lead.not_interested.is_(True))))

    grouped = base.group_by(models.Lead.id).subquery()
    total = db.query(func.count()).select_from(grouped).scalar() or 0
    # One extra count for the tab badge: threads waiting on a human. Counted
    # server-side so the frontend never has to guess from the current page.
    needs_human_count = (db.query(func.count(func.distinct(models.Lead.id)))
                         .join(models.EmailMessage,
                               models.EmailMessage.lead_id == models.Lead.id)
                         .filter(models.Lead.needs_human.is_(True),
                                 models.Lead.escalated.is_(False),
                                 models.EmailMessage.is_spam.is_(False),
                                 models.EmailMessage.is_escalation.is_(False))
                         .scalar() or 0)

    rows = (db.query(models.Lead)
              .join(grouped, grouped.c.id == models.Lead.id)
              .order_by(grouped.c.last_at.desc())
              .offset((page - 1) * per_page)
              .limit(per_page).all())

    items = []
    for lead in rows:
        msgs = [m for m in lead.messages
                if not m.is_spam and not m.is_escalation]
        last = msgs[-1] if msgs else None
        items.append({
            "lead_id": lead.id, "name": lead.name, "email": lead.email,
            "company": lead.company, "agent_id": lead.agent_id,
            "temperature": lead.temperature.value if hasattr(lead.temperature, "value") else lead.temperature,
            "status": lead.status.value if hasattr(lead.status, "value") else lead.status,
            "message_count": len(msgs),
            "last_subject": last.subject if last else "",
            "last_snippet": (last.body[:140] if last else ""),
            "last_direction": last.direction if last else "",
            "last_at": last.created_at.isoformat() if last else None,
            "ai_paused": lead.ai_paused,
            "escalated": lead.escalated,
            # A human has to answer this (price, contract, legal, security).
            # Deliberately NOT the same flag as `escalated`: the thread is right
            # here in Messages so the operator can read it and reply, the agent
            # just stopped writing on its own.
            "needs_human": lead.needs_human,
            "needs_human_reason": lead.needs_human_reason,
            # Said not interested — parked in Garbage, purged after retention.
            "not_interested": lead.not_interested,
            "not_interested_note": lead.not_interested_note,
            "hot": True,
        })
    return {
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
        "items": items,
        "hot_only": not all_threads,
        "hot_window_days": hot_days,
        "needs_human": needs_human_count,
    }


@router.get("/thread/{lead_id}")
def thread(lead_id: int, page: int = Query(1, ge=1),
           per_page: int = Query(20, ge=5, le=100),
           db: Session = Depends(get_db)):
    """Paginated messages for a specific conversation — long threads never
    freeze the UI. Escalation rows are excluded: they are not part of the
    conversation, they live on the Escalation page."""
    lead = db.get(models.Lead, lead_id)
    if not lead:
        return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}
    base = (db.query(models.EmailMessage)
              .filter(models.EmailMessage.lead_id == lead_id,
                      models.EmailMessage.is_spam.is_(False),
                      models.EmailMessage.is_escalation.is_(False)))
    total = base.with_entities(func.count(models.EmailMessage.id)).scalar() or 0
    rows = (base.order_by(models.EmailMessage.created_at.asc())
                 .offset((page - 1) * per_page)
                 .limit(per_page).all())
    agent = db.get(models.Agent, lead.agent_id) if lead.agent_id else None
    return {
        "lead": {"id": lead.id, "email": lead.email, "name": lead.name,
                 "company": lead.company, "agent_id": lead.agent_id,
                 "agent_name": agent.name if agent else "",
                 "ai_paused": lead.ai_paused, "escalated": lead.escalated,
                 "escalation_reason": lead.escalation_reason or "",
                 # A human has to answer this. The thread is here (not parked
                 # on the Escalation page) precisely so somebody can reply.
                 "needs_human": lead.needs_human,
                 "needs_human_reason": lead.needs_human_reason or "",
                 "not_interested": lead.not_interested,
                 "not_interested_note": lead.not_interested_note or "",
                 "garbage_at": lead.garbage_at.isoformat() if lead.garbage_at else None},
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
        "items": [{
            "id": m.id, "direction": m.direction, "sent_by": m.sent_by,
            "from_addr": m.from_addr, "subject": m.subject, "body": m.body,
            "html_used": m.html_used,
            "created_at": m.created_at.isoformat() if m.created_at else "",
        } for m in rows],
    }


@router.get("/feed", response_model=list[schemas.MessageOut])
def feed(since_id: int = Query(default=0), agent_id: Optional[int] = Query(default=None),
         db: Session = Depends(get_db)):
    """Realtime monitoring feed: frontend polls with the last seen message id.
    Spam and escalations are both excluded — neither is a conversation."""
    q = (db.query(models.EmailMessage)
         .filter(models.EmailMessage.id > since_id,
                 models.EmailMessage.is_spam.is_(False),
                 models.EmailMessage.is_escalation.is_(False)))
    if agent_id:
        q = q.filter(models.EmailMessage.agent_id == agent_id)
    return q.order_by(models.EmailMessage.id.asc()).limit(100).all()
