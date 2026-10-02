"""Login (email+password) -> email OTP -> JWT. No registration endpoint.

Auth is dual-mode: the JWT is returned in the response body (existing
sessionStorage + Bearer-header flow keeps working unchanged) AND set as an
httpOnly cookie in the same response. The cookie can't be read by JS, so it's
immune to XSS token theft; SameSite=Lax blocks it from being sent on
cross-site requests, which is the standard CSRF mitigation for cookie auth
combined with fetch (not a plain HTML form)."""
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from .. import models, security
from ..services import mailer

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str):
    from ..security_middleware import new_csrf_token
    # The cookie lives exactly as long as the IDLE window, not as long as the
    # absolute cap — /refresh re-sets it whenever the session is extended, so
    # the browser never holds a cookie whose token is already dead.
    max_age = security.idle_seconds()
    response.set_cookie(
        key=security.COOKIE_NAME, value=token,
        httponly=True, samesite="lax",
        secure=not settings.DEBUG,
        max_age=max_age,
        path="/",
    )
    # CSRF double-submit: a readable (non-httpOnly) cookie the JS can read and
    # echo back as X-CSRF-Token header. Cross-site scripts cannot read this.
    csrf = new_csrf_token()
    response.set_cookie(
        key="cv_csrf", value=csrf,
        httponly=False, samesite="lax",
        secure=not settings.DEBUG,
        max_age=max_age,
        path="/",
    )


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class OtpIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


@router.post("/login")
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == data.email.lower()).first()
    if not user:
        raise HTTPException(401, "Invalid email or password")
    if security.is_locked(user):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    if not security.verify_password(data.password, user.password_hash):
        security.register_login_failure(db, user)
        raise HTTPException(401, "Invalid email or password")
    user.failed_logins = 0
    db.commit()

    if not settings.OTP_ENABLED:
        token = security.make_token(user)
        _set_session_cookie(response, token)
        return {"token": token, "otp_required": False}

    code = security.new_otp(db, user)
    try:
        mailer.send_system_email(
            user.email, "Your Chatversio AI verification code",
            f"Your one-time verification code is: {code}\n\n"
            f"It expires in {settings.OTP_EXPIRE_MINUTES} minutes. "
            "If you didn't try to sign in, you can ignore this email.")
    except Exception:
        raise HTTPException(502, "Could not send the OTP email — check SMTP settings.")
    return {"otp_required": True, "message": "OTP sent to your email"}


@router.post("/verify-otp")
def verify_otp(data: OtpIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == data.email.lower()).first()
    if not user or not security.check_otp(db, user, data.code):
        raise HTTPException(401, "Invalid or expired code")
    token = security.make_token(user)
    _set_session_cookie(response, token)
    return {"token": token}


@router.post("/refresh")
def refresh_session(response: Response, db: Session = Depends(get_db),
                    authorization: str = Header(default=""),
                    cv_session: str = Cookie(default="")):
    """Slides the IDLE clock forward — nothing else.

    The browser calls this while the user is actually working, so an active
    session never gets logged out under them. The new token carries the
    ORIGINAL absolute deadline, so this can never stretch a login past
    JWT_EXPIRE_HOURS. A token whose idle window already closed, or whose cap
    has passed, is refused with 401 here — that is what puts the user back on
    the login screen with "Session expired"."""
    token = security.pick_token(authorization, cv_session)
    if not token:
        raise HTTPException(401, "Not signed in")
    payload = security.decode_token(token)
    user = db.get(models.User, int(payload["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    deadline = security.abs_deadline(payload)
    new_token = security.make_token(user, abs_at=deadline)
    _set_session_cookie(response, new_token)
    return {"token": new_token,
            "expires_in": security.idle_seconds(),
            "absolute_expires_at": (deadline.isoformat() if deadline else None)}


@router.post("/logout")
def logout(response: Response):
    """Clears the httpOnly session cookie (and the CSRF cookie with it). The
    frontend should also drop its own localStorage token — this only clears
    the server-set cookies."""
    response.delete_cookie(key=security.COOKIE_NAME, path="/")
    response.delete_cookie(key="cv_csrf", path="/")
    return {"ok": True}


@router.get("/me")
def me(user: models.User = Depends(security.current_user)):
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin,
            "is_superadmin": bool(getattr(user, "is_superadmin", False))}
