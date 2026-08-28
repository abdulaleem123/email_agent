"""Dashboard stats (1d / 15d / 30d / overall, per agent) + notifications."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
WINDOWS = {"1d": 1, "15d": 15, "30d": 30, "all": None}


def _counts(db, agent_id, since):
    q_out = db.query(func.count(models.EmailMessage.id)).filter(
        models.EmailMessage.direction == "out",
        models.EmailMessage.is_spam.is_(False))
    q_in = db.query(func.count(models.EmailMessage.id)).filter(
        models.EmailMessage.direction == "in",
        models.EmailMessage.is_spam.is_(False))
    if agent_id:
        q_out = q_out.filter(models.EmailMessage.agent_id == agent_id)
        q_in = q_in.filter(models.EmailMessage.agent_id == agent_id)
    if since:
        q_out = q_out.filter(models.EmailMessage.created_at >= since)
        q_in = q_in.filter(models.EmailMessage.created_at >= since)
    return q_out.scalar() or 0, q_in.scalar() or 0


@router.get("/stats")
def stats(window: str = Query(default="30d"), db: Session = Depends(get_db)):
    days = WINDOWS.get(window, 30)
    since = datetime.utcnow() - timedelta(days=days) if days else None

    agents = db.query(models.Agent).order_by(models.Agent.id).all()
    per_agent = []
    for a in agents:
        sent, received = _counts(db, a.id, since)
        replied_leads = (db.query(func.count(models.Lead.id))
                         .filter(models.Lead.agent_id == a.id,
                                 models.Lead.status == models.LeadStatus.replied)
                         .scalar() or 0)
        per_agent.append({"agent_id": a.id, "name": a.name, "role": a.role,
                          "is_active": a.is_active, "sent": sent,
                          "received": received, "replied_leads": replied_leads,
                          "daily_limit": a.daily_send_limit})
    total_sent, total_received = _counts(db, None, since)
    spam_q = db.query(func.count(models.EmailMessage.id)).filter(
        models.EmailMessage.is_spam.is_(True))
    if since:
        spam_q = spam_q.filter(models.EmailMessage.created_at >= since)

    hotwarm = dict(db.query(models.Lead.temperature, func.count(models.Lead.id))
                   .group_by(models.Lead.temperature).all())
    return {
        "window": window,
        "totals": {"sent": total_sent, "received": total_received,
                   "garbage": spam_q.scalar() or 0,
                   "leads": db.query(func.count(models.Lead.id)).filter(
                       models.Lead.status != models.LeadStatus.garbage).scalar() or 0,
                   "campaigns": db.query(func.count(models.Campaign.id)).scalar() or 0},
        "temperature": {(k.value if hasattr(k, "value") else str(k)): v
                        for k, v in hotwarm.items()},
        "per_agent": per_agent,
    }


@router.get("/timeseries")
def timeseries(days: int = Query(default=15, ge=1, le=90),
               db: Session = Depends(get_db)):
    """Daily sent/received for the chart."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.query(func.date(models.EmailMessage.created_at),
                     models.EmailMessage.direction,
                     func.count(models.EmailMessage.id))
            .filter(models.EmailMessage.created_at >= since,
                    models.EmailMessage.is_spam.is_(False))
            .group_by(func.date(models.EmailMessage.created_at),
                      models.EmailMessage.direction).all())
    series = {}
    for d, direction, n in rows:
        day = str(d)
        series.setdefault(day, {"date": day, "sent": 0, "received": 0})
        series[day]["sent" if direction == "out" else "received"] = n
    return sorted(series.values(), key=lambda x: x["date"])


@router.get("/notifications", response_model=list[schemas.NotificationOut])
def notifications(unread_only: bool = Query(default=False),
                  agent_id: int | None = Query(default=None),
                  db: Session = Depends(get_db)):
    q = db.query(models.Notification)
    if unread_only:
        q = q.filter(models.Notification.read.is_(False))
    if agent_id:
        q = q.filter(models.Notification.agent_id == agent_id)
    rows = q.order_by(models.Notification.created_at.desc()).limit(50).all()
    agent_names = {a.id: a.name for a in db.query(models.Agent.id, models.Agent.name).all()}
    out = []
    for n in rows:
        d = schemas.NotificationOut.model_validate(n, from_attributes=True).model_dump()
        d["agent_name"] = agent_names.get(n.agent_id, "")
        out.append(d)
    return out


@router.post("/notifications/read")
def mark_read(db: Session = Depends(get_db)):
    db.query(models.Notification).filter(models.Notification.read.is_(False))\
      .update({models.Notification.read: True})
    db.commit()
    return {"ok": True}