# """JWT auth + email OTP. Single admin account (no public registration).
# Brute-force lockout, bcrypt hashing, short-lived tokens."""
# import hashlib
# import secrets
# from datetime import datetime, timedelta

# import jwt
# from fastapi import Depends, Header, HTTPException
# import bcrypt
# from sqlalchemy.orm import Session

# from .config import settings
# from .database import get_db
# from . import models

# MAX_FAILED_LOGINS = 5
# LOCKOUT_MINUTES = 15


# def hash_password(p: str) -> str:
#     # bcrypt has a 72-byte input limit; encode + truncate defensively
#     return bcrypt.hashpw(p.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


# def verify_password(p: str, h: str) -> bool:
#     try:
#         return bcrypt.checkpw(p.encode("utf-8")[:72], h.encode("utf-8"))
#     except Exception:
#         return False


# def make_token(user: models.User) -> str:
#     payload = {
#         "sub": str(user.id),
#         "email": user.email,
#         "exp": datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRE_HOURS),
#         "iat": datetime.utcnow(),
#     }
#     return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


# def current_user(authorization: str = Header(default=""),
#                  db: Session = Depends(get_db)) -> models.User:
#     if not authorization.startswith("Bearer "):
#         raise HTTPException(401, "Missing bearer token")
#     token = authorization.split(" ", 1)[1]
#     try:
#         payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
#     except jwt.ExpiredSignatureError:
#         raise HTTPException(401, "Session expired — sign in again")
#     except Exception:
#         raise HTTPException(401, "Invalid token")
#     user = db.get(models.User, int(payload["sub"]))
#     if not user:
#         raise HTTPException(401, "User not found")
#     return user


# # ------------------------------------------------------------------ OTP
# def new_otp(db: Session, user: models.User) -> str:
#     """Creates a 6-digit OTP, stores its hash, returns the plain code (to email)."""
#     code = f"{secrets.randbelow(1000000):06d}"
#     db.query(models.OtpCode).filter(models.OtpCode.user_id == user.id,
#                                     models.OtpCode.used.is_(False)).delete()
#     db.add(models.OtpCode(
#         user_id=user.id,
#         code_hash=hashlib.sha256(code.encode()).hexdigest(),
#         expires_at=datetime.utcnow() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)))
#     db.commit()
#     return code


# def check_otp(db: Session, user: models.User, code: str) -> bool:
#     rec = (db.query(models.OtpCode)
#            .filter(models.OtpCode.user_id == user.id, models.OtpCode.used.is_(False))
#            .order_by(models.OtpCode.created_at.desc()).first())
#     if not rec or rec.expires_at < datetime.utcnow() or rec.attempts >= 5:
#         return False
#     rec.attempts += 1
#     ok = rec.code_hash == hashlib.sha256(code.strip().encode()).hexdigest()
#     if ok:
#         rec.used = True
#     db.commit()
#     return ok


# def register_login_failure(db: Session, user: models.User):
#     user.failed_logins = (user.failed_logins or 0) + 1
#     if user.failed_logins >= MAX_FAILED_LOGINS:
#         user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
#         user.failed_logins = 0
#     db.commit()


# def is_locked(user: models.User) -> bool:
#     return bool(user.locked_until and user.locked_until > datetime.utcnow())


# def current_superadmin(user: "models.User" = Depends(current_user)) -> "models.User":
#     """Guards the Super Admin area (AI usage + API-key management ONLY)."""
#     if not getattr(user, "is_superadmin", False):
#         raise HTTPException(403, "Super Admin access required")
#     return user



"""JWT auth + email OTP. Single admin account (no public registration).
Brute-force lockout, bcrypt hashing, short-lived tokens."""
import calendar
import hashlib
import secrets
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException, Cookie
import bcrypt
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from . import models

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
COOKIE_NAME = "cv_session"


# ---------------------------------------------------------------- session life
def idle_delta() -> timedelta:
    """How long a session may sit untouched before it expires."""
    return timedelta(minutes=max(1, int(settings.SESSION_IDLE_MINUTES)))


def absolute_delta() -> timedelta:
    """Hard cap on ONE login, activity or not."""
    return timedelta(hours=max(1, int(settings.JWT_EXPIRE_HOURS)))


def idle_seconds() -> int:
    return int(idle_delta().total_seconds())


def _ts(dt: datetime) -> int:
    """Naive-UTC datetime -> unix seconds, exactly how PyJWT serialises its
    own claims, so `abs` is on the same clock as `exp`."""
    return calendar.timegm(dt.utctimetuple())


