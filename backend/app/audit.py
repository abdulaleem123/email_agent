"""Audit logging — call log() from any endpoint that changes something
sensitive. Failures here NEVER break the calling request (best-effort,
wrapped in try/except) — an audit-log write failing shouldn't stop a real
user action from succeeding.

Retention: an admin-action trail is only useful while somebody is still
thinking about it, and this table gets a row on every sensitive endpoint, so
rows are dropped after RETENTION_HOURS. Keeping it short is what stops the
table (and every `SELECT count(*)` on the Audit logs page) from growing
without bound. Purge runs on three paths so a quiet install still cleans up:
on every log() write, on every Audit logs page read, and hourly from Beat.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models

RETENTION_HOURS = 24


def purge_old(db: Session, hours: int = RETENTION_HOURS) -> int:
    """Delete audit rows older than `hours`. Best-effort: never raises, and
    never rolls back a caller's pending work on failure."""
    try:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        n = (db.query(models.AuditLog)
               .filter(models.AuditLog.created_at < cutoff)
               .delete(synchronize_session=False))
        db.commit()
        return int(n or 0)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def log(db: Session, user, action: str, target_type: str = "",
       target_id="", detail: str = "", ip: str = ""):
    try:
        db.add(models.AuditLog(
            user_id=getattr(user, "id", None),
            user_email=getattr(user, "email", "") or "",
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else "",
            detail=detail[:2000],
            ip_address=ip,
        ))
        db.commit()
    except Exception:
        db.rollback()
    # Opportunistic trim: any admin action is a cheap moment to drop expired
    # rows, so the table never outlives its retention even if Beat is down.
    purge_old(db)
