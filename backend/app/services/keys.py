"""Runtime API keys + usage recording.

Keys live in SettingKV (managed live from the Super Admin page) with .env as
fallback — change/update/delete/test without restarting anything. Keys are
ENCRYPTED AT REST with AES-GCM (never stored as plaintext); the encryption key
is derived from JWT_SECRET. If cryptography isn't installed, it degrades to
plaintext with a stored marker so reads still work."""
import base64
import hashlib
from datetime import datetime
from sqlalchemy.orm import Session
from ..config import settings
from .. import models

_ENC_PREFIX = "gcm:"


def _fernet_key() -> bytes:
    # 32-byte key derived from JWT_SECRET (stable across restarts)
    return hashlib.sha256(("kv-enc::" + settings.JWT_SECRET).encode()).digest()


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        return ""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import os
        nonce = os.urandom(12)
        ct = AESGCM(_fernet_key()).encrypt(nonce, plaintext.encode(), None)
        return _ENC_PREFIX + base64.b64encode(nonce + ct).decode()
    except Exception:
        return plaintext        # cryptography missing -> plaintext fallback


def decrypt_secret(stored: str) -> str:
    if not stored:
        return ""
    if not stored.startswith(_ENC_PREFIX):
        return stored           # legacy plaintext
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        raw = base64.b64decode(stored[len(_ENC_PREFIX):])
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(_fernet_key()).decrypt(nonce, ct, None).decode()
    except Exception:
        return ""

# $ per 1M tokens (input, output)
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}


def get_key(db: Session, name: str, env_value: str) -> str:
    row = db.get(models.SettingKV, name)
    if row and row.value:
        return decrypt_secret(row.value)
    return env_value or ""


def openai_key(db: Session) -> str:
    return get_key(db, "openai_api_key", settings.OPENAI_API_KEY)



def cost_of(model: str, in_tok: int, out_tok: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return round((in_tok * pin + out_tok * pout) / 1_000_000, 6)


def record(db: Session, provider: str, kind: str, model: str = "",
           agent_id: int | None = None, input_tokens: int = 0,
           output_tokens: int = 0):
    db.add(models.ApiUsage(
        provider=provider, kind=kind, model=model, agent_id=agent_id,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=cost_of(model, input_tokens, output_tokens),
        created_at=datetime.utcnow()))
    db.commit()
    # Proactive credit notifications so the team sees it in the bell BEFORE
    # outbound auto-pauses. Deduped via SettingKV flags; the flags reset
    # automatically whenever usage drops back under a threshold (quota raised
    # or ApiUsage cleared for the new billing cycle).
    try:
        if provider == "openai":
            _maybe_notify_openai(db, agent_id)
    except Exception:
        pass   # notifications must never break a real API call


def _flag(db: Session, key: str) -> bool:
    row = db.get(models.SettingKV, key)
    return bool(row and row.value == "1")


def _set_flag(db: Session, key: str, on: bool):
    row = db.get(models.SettingKV, key)
    if row:
        row.value = "1" if on else "0"
    else:
        db.add(models.SettingKV(key=key, value="1" if on else "0"))
    db.commit()


def _push_notification(db: Session, kind: str, title: str, body: str = "",
                       agent_id: int | None = None):
    db.add(models.Notification(kind=kind, title=title[:300], body=body[:2000],
                               agent_id=agent_id))
    db.commit()



def _maybe_notify_openai(db: Session, agent_id: int | None):
    """OpenAI has no fixed quota here, so we notify on SPEND milestones — each
    crossed $5 of cumulative cost fires one info notification, deduped so it
    only fires once per threshold."""
    from sqlalchemy import func
    total = (db.query(func.coalesce(func.sum(models.ApiUsage.cost_usd), 0.0))
             .filter(models.ApiUsage.provider == "openai").scalar() or 0.0)
    step = 5.0
    milestone = int(total // step) * int(step)
    if milestone <= 0:
        return
    key = "openai_spend_notified"
    row = db.get(models.SettingKV, key)
    last = float(row.value) if (row and row.value) else 0.0
    if milestone > last:
        _push_notification(db, "info", f"OpenAI spend crossed ${milestone}",
                           f"Cumulative OpenAI cost is now ${total:.2f}. "
                           "See the breakdown in Super Admin → Usage.", agent_id)
        if row:
            row.value = str(milestone)
        else:
            db.add(models.SettingKV(key=key, value=str(milestone)))
        db.commit()