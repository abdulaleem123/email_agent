from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .config import settings
from .security import current_user
from . import models
from .routers import (agents, leads, campaigns, knowledge, auth,
                      inbox, dashboard, garbage, app_settings, superadmin, pitch,
                      mail_records, unsubscribe)
from .migrate import run_migrations
from .bootstrap import bootstrap
from .security_middleware import RateLimitMiddleware, CSRFMiddleware

Base.metadata.create_all(bind=engine)
run_migrations()
bootstrap()

app = FastAPI(title=settings.APP_NAME, docs_url="/docs" if settings.DEBUG else None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN, "http://127.0.0.1:5173"],
    allow_credentials=True,   # required so the browser sends/accepts the httpOnly session cookie
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
             pitch.router, mail_records.router]
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