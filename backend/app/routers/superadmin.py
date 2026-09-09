"""Super Admin area — AI USAGE + API KEYS only, nothing else.

- Real-time OpenAI usage: input/output tokens, cost (USD), per agent,
  per model, per kind (chat / embedding / moderation / search), with time windows.
- API keys managed live (stored in SettingKV, .env as fallback): view (masked),
  update, delete, and TEST — no server restart needed.
- Web research uses DuckDuckGo (free, no key needed).
"""
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..security import current_superadmin
from .. import models, audit
from ..services import keys as keysvc

router = APIRouter(prefix="/api/superadmin", tags=["superadmin"],
                   dependencies=[Depends(current_superadmin)])

WINDOWS = {"1d": 1, "7d": 7, "15d": 15, "30d": 30, "all": None}


# --------------------------------------------------------------- usage
def _since(window: str):
    days = WINDOWS.get(window, 30)
    return (datetime.utcnow() - timedelta(days=days)) if days else None


@router.get("/usage")
def usage(window: str = "30d", db: Session = Depends(get_db)):
    since = _since(window)
    q = db.query(models.ApiUsage)
    if since:
        q = q.filter(models.ApiUsage.created_at >= since)

    rows = q.all()
    def agg(items):
        return {
            "calls": len(items),
            "input_tokens": sum(r.input_tokens for r in items),
            "output_tokens": sum(r.output_tokens for r in items),
            "cost_usd": round(sum(r.cost_usd for r in items), 4),
        }

    openai_rows = [r for r in rows if r.provider == "openai"]

    # per model
    models_map = {}
    for r in openai_rows:
        models_map.setdefault(r.model or "unknown", []).append(r)
    per_model = [{"model": m, **agg(v)} for m, v in sorted(models_map.items())]

    # per agent
    agents = {a.id: a.name for a in db.query(models.Agent).all()}
    agent_map = {}
    for r in rows:
        agent_map.setdefault(r.agent_id, []).append(r)
    per_agent = [{"agent_id": aid, "name": agents.get(aid, "system" if aid is None else f"#{aid}"),
                  **agg(v)} for aid, v in agent_map.items()]
    per_agent.sort(key=lambda x: x["cost_usd"], reverse=True)

    # per kind
    kind_map = {}
    for r in rows:
        kind_map.setdefault(r.kind or "chat", []).append(r)
    per_kind = [{"kind": k, **agg(v)} for k, v in sorted(kind_map.items())]

    return {
        "window": window,
        "openai": {**agg(openai_rows)},
        "total_cost_usd": round(sum(r.cost_usd for r in rows), 4),
        "per_model": per_model,
        "per_agent": per_agent,
        "per_kind": per_kind,
    }


@router.get("/usage/timeseries")
def usage_timeseries(days: int = 15, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.query(func.date(models.ApiUsage.created_at),
                     func.sum(models.ApiUsage.input_tokens),
                     func.sum(models.ApiUsage.output_tokens),
                     func.sum(models.ApiUsage.cost_usd))
            .filter(models.ApiUsage.created_at >= since)
            .group_by(func.date(models.ApiUsage.created_at)).all())
    out = [{"date": str(d), "input_tokens": int(i or 0),
            "output_tokens": int(o or 0), "cost_usd": round(float(c or 0), 4)}
           for d, i, o, c in rows]
    return sorted(out, key=lambda x: x["date"])


# --------------------------------------------------------------- API keys
KEY_DEFS = {
    "openai_api_key": ("OpenAI", settings.OPENAI_API_KEY),
}


def _mask(v: str) -> str:
    if not v:
        return ""
    return (v[:5] + "…" + v[-4:]) if len(v) > 12 else "•••"


@router.get("/keys")
def list_keys(db: Session = Depends(get_db)):
    out = []
    for name, (label, env_val) in KEY_DEFS.items():
        val = keysvc.get_key(db, name, env_val)
        row = db.get(models.SettingKV, name)
        out.append({"name": name, "label": label,
                    "masked": _mask(val), "configured": bool(val),
                    "source": "settings" if (row and row.value) else ("env" if env_val else "none")})
    return out


class KeyIn(BaseModel):
    value: str


@router.put("/keys/{name}")
def set_key(name: str, data: KeyIn, request: Request, db: Session = Depends(get_db),
           user: models.User = Depends(current_superadmin)):
    if name not in KEY_DEFS:
        return {"error": "unknown key"}
    enc = keysvc.encrypt_secret(data.value.strip())
    row = db.get(models.SettingKV, name)
    if row:
        row.value = enc
    else:
        db.add(models.SettingKV(key=name, value=enc))
    # rotation-age tracking (see /secrets-health)
    from datetime import datetime
    marker_key = f"{name}_rotated_at"
    marker = db.get(models.SettingKV, marker_key)
    now_iso = datetime.utcnow().isoformat()
    if marker:
        marker.value = now_iso
    else:
        db.add(models.SettingKV(key=marker_key, value=now_iso))
    db.commit()
    audit.log(db, user, "api_key.set", "settings", name, "value not logged (secret)",
             request.client.host if request.client else "")
    return {"name": name, "configured": bool(data.value.strip()), "masked": _mask(data.value.strip())}


