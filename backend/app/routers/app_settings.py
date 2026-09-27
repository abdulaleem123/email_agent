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

    # ── Outbound volume ────────────────────────────────────────────────────
    # The operator sets these once here, not per campaign. Every send path
    # reads them, so changing a value takes effect on the next email.
    "daily_send_limit": str(env.DAILY_SEND_LIMIT),        # 0 = use the agent's own cap
    "email_batch_size": str(env.EMAIL_BATCH_SIZE),         # leads per Batch
    "batch_size_min": str(env.BATCH_SIZE_MIN),
    "batch_size_max": str(env.BATCH_SIZE_MAX),
    "email_poll_size": str(env.EMAIL_POLL_SIZE),          # inbound msgs per poll cycle
    "outbound_delay_min": str(env.OUTBOUND_DELAY_MIN_SECONDS),
    "outbound_delay_max": str(env.OUTBOUND_DELAY_MAX_SECONDS),
    "inbound_reply_delay": str(env.INBOUND_REPLY_DELAY_SECONDS),

    # ── Follow-ups ─────────────────────────────────────────────────────────
    "followup_after_hours": str(env.FOLLOWUP_AFTER_HOURS),  # legacy hour-based fallback
    "max_followups": str(env.MAX_FOLLOWUPS),                # cap when a campaign has no plan
    "followup_max_days": str(env.FOLLOWUP_MAX_DAYS),        # no reply for N days -> close

    # ── Lead ownership ─────────────────────────────────────────────────────
    # A lead stays with its agent while they are communicating; the agent is
    # paused, or this many days pass with NO mail either way, and the lead is
    # released for any other agent to take over.
    "lead_ownership_days": "7",

    # ── Retention ──────────────────────────────────────────────────────────
    "garbage_retention_days": str(env.GARBAGE_RETENTION_DAYS),
    "escalation_retention_days": str(env.ESCALATION_RETENTION_DAYS),
    "not_interested_retention_days": str(env.NOT_INTERESTED_RETENTION_DAYS),
    "stale_lead_days": str(env.STALE_LEAD_DAYS),
}

# Ranges the Settings page enforces so a typo cannot stop the world. Anything
# outside these is clamped on save rather than rejected, so a bad edit is never
# a dead end.
BOUNDS = {
    "daily_send_limit": (0, 100000),        # 0 = no global cap
    "email_batch_size": (10, 2000),
    "batch_size_min": (10, 500),
    "batch_size_max": (10, 2000),
    "email_poll_size": (1, 5000),
    "outbound_delay_min": (5, 86400),
    "outbound_delay_max": (5, 86400),
    "inbound_reply_delay": (0, 86400),
    "followup_after_hours": (1, 8760),
    "max_followups": (0, 20),
    "followup_max_days": (1, 365),
    "lead_ownership_days": (1, 90),
    "garbage_retention_days": (1, 3650),
    "escalation_retention_days": (1, 3650),
    "not_interested_retention_days": (0, 3650),   # 0 = keep forever
    "stale_lead_days": (1, 365),
}

BOOLEANS = {"auto_reply_enabled", "moderation_enabled", "mx_verify_enabled",
            "garbage_auto_purge"}


def _coerce(key: str, value):
    """Clamp a value to BOUNDS. bools become 'true'/'false', numbers become
    ints, anything else is stored as a short string."""
    if key in BOOLEANS:
        raw = value if isinstance(value, bool) else str(value).strip().lower()
        return "true" if raw in (True, "true", "1", "yes", "on") else "false"
    if key in BOUNDS:
        lo, hi = BOUNDS[key]
        try:
            return str(max(lo, min(hi, int(float(value)))))
        except (TypeError, ValueError):
            return DEFAULTS[key]
    return str(value)[:500]


def _int(values: dict, key: str) -> int:
    try:
        return int(float(values.get(key, DEFAULTS[key])))
    except (TypeError, ValueError):
        return int(DEFAULTS[key])


