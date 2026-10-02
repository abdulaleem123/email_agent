import logging
from pathlib import Path

from fastapi import FastAPI, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .config import settings
from .security import current_user
from . import models
from .routers import (agents, leads, campaigns, knowledge, auth,
                      inbox, dashboard, garbage, app_settings, superadmin, pitch,
                      mail_records, unsubscribe, escalations)
from .migrate import run_migrations
from .bootstrap import bootstrap
from .security_middleware import RateLimitMiddleware, CSRFMiddleware
from .services import jobs

log = logging.getLogger("chatversio.api")

Base.metadata.create_all(bind=engine,checkfirst=True)
run_migrations()
bootstrap()
# Any import/verify job left mid-flight by a previous process is dead: mark it
# failed so the Leads page never shows a frozen progress bar.
jobs.ensure_bootstrap()

app = FastAPI(title=settings.APP_NAME, docs_url="/docs" if settings.DEBUG else None)


# --- One JSON shape for every failure -------------------------------------
# Before this, an unexpected server error returned FastAPI's plain-text
# "Internal Server Error" body, the browser could not parse it as JSON, and
# the UI showed a blank failure. Now the frontend always gets {detail} and can
# toast something readable — and the log keeps the traceback.
@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    first = (exc.errors() or [{}])[0]
    where = ".".join(str(p) for p in (first.get("loc") or [])[1:]) or "request"
    # Pydantic's own wording ("Input should be a valid integer") is developer
    # language; the browser shows this line to the person clicking Upload.
    msg = first.get("msg", "invalid")
    msg = _VALIDATION_TEXT.get(msg, msg)
    return JSONResponse(status_code=422,
                        content={"detail": f"{where}: {msg}",
                                 "errors": [str(e.get("msg", "")) for e in (exc.errors() or [])[:5]]})


_VALIDATION_TEXT = {
    "Input should be a valid integer": "must be a whole number",
    "Input should be a valid number": "must be a number",
    "Input should be a valid string": "must be text",
    "Input should be a valid boolean": "must be yes or no",
    "Field required": "is missing",
}


def _friendly_500(exc: Exception) -> str:
    """One sentence telling the operator what to DO. The class name, the
    message and the full traceback stay in the log — none of them help the
    person whose upload or enroll just failed."""
    text = str(exc).lower()
    if "too many" in text and "parameter" in text:
        return "That selection was too large for one request — try it in smaller batches."
    if "duplicate key" in text or "unique constraint" in text:
        return "Some of those records already exist — nothing was changed."
    if "could not connect" in text or "connection refused" in text or \
            "connection to server" in text or "timeout" in text or "timed out" in text:
        return "The server is busy or unreachable right now — please try again in a moment."
    if isinstance(exc, MemoryError):
        return "That was too much data to process at once — try a smaller file or selection."
    return ("Something went wrong on our side — please try again. If it keeps "
            "failing, the details are in the server log.")


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": _friendly_500(exc)})

# Allow the configured origin + common local dev origins
# (localhost, 127.0.0.1, and WSL2/LAN IPs like 172.x.x.x / 192.168.x.x)
_extra_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://192.168.0.104:8000",
    "http://192.168.0.104:5173",
]

_allowed_origins = list(dict.fromkeys(
    [settings.FRONTEND_ORIGIN] + _extra_origins
))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"http://(172\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+):\d+",  # WSL2 + LAN
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RateLimitMiddleware)

# auth endpoints are public; everything else needs a valid JWT
app.include_router(auth.router)
app.include_router(unsubscribe.router)
app.include_router(superadmin.router)
PROTECTED = [agents.router, leads.router, campaigns.router, knowledge.router,
             inbox.router, dashboard.router, garbage.router, app_settings.router,
             pitch.router, mail_records.router, escalations.router]
for r in PROTECTED:
    app.include_router(r, dependencies=[Depends(current_user)])


def _redis_ok() -> bool:
    try:
        import redis
        redis.from_url(settings.REDIS_URL).ping()
        return True
    except Exception:
        return False


@app.get("/api/health")
def health():
    return {"ok": True, "app": settings.APP_NAME}


@app.get("/api/status", dependencies=[Depends(current_user)])
def status(db: Session = Depends(get_db)):
    """Capacity panel for the Super Admin / Settings page. The counts are the
    honest signal of how big this install has grown (80k+ leads is normal now),
    and the import jobs show whether a background import is mid-flight."""
    return {
        "ok": True, "app": settings.APP_NAME, "redis": _redis_ok(),
        "agents": db.query(models.Agent).count(),
        "leads": db.query(models.Lead).filter(
            models.Lead.status != models.LeadStatus.garbage).count(),
        "campaigns": db.query(models.Campaign).count(),
        "smtp_configured": bool(settings.SMTP_USER and settings.SMTP_PASSWORD),
        "imap_configured": bool(settings.IMAP_USER and settings.IMAP_PASSWORD),
        "otp_enabled": settings.OTP_ENABLED,
        "dkim_configured": bool(settings.DKIM_DOMAIN and settings.DKIM_PRIVATE_KEY_PATH),
        "capacity": {
            "leads_total": jobs.raw_count("leads"),
            "messages_total": jobs.raw_count("email_messages"),
            "escalations_total": db.query(models.EmailMessage)
                                 .filter(models.EmailMessage.is_escalation.is_(True)).count(),
            "imports_running": db.query(models.ImportJob)
                                .filter(models.ImportJob.status.in_(("queued", "running"))).count(),
            "import_slots": jobs.MAX_CONCURRENT,
        },
        "jobs": jobs.recent_jobs(limit=5),
    }


# --- Optional: serve built frontend (npm run build first) ---
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if settings.SERVE_FRONTEND and _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/")
    def spa_index():
        return HTMLResponse((_FRONTEND_DIST / "index.html").read_text(encoding="utf-8"))

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        if path.startswith("api"):
            return {"detail": "Not found"}
        file = _FRONTEND_DIST / path
        if file.is_file():
            return FileResponse(file)
        return spa_index()