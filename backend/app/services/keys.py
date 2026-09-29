"""Runtime API keys + usage recording.

Keys live in SettingKV (managed live from the Super Admin page) with .env as
fallback — change/update/delete/test without restarting anything. Keys are
ENCRYPTED AT REST with AES-GCM (never stored as plaintext); the encryption key
is derived from JWT_SECRET. If cryptography isn't installed, it degrades to
plaintext with a stored marker so reads still work."""
import base64
import hashlib
import logging
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
# Fallback ONLY — when calls are routed through LiteLLM the exact spend comes
# back in the `x-litellm-response-cost` response header and overrides this.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "omni-moderation-latest": (0.0, 0.0),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
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


# ------------------------------------------------------- LiteLLM gateway
COST_HEADER = "x-litellm-response-cost"


def gateway_url() -> str | None:
    """LiteLLM (or any OpenAI-compatible proxy) base URL, or None for direct.

    Shared by every OpenAI() construction in the app so there is exactly one
    place deciding whether traffic goes through the gateway."""
    return (settings.OPENAI_BASE_URL or "").strip() or None


def cost_from_headers(headers) -> float:
    """Exact spend computed by the LiteLLM proxy for this one call.

    Returns 0.0 when the call went straight to the provider (no header) so
    callers can fall back to the local PRICES table."""
    try:
        raw = headers.get(COST_HEADER)
        return round(float(raw), 6) if raw not in (None, "") else 0.0
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _ns(client, route):
    o = client
    for part in route:
        o = getattr(o, part)
    return o


# Only log the first gateway failure per process — otherwise a dead proxy
# would spam the worker log on every single email.
_gateway_warned = False


def costed_call(client, route, **kwargs):
    """Run an OpenAI-SDK operation and also capture LiteLLM's spend figure.

    client  — the OpenAI() instance
    route   — e.g. ("chat", "completions"), ("embeddings",), ("moderations",)

    Returns (parsed_response, cost_usd). Uses `.with_raw_response` so the
    response headers (x-litellm-response-cost) survive; cost falls back to the
    local PRICES table when there is no header.

    When a gateway is configured the real provider key rides along in the
    request body (`extra_body.api_key`) — LiteLLM consumes Authorization for
    proxy auth and never forwards it — and if the call fails for ANY reason
    it retries the identical call straight at the provider, so a proxy outage
    or bad gateway config can never stop email generation.
    """
    global _gateway_warned
    gate = gateway_url()
    if gate:
        kw = dict(kwargs)
        eb = dict(kw.get("extra_body") or {})
        eb.setdefault("api_key", getattr(client, "api_key", None) or "")
        kw["extra_body"] = eb
        try:
            return _invoke(_ns(client, route), **kw)
        except Exception as exc:
            if not _gateway_warned:
                _gateway_warned = True
                logging.getLogger(__name__).warning(
                    "LLM gateway %s failed (%s: %s) — retrying direct with "
                    "the provider instead.", gate, type(exc).__name__, exc)
        direct_kw = dict(kwargs)                   # drop the proxy-only body key
        if "extra_body" in direct_kw:
            eb = dict(direct_kw["extra_body"] or {})
            eb.pop("api_key", None)
            direct_kw["extra_body"] = eb
        direct = client.__class__(api_key=getattr(client, "api_key", None),
                                  base_url=None)
        return _invoke(_ns(direct, route), **direct_kw)
    return _invoke(_ns(client, route), **kwargs)


def _invoke(ns, **kwargs):
    raw_ns = getattr(ns, "with_raw_response", None)
    if raw_ns is None:                       # very old SDK — no headers available
        return ns.create(**kwargs), 0.0
    raw = raw_ns.create(**kwargs)
    return raw.parse(), cost_from_headers(raw.headers)


def record(db: Session, provider: str, kind: str, model: str = "",
           agent_id: int | None = None, input_tokens: int = 0,
           output_tokens: int = 0, cost_usd: float | None = None):
    # LiteLLM's header value wins; otherwise price it locally.
    spent = float(cost_usd) if cost_usd else cost_of(model, input_tokens, output_tokens)
    db.add(models.ApiUsage(
        provider=provider, kind=kind, model=model, agent_id=agent_id,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=round(spent, 6),
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