def _normalize_batch_range(values: dict) -> dict:
    """Keep batch_size_min <= email_batch_size <= batch_size_max.

    BOUNDS alone is not enough: it is a wide 10..2000 guard rail, so a save of
    5 used to stick as 10 even with batch_size_min=20. Batches are then built
    at min..max, so the page would show a size the enroller never uses. Resolve
    the range here instead, on both read and write, so what is displayed is
    always what actually happens."""
    lo, hi = _int(values, "batch_size_min"), _int(values, "batch_size_max")
    if lo > hi:
        lo, hi = hi, lo
    size = min(max(_int(values, "email_batch_size"), lo), hi)
    values["batch_size_min"], values["batch_size_max"] = str(lo), str(hi)
    values["email_batch_size"] = str(size)
    return values


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    stored = {s.key: s.value for s in db.query(models.SettingKV).all()}
    values = _normalize_batch_range({**DEFAULTS, **stored})
    return {**values, "bounds": BOUNDS, "booleans": sorted(BOOLEANS)}


@router.put("")
def put_settings(data: dict, db: Session = Depends(get_db)):
    # Accept flat body from frontend {key: value} OR nested {values: {...}}
    payload = data.get("values") if isinstance(data.get("values"), dict) else data
    for k, v in payload.items():
        if k not in DEFAULTS:
            continue
        row = db.get(models.SettingKV, k)
        value = _coerce(k, v)
        if row:
            row.value = value
        else:
            db.add(models.SettingKV(key=k, value=value))
    db.commit()
    stored = {s.key: s.value for s in db.query(models.SettingKV).all()}
    values = _normalize_batch_range({**DEFAULTS, **stored})
    # Persist the resolved size so the stored row matches what is served.
    for k in ("email_batch_size", "batch_size_min", "batch_size_max"):
        row = db.get(models.SettingKV, k)
        if row is None:
            db.add(models.SettingKV(key=k, value=values[k]))
        elif row.value != values[k]:
            row.value = values[k]
    db.commit()
    return {**values, "bounds": BOUNDS, "booleans": sorted(BOOLEANS)}



def get_runtime_setting(db, key: str, default=None):
    """Settings page value (DB) wins over .env DEFAULTS."""
    row = db.get(models.SettingKV, key)
    if row is not None and row.value not in (None, ""):
        return row.value
    return DEFAULTS.get(key, default)


@router.get("/usage")
def sending_usage(db: Session = Depends(get_db)):
    """What the daily limit is actually doing, right now.

    A cap you cannot see is a mystery, so this answers it directly: per agent,
    how many outbound emails have gone out today, what the effective cap is
    (the smaller of the agent's own cap and the global one), how much is left,
    and whether that agent is currently held back by the cap."""
    from datetime import datetime
    from sqlalchemy import func

    from ..tasks import _daily_limit

    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent = dict((aid, n) for aid, n in (
        db.query(models.EmailMessage.agent_id, func.count(models.EmailMessage.id))
        .filter(models.EmailMessage.direction == "out",
                models.EmailMessage.created_at >= start,
                models.EmailMessage.is_spam.is_(False))
        .group_by(models.EmailMessage.agent_id).all()) if aid)

    rows, total_sent, total_cap = [], 0, 0
    for a in db.query(models.Agent).all():
        limit = _daily_limit(db, a)
        n = sent.get(a.id, 0)
        total_sent += n
        total_cap += limit
        rows.append({
            "agent_id": a.id, "name": a.name,
            "sent_today": n, "limit": limit,
            "remaining": max(0, limit - n),
            "capped": n >= limit,
        })
    return {
        "items": rows,
        "sent_today": total_sent,
        "limit_total": total_cap,
        "remaining_total": max(0, total_cap - total_sent),
        "global_daily_send_limit": int(get_runtime_setting(db, "daily_send_limit") or 0),
        "email_batch_size": int(get_runtime_setting(db, "email_batch_size") or 50),
        "email_poll_size": int(get_runtime_setting(db, "email_poll_size") or 100),
    }
