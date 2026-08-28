"""Audit logging — call log() from any endpoint that changes something
sensitive. Failures here NEVER break the calling request (best-effort,
wrapped in try/except) — an audit-log write failing shouldn't stop a real
user action from succeeding."""
from sqlalchemy.orm import Session

from . import models


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