"""Settings page: runtime toggles with realtime effect (stored in DB KV)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..config import settings as env
from .. import models

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS = {
    "auto_reply_enabled": "true",
    "moderation_enabled": str(env.OPENAI_MODERATION).lower(),
    "mx_verify_enabled": str(env.MX_VERIFY_BEFORE_SEND).lower(),
    "garbage_auto_purge": "true",
    "garbage_retention_days": str(env.GARBAGE_RETENTION_DAYS),
    "outbound_delay_min": str(env.OUTBOUND_DELAY_MIN_SECONDS),
    "outbound_delay_max": str(env.OUTBOUND_DELAY_MAX_SECONDS),
    "inbound_reply_delay": str(env.INBOUND_REPLY_DELAY_SECONDS),
    "followup_after_hours": str(env.FOLLOWUP_AFTER_HOURS),
    "max_followups": str(env.MAX_FOLLOWUPS),
}




@router.get("")
def get_settings(db: Session = Depends(get_db)):
    stored = {s.key: s.value for s in db.query(models.SettingKV).all()}
    return {**DEFAULTS, **stored}


@router.put("")
def put_settings(data: dict, db: Session = Depends(get_db)):
    # Accept flat body from frontend {key: value} OR nested {values: {...}}
    payload = data.get("values") if isinstance(data.get("values"), dict) else data
    for k, v in payload.items():
        if k not in DEFAULTS:
            continue
        row = db.get(models.SettingKV, k)
        if row:
            row.value = str(v)[:500]
        else:
            db.add(models.SettingKV(key=k, value=str(v)[:500]))
    db.commit()
    stored = {s.key: s.value for s in db.query(models.SettingKV).all()}
    return {**DEFAULTS, **stored}



def get_runtime_setting(db, key: str, default=None):
    """Settings page value (DB) wins over .env DEFAULTS."""
    row = db.get(models.SettingKV, key)
    if row is not None and row.value not in (None, ""):
        return row.value
    return DEFAULTS.get(key, default)
