"""System health probe for the Super Admin monitoring card.

The background side of this app (Celery Beat firing a task, the worker
executing it, the inbox actually being polled) is invisible in a normal UI —
so every beat cycle drops a heartbeat row into settings_kv and this module
reads it back. A green row here means "something really ran a moment ago",
not "the config says it should run".

Checks, and why each one exists:
- db / redis        the two things every other feature silently depends on
- beat               heartbeat written when poll_inbox is *scheduled* (120s)
- worker / inbox     heartbeat written when that cycle *finishes*, with the
                     mailbox + message counts so a cycle that ran but did
                     nothing is still distinguishable from one that never ran
- litellm            the LLM gateway; "skipped" when OPENAI_BASE_URL is blank
                     (direct-to-OpenAI mode) so the card never lies about it
"""
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from .. import models
from ..config import settings

# poll-inbox-every-2-min in celery_app.py
BEAT_INTERVAL = 120.0
FRESH_S = 300.0     # <= 5 min  -> ok
STALE_S = 1800.0    # <= 30 min -> warn, beyond that -> down


def heartbeat(db: Session, name: str, detail: str = "") -> None:
    """Record that a background cycle reached this point.

    Never raises: a health write must not be able to fail the task that is
    reporting health."""
    try:
        now = datetime.utcnow().isoformat(timespec="seconds")
        payload = f"{now}|{detail}"[:490]
        row = db.get(models.SettingKV, f"hb:{name}")
        if row is None:
            db.add(models.SettingKV(key=f"hb:{name}", value=payload))
        else:
            row.value = payload
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _heartbeat_age(db: Session, name: str):
    """(seconds since heartbeat, stored detail) or (None, "")."""
    row = db.get(models.SettingKV, f"hb:{name}")
    if row is None or not row.value:
        return None, ""
    ts, _, detail = row.value.partition("|")
    try:
        when = datetime.fromisoformat(ts)
    except ValueError:
        return None, detail.strip()
    age = (datetime.utcnow() - when).total_seconds()
    return age, detail.strip()


def _freshness(age) -> str:
    if age is None:
        return "down"
    if age <= FRESH_S:
        return "ok"
    if age <= STALE_S:
        return "warn"
    return "down"


def _ago(age) -> str:
    if age is None:
        return "never ran"
    if age < 90:
        return f"{int(age)}s ago"
    if age < 5400:
        return f"{int(age // 60)}m ago"
    return f"{age / 3600:.1f}h ago"


def _check(key, label, status, detail, critical=True):
    return {"key": key, "label": label, "status": status,
            "detail": detail, "critical": critical}


def probe(db: Session) -> dict:
    checks = []

    # --- API: this request itself is the proof -----------------------------
    checks.append(_check("api", "API", "ok", "HTTP 200"))

    # --- Database ----------------------------------------------------------
    try:
        import time as _time
        t0 = _time.perf_counter()
        db.execute(models.SettingKV.__table__.select().limit(1))
        ms = int((_time.perf_counter() - t0) * 1000)
        checks.append(_check("db", "PostgreSQL", "ok", f"connected · {ms}ms"))
    except Exception as exc:
        checks.append(_check("db", "PostgreSQL", "down", str(exc)[:80]))

    # --- Redis (broker + result backend) -----------------------------------
    try:
        import time as _time
        from redis import from_url
        t0 = _time.perf_counter()
        from_url(settings.REDIS_URL, socket_connect_timeout=2).ping()
        ms = int((_time.perf_counter() - t0) * 1000)
        checks.append(_check("redis", "Redis", "ok", f"PONG · {ms}ms"))
    except Exception as exc:
        checks.append(_check("redis", "Redis", "down", str(exc)[:80]))

    # --- Celery Beat -------------------------------------------------------
    age, _ = _heartbeat_age(db, "beat")
    checks.append(_check(
        "beat", "Celery Beat", _freshness(age),
        f"scheduler firing · {_ago(age)}"))

    # --- Celery Worker -----------------------------------------------------
    age, _ = _heartbeat_age(db, "worker")
    checks.append(_check(
        "worker", "Celery Worker", _freshness(age),
        f"executing tasks · {_ago(age)}"))

    # --- Inbox polling -----------------------------------------------------
    age, detail = _heartbeat_age(db, "inbox")
    checks.append(_check(
        "inbox", "Inbox polling", _freshness(age),
        f"{detail or 'no cycles yet'} · {_ago(age)}"))

    # --- LLM gateway -------------------------------------------------------
    base = (settings.OPENAI_BASE_URL or "").strip()
    if not base:
        checks.append(_check("litellm", "LLM gateway", "skipped",
                             "OPENAI_BASE_URL empty → talking to OpenAI direct",
                             critical=False))
    else:
        url = base.rstrip("/") + "/health/liveliness"
        try:
            with httpx.Client(timeout=3.0) as client:
                r = client.get(url)
            status = "ok" if r.status_code == 200 else "down"
            checks.append(_check(
                "litellm", "LLM gateway (LiteLLM)", status,
                f"{url} → {r.status_code}", critical=False))
        except Exception as exc:
            checks.append(_check(
                "litellm", "LLM gateway (LiteLLM)", "warn",
                f"unreachable ({type(exc).__name__}) — falling back to direct "
                f"OpenAI", critical=False))

    critical = [c for c in checks if c["critical"]]
    ok = all(c["status"] == "ok" for c in critical)
    return {
        "ok": ok,
        "checked_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "beat_interval_seconds": int(BEAT_INTERVAL),
        "checks": checks,
    }