@router.delete("/keys/{name}")
def delete_key(name: str, request: Request, db: Session = Depends(get_db),
               user: models.User = Depends(current_superadmin)):
    row = db.get(models.SettingKV, name)
    if row:
        db.delete(row)
        db.commit()
    audit.log(db, user, "api_key.delete", "settings", name, "",
             request.client.host if request.client else "")
    env_val = KEY_DEFS.get(name, ("", ""))[1]
    return {"name": name, "configured": bool(env_val), "fallback": "env" if env_val else "none"}


@router.post("/keys/{name}/test")
def test_key(name: str, db: Session = Depends(get_db)):
    """Live-test a key without spending real quota where possible."""
    if name == "openai_api_key":
        key = keysvc.openai_key(db)
        if not key:
            return {"ok": False, "detail": "No OpenAI key set"}
        try:
            r = httpx.get("https://api.openai.com/v1/models",
                          headers={"Authorization": f"Bearer {key}"}, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "detail": "OpenAI key valid"}
            return {"ok": False, "detail": f"OpenAI rejected the key ({r.status_code})"}
        except Exception as e:
            return {"ok": False, "detail": f"Could not reach OpenAI: {e}"}
    return {"ok": False, "detail": "unknown key"}


# --------------------------------------------------------------- audit log
@router.get("/audit-log")
def audit_log(page: int = 1, per_page: int = 50, db: Session = Depends(get_db)):
    """Who did what, when — key changes, deletes, login attempts. Paginated."""
    per_page = min(max(per_page, 1), 200)
    q = db.query(models.AuditLog).order_by(models.AuditLog.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total, "page": page, "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
        "items": [{
            "id": r.id, "user_email": r.user_email, "action": r.action,
            "target_type": r.target_type, "target_id": r.target_id,
            "detail": r.detail, "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in items],
    }


# --------------------------------------------------------- secrets rotation
@router.get("/secrets-health")
def secrets_health(db: Session = Depends(get_db)):
    """Flags secrets that haven't been rotated in a while. JWT_SECRET itself
    can't be rotated from here (it's an env var — rotating it invalidates
    every session immediately, so it's a deliberate deploy-time action), but
    we track its configured age and the age of each stored API key so you
    get a clear nudge instead of silently running on year-old secrets."""
    from datetime import datetime
    now = datetime.utcnow()
    warnings = []

    # API keys: warn if unrotated for 90+ days (SettingKV has no updated_at
    # column, so we track rotation timestamps in a companion key).
    for name in KEY_DEFS:
        marker = db.get(models.SettingKV, f"{name}_rotated_at")
        if marker and marker.value:
            try:
                age_days = (now - datetime.fromisoformat(marker.value)).days
                if age_days >= 90:
                    warnings.append({"item": name, "age_days": age_days,
                                     "message": f"{KEY_DEFS[name][0]} key hasn't been rotated in {age_days} days"})
            except ValueError:
                pass

    jwt_marker = db.get(models.SettingKV, "jwt_secret_noted_at")
    jwt_age = None
    if jwt_marker and jwt_marker.value:
        try:
            jwt_age = (now - datetime.fromisoformat(jwt_marker.value)).days
        except ValueError:
            pass
    return {
        "warnings": warnings,
        "jwt_secret_age_days": jwt_age,
        "jwt_secret_note": "JWT_SECRET rotation logs everyone out immediately — "
                           "rotate it in your .env / secret manager directly, "
                           "not from this UI.",
    }


# ------------------------------------------------------------------ backups
@router.get("/backups")
def list_backups():
    from ..services import backup
    return {"backups": backup.list_backups(), "keep": backup.BACKUP_KEEP,
           "runs": "daily, automatically, via Celery beat"}


@router.post("/backups/run-now")
def run_backup_now(request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(current_superadmin)):
    from ..services import backup
    result = backup.run_backup()
    audit.log(db, user, "backup.run_manual", "database", "", str(result),
             request.client.host if request.client else "")
    return result


# ------------------------------------------------------------ SMTP diagnostics
@router.get("/smtp-diagnostic")
def smtp_diagnostic():
    """Self-test: does THIS server allow outbound port 25? If not, SMTP-level
    mailbox verification will mostly return 'unknown' no matter what — a
    hosting/network limitation, not a bug. Run this after every deploy."""
    from ..services import mailer
    return mailer.diagnose_port25()