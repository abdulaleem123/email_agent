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
    """Daily sent/received for the chart. Always returns all N days (zeros
    for days with no activity) so the chart renders even on a fresh install."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.query(func.date(models.EmailMessage.created_at),
                     models.EmailMessage.direction,
                     func.count(models.EmailMessage.id))
            .filter(models.EmailMessage.created_at >= since,
                    models.EmailMessage.is_spam.is_(False))
            .group_by(func.date(models.EmailMessage.created_at),
                      models.EmailMessage.direction).all())
    series = {}
    # Pre-seed every day in the window with zeros so chart axes always show
    for i in range(days):
        day = str((datetime.utcnow() - timedelta(days=days - 1 - i)).date())
        series[day] = {"date": day, "sent": 0, "received": 0}
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


@router.get("/monitoring")
def monitoring(page: int = Query(1, ge=1), per_page: int = Query(20, ge=5, le=100),
               db: Session = Depends(get_db)):
    """Real-time system monitoring: outbound sent, inbound received, paused
    agents, bounced/failed. Paginated so it never OOMs under high volume."""
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hour_ago = now - timedelta(hours=1)

    agents = db.query(models.Agent).order_by(models.Agent.id).all()
    agent_rows = []
    for a in agents:
        sent_today = (db.query(func.count(models.EmailMessage.id))
                      .filter(models.EmailMessage.agent_id == a.id,
                              models.EmailMessage.direction == "out",
                              models.EmailMessage.created_at >= today,
                              models.EmailMessage.is_spam.is_(False)).scalar() or 0)
        recv_today = (db.query(func.count(models.EmailMessage.id))
                      .filter(models.EmailMessage.agent_id == a.id,
                              models.EmailMessage.direction == "in",
                              models.EmailMessage.created_at >= today,
                              models.EmailMessage.is_spam.is_(False)).scalar() or 0)
        sent_1h = (db.query(func.count(models.EmailMessage.id))
                   .filter(models.EmailMessage.agent_id == a.id,
                           models.EmailMessage.direction == "out",
                           models.EmailMessage.created_at >= hour_ago,
                           models.EmailMessage.is_spam.is_(False)).scalar() or 0)
        agent_rows.append({
            "agent_id": a.id, "name": a.name, "role": a.role or "",
            "is_active": a.is_active,
            "sent_today": sent_today, "recv_today": recv_today, "sent_last_1h": sent_1h,
            "daily_limit": a.daily_send_limit or 150,
        })

    # Recent outbound (paginated)
    out_q = (db.query(models.EmailMessage)
               .filter(models.EmailMessage.direction == "out",
                       models.EmailMessage.is_spam.is_(False))
               .order_by(models.EmailMessage.created_at.desc()))
    out_total = out_q.with_entities(func.count(models.EmailMessage.id)).scalar() or 0
    out_rows = out_q.offset((page - 1) * per_page).limit(per_page).all()

    # Recent inbound (paginated)
    in_q = (db.query(models.EmailMessage)
              .filter(models.EmailMessage.direction == "in",
                      models.EmailMessage.is_spam.is_(False))
              .order_by(models.EmailMessage.created_at.desc()))
    in_total = in_q.with_entities(func.count(models.EmailMessage.id)).scalar() or 0
    in_rows = in_q.offset((page - 1) * per_page).limit(per_page).all()

    # Bounces / failed
    bounce_q = (db.query(models.EmailMessage)
                  .filter(models.EmailMessage.is_spam.is_(True),
                          models.EmailMessage.spam_reason.ilike("%bounce%"))
                  .order_by(models.EmailMessage.created_at.desc()))
    bounce_total = bounce_q.with_entities(func.count(models.EmailMessage.id)).scalar() or 0
    bounce_rows = bounce_q.limit(per_page).all()

    lead_ids = {r.lead_id for r in out_rows + in_rows + bounce_rows if r.lead_id}
    leads_map = {l.id: l for l in db.query(models.Lead).filter(models.Lead.id.in_(lead_ids)).all()} if lead_ids else {}

    def _ser(r):
        lead = leads_map.get(r.lead_id)
        return {"id": r.id, "direction": r.direction,
                "subject": (r.subject or "")[:120],
                "from_addr": r.from_addr or "",
                "lead_email": lead.email if lead else "",
                "created_at": r.created_at.isoformat() if r.created_at else ""}

    return {
        "page": page, "per_page": per_page,
        "agents": agent_rows,
        "outbound": {"total": out_total, "items": [_ser(r) for r in out_rows],
                     "pages": max(1, (out_total + per_page - 1) // per_page)},
        "inbound": {"total": in_total, "items": [_ser(r) for r in in_rows],
                    "pages": max(1, (in_total + per_page - 1) // per_page)},
        "bounced": {"total": bounce_total, "items": [_ser(r) for r in bounce_rows]},
        "paused_agents": [a["name"] for a in agent_rows if not a["is_active"]],
    }