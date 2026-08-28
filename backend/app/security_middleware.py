"""Security middleware: rate limiting + CSRF double-submit-cookie check.

Both are Redis-backed (already running for Celery) so limits are shared
correctly across multiple uvicorn workers, not per-process in-memory counters
that silently reset/miss under load.
"""
import secrets
import time

import redis
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from . import security

_redis = redis.from_url(settings.REDIS_URL, decode_responses=True)

CSRF_COOKIE = "cv_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# path-prefix -> (max requests, window seconds). Auth endpoints get the
# tightest limits since they're the classic brute-force / credential-
# stuffing target; everything else gets a generous general ceiling.
RATE_LIMITS = [
    ("/api/auth/login", 10, 60),
    ("/api/auth/verify-otp", 10, 60),
    ("/api/auth/logout", 20, 60),
    ("/api/", 300, 60),   # general API ceiling — generous, just stops runaway scripts
]


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        limit = next(((p, n, w) for p, n, w in RATE_LIMITS if path.startswith(p)), None)
        if limit and not settings.DEBUG:   # relaxed in dev so local testing isn't throttled
            prefix, max_n, window = limit
            ip = _client_ip(request)
            key = f"rl:{prefix}:{ip}"
            try:
                current = _redis.incr(key)
                if current == 1:
                    _redis.expire(key, window)
                if current > max_n:
                    ttl = _redis.ttl(key)
                    return JSONResponse(
                        status_code=429,
                        content={"detail": f"Too many requests — try again in {max(ttl, 1)}s"},
                        headers={"Retry-After": str(max(ttl, 1))},
                    )
            except redis.RedisError:
                pass   # Redis down -> fail open, don't block the whole app on a cache outage
        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie: login sets a non-httpOnly cv_csrf cookie (JS CAN
    read this one — that's the point, it's not the secret, the session
    cookie is). Every state-changing request must echo it back in the
    X-CSRF-Token header. An attacker's cross-site form/script can make the
    browser SEND the session cookie automatically, but can't READ the CSRF
    cookie to put it in a header (same-origin policy) — so forged requests
    fail this check even though the (httpOnly) session cookie rides along."""

    async def dispatch(self, request: Request, call_next):
        if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
            return await call_next(request)
        if request.url.path.startswith("/api/auth/"):
            return await call_next(request)   # login/logout/verify-otp: no session yet to protect

        session_cookie = request.cookies.get(security.COOKIE_NAME)
        if session_cookie:   # only enforce CSRF for cookie-authenticated requests;
                              # pure Bearer-token API clients are immune to browser CSRF by nature
            csrf_cookie = request.cookies.get(CSRF_COOKIE)
            csrf_header = request.headers.get(CSRF_HEADER)
            if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})
        return await call_next(request)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)