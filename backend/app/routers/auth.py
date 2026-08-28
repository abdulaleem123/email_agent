# # """Login (email+password) -> email OTP -> JWT. No registration endpoint."""
# # from fastapi import APIRouter, Depends, HTTPException
# # from pydantic import BaseModel, EmailStr, Field
# # from sqlalchemy.orm import Session

# # from ..config import settings
# # from ..database import get_db
# # from .. import models, security
# # from ..services import mailer

# # router = APIRouter(prefix="/api/auth", tags=["auth"])


# # class LoginIn(BaseModel):
# #     email: EmailStr
# #     password: str = Field(min_length=1, max_length=200)


# # class OtpIn(BaseModel):
# #     email: EmailStr
# #     code: str = Field(min_length=4, max_length=10)


# # @router.post("/login")
# # def login(data: LoginIn, db: Session = Depends(get_db)):
# #     user = db.query(models.User).filter(models.User.email == data.email.lower()).first()
# #     if not user:
# #         raise HTTPException(401, "Invalid email or password")
# #     if security.is_locked(user):
# #         raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
# #     if not security.verify_password(data.password, user.password_hash):
# #         security.register_login_failure(db, user)
# #         raise HTTPException(401, "Invalid email or password")
# #     user.failed_logins = 0
# #     db.commit()

# #     if not settings.OTP_ENABLED:
# #         return {"token": security.make_token(user), "otp_required": False}

# #     code = security.new_otp(db, user)
# #     try:
# #         mailer.send_system_email(
# #             user.email, "Your Chatversio AI verification code",
# #             f"Your one-time verification code is: {code}\n\n"
# #             f"It expires in {settings.OTP_EXPIRE_MINUTES} minutes. "
# #             "If you didn't try to sign in, you can ignore this email.")
# #     except Exception:
# #         raise HTTPException(502, "Could not send the OTP email — check SMTP settings.")
# #     return {"otp_required": True, "message": "OTP sent to your email"}


# # @router.post("/verify-otp")
# # def verify_otp(data: OtpIn, db: Session = Depends(get_db)):
# #     user = db.query(models.User).filter(models.User.email == data.email.lower()).first()
# #     if not user or not security.check_otp(db, user, data.code):
# #         raise HTTPException(401, "Invalid or expired code")
# #     return {"token": security.make_token(user)}


# # @router.get("/me")
# # def me(user: models.User = Depends(security.current_user)):
# #     return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


# """Login (email+password) -> email OTP -> JWT. No registration endpoint."""
# from fastapi import APIRouter, Depends, HTTPException
# from pydantic import BaseModel, EmailStr, Field
# from sqlalchemy.orm import Session

# from ..config import settings
# from ..database import get_db
# from .. import models, security
# from ..services import mailer

# router = APIRouter(prefix="/api/auth", tags=["auth"])


# class LoginIn(BaseModel):
#     email: EmailStr
#     password: str = Field(min_length=1, max_length=200)


# class OtpIn(BaseModel):
#     email: EmailStr
#     code: str = Field(min_length=4, max_length=10)


# @router.post("/login")
# def login(data: LoginIn, db: Session = Depends(get_db)):
#     user = db.query(models.User).filter(models.User.email == data.email.lower()).first()
#     if not user:
#         raise HTTPException(401, "Invalid email or password")
#     if security.is_locked(user):
#         raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
#     if not security.verify_password(data.password, user.password_hash):
#         security.register_login_failure(db, user)
#         raise HTTPException(401, "Invalid email or password")
#     user.failed_logins = 0
#     db.commit()

#     if not settings.OTP_ENABLED:
#         return {"token": security.make_token(user), "otp_required": False}

#     code = security.new_otp(db, user)
#     try:
#         mailer.send_system_email(
#             user.email, "Your Chatversio AI verification code",
#             f"Your one-time verification code is: {code}\n\n"
#             f"It expires in {settings.OTP_EXPIRE_MINUTES} minutes. "
#             "If you didn't try to sign in, you can ignore this email.")
#     except Exception:
#         raise HTTPException(502, "Could not send the OTP email — check SMTP settings.")
#     return {"otp_required": True, "message": "OTP sent to your email"}


# @router.post("/verify-otp")
# def verify_otp(data: OtpIn, db: Session = Depends(get_db)):
#     user = db.query(models.User).filter(models.User.email == data.email.lower()).first()
#     if not user or not security.check_otp(db, user, data.code):
#         raise HTTPException(401, "Invalid or expired code")
#     return {"token": security.make_token(user)}


# @router.get("/me")
# def me(user: models.User = Depends(security.current_user)):
#     return {"id": user.id, "email": user.email, "is_admin": user.is_admin,
#             "is_superadmin": bool(getattr(user, "is_superadmin", False))}


"""Login (email+password) -> email OTP -> JWT. No registration endpoint.

Auth is dual-mode: the JWT is returned in the response body (existing
sessionStorage + Bearer-header flow keeps working unchanged) AND set as an
httpOnly cookie in the same response. The cookie can't be read by JS, so it's
immune to XSS token theft; SameSite=Lax blocks it from being sent on
cross-site requests, which is the standard CSRF mitigation for cookie auth
combined with fetch (not a plain HTML form)."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from .. import models, security
from ..services import mailer

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str):
    response.set_cookie(
        key=security.COOKIE_NAME, value=token,
        httponly=True, samesite="lax",
        secure=not settings.DEBUG,          # HTTPS-only in production; allowed over http on localhost in dev
        max_age=settings.JWT_EXPIRE_HOURS * 3600,
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


@router.post("/logout")
def logout(response: Response):
    """Clears the httpOnly session cookie. The frontend should also drop its
    own sessionStorage token — this only clears the server-set cookie."""
    response.delete_cookie(key=security.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: models.User = Depends(security.current_user)):
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin,
            "is_superadmin": bool(getattr(user, "is_superadmin", False))}
