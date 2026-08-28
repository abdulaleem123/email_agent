"""Per-agent inbox: every conversation grouped under its agent, vertical
thread view, realtime via frontend polling. Shows who sent what and when."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


@router.get("")
def inbox(agent_id: int | None = Query(default=None),
          page: int = Query(1, ge=1),
          per_page: int = Query(30, ge=5, le=100),
          q: str = Query(""),
          db: Session = Depends(get_db)):
    """Conversations (leads with messages), newest activity first, paginated
    so 50k+ leads never dump into one response."""
    base = (db.query(models.Lead.id,
                     func.max(models.EmailMessage.created_at).label("last_at"))
              .join(models.EmailMessage, models.EmailMessage.lead_id == models.Lead.id)
              .filter(models.EmailMessage.is_spam.is_(False)))
    if agent_id:
        base = base.filter(models.Lead.agent_id == agent_id)
    if q:
        like = f"%{q.strip()}%"
        base = base.filter((models.Lead.email.ilike(like)) |
                           (models.Lead.name.ilike(like)) |
                           (models.Lead.company.ilike(like)))
    grouped = base.group_by(models.Lead.id).subquery()
    total = db.query(func.count()).select_from(grouped).scalar() or 0

    rows = (db.query(models.Lead)
              .join(grouped, grouped.c.id == models.Lead.id)
              .order_by(grouped.c.last_at.desc())
              .offset((page - 1) * per_page)
              .limit(per_page).all())

    items = []
    for lead in rows:
        msgs = [m for m in lead.messages if not m.is_spam]
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
        })
    return {
        "page": page, "per_page": per_page, "total": total,
        "pages": (total + per_page - 1) // per_page,
        "items": items,
    }


@router.get("/thread/{lead_id}")
def thread(lead_id: int, page: int = Query(1, ge=1),
           per_page: int = Query(20, ge=5, le=100),
           db: Session = Depends(get_db)):
    """Paginated messages for a specific conversation — long threads never
    freeze the UI."""
    lead = db.get(models.Lead, lead_id)
    if not lead:
        return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}
    base = (db.query(models.EmailMessage)
              .filter(models.EmailMessage.lead_id == lead_id,
                      models.EmailMessage.is_spam.is_(False)))
    total = base.with_entities(func.count(models.EmailMessage.id)).scalar() or 0
    rows = (base.order_by(models.EmailMessage.created_at.asc())
                 .offset((page - 1) * per_page)
                 .limit(per_page).all())
    agent = db.get(models.Agent, lead.agent_id) if lead.agent_id else None
    return {
        "lead": {"id": lead.id, "email": lead.email, "name": lead.name,
                 "company": lead.company, "agent_id": lead.agent_id,
                 "agent_name": agent.name if agent else "",
                 "ai_paused": lead.ai_paused},
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
def feed(since_id: int = Query(default=0), agent_id: int | None = Query(default=None),
         db: Session = Depends(get_db)):
    """Realtime monitoring feed: frontend polls with the last seen message id."""
    q = (db.query(models.EmailMessage)
         .filter(models.EmailMessage.id > since_id,
                 models.EmailMessage.is_spam.is_(False)))
    if agent_id:
        q = q.filter(models.EmailMessage.agent_id == agent_id)
    return q.order_by(models.EmailMessage.id.asc()).limit(100).all()