def hash_password(p: str) -> str:
    # bcrypt has a 72-byte input limit; encode + truncate defensively
    return bcrypt.hashpw(p.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode("utf-8")[:72], h.encode("utf-8"))
    except Exception:
        return False


def make_token(user: models.User, abs_at: datetime | None = None) -> str:
    """One token, two clocks.

    exp — the IDLE window (SESSION_IDLE_MINUTES). The SPA slides it forward by
        calling POST /api/auth/refresh while the user is actually working, so a
        live session never interrupts anyone; stop working for an hour and the
        token dies on its own.
    abs — the ABSOLUTE deadline of this login (JWT_EXPIRE_HOURS from sign-in).
        Refreshing copies it into the new token untouched, so one login can
        never outlive its cap no matter how active the user is.

    A token issued before `abs` existed simply falls back to its own `exp`,
    which was the old 12-hour clock — still valid, still expires."""
    now = datetime.utcnow()
    if abs_at is None:
        abs_at = now + absolute_delta()
    exp_at = min(now + idle_delta(), abs_at)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "nbf": now,
        "exp": exp_at,
        "abs": _ts(abs_at),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def pick_token(authorization: str = "", cv_session: str = "") -> str:
    """Bearer first — the SPA always holds the freshest token in
    localStorage, and a browser cookie can lag one refresh behind it. The
    cookie is the fallback for clients that authenticate with it alone."""
    if authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1]
    return cv_session or ""


def decode_token(token: str) -> dict:
    """Verify signature + BOTH clocks. Raises 401 with a message that is safe
    to show the user verbatim."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired — sign in again")
    except Exception:
        raise HTTPException(401, "Invalid token")
    abs_ts = payload.get("abs")
    if isinstance(abs_ts, (int, float)) and _ts(datetime.utcnow()) >= abs_ts:
        raise HTTPException(401, "Session expired — sign in again")
    return payload


def abs_deadline(payload: dict) -> datetime | None:
    """The absolute deadline carried by a token, if it has one."""
    abs_ts = payload.get("abs")
    if isinstance(abs_ts, (int, float)) and abs_ts > 0:
        return datetime.utcfromtimestamp(abs_ts)
    return None


def current_user(authorization: str = Header(default=""),
                 cv_session: str = Cookie(default=""),
                 db: Session = Depends(get_db)) -> models.User:
    """Accepts EITHER the Bearer header (what the SPA sends) OR the httpOnly
    session cookie. Both carry the same token, both are checked against the
    idle clock and the absolute deadline in `decode_token`."""
    token = pick_token(authorization, cv_session)
    if not token:
        raise HTTPException(401, "Not signed in")
    payload = decode_token(token)
    user = db.get(models.User, int(payload["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    return user


# ------------------------------------------------------------------ OTP
def new_otp(db: Session, user: models.User) -> str:
    """Creates a 6-digit OTP, stores its hash, returns the plain code (to email)."""
    code = f"{secrets.randbelow(1000000):06d}"
    db.query(models.OtpCode).filter(models.OtpCode.user_id == user.id,
                                    models.OtpCode.used.is_(False)).delete()
    db.add(models.OtpCode(
        user_id=user.id,
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        expires_at=datetime.utcnow() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)))
    db.commit()
    return code


def check_otp(db: Session, user: models.User, code: str) -> bool:
    rec = (db.query(models.OtpCode)
           .filter(models.OtpCode.user_id == user.id, models.OtpCode.used.is_(False))
           .order_by(models.OtpCode.created_at.desc()).first())
    if not rec or rec.expires_at < datetime.utcnow() or rec.attempts >= 5:
        return False
    rec.attempts += 1
    ok = rec.code_hash == hashlib.sha256(code.strip().encode()).hexdigest()
    if ok:
        rec.used = True
    db.commit()
    return ok


def register_login_failure(db: Session, user: models.User):
    user.failed_logins = (user.failed_logins or 0) + 1
    if user.failed_logins >= MAX_FAILED_LOGINS:
        user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
        user.failed_logins = 0
    db.commit()


def is_locked(user: models.User) -> bool:
    return bool(user.locked_until and user.locked_until > datetime.utcnow())


def current_superadmin(user: "models.User" = Depends(current_user)) -> "models.User":
    """Guards the Super Admin area (AI usage + API-key management ONLY)."""
    if not getattr(user, "is_superadmin", False):
        raise HTTPException(403, "Super Admin access required")
    return user
