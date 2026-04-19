"""WeChat Mini Program authentication routes.

Three endpoints support the three scenarios a mini program user can be in:

- POST /auth/wechat/login — exchanges a Tencent js_code for either a JWT
  (returning user) or a short-lived setup ticket (first time on this device).
- POST /auth/wechat/link-with-password — binds the WeChat openid from a
  setup ticket to an existing Trainsight account after password verification.
- POST /auth/wechat/register — creates a new account bound to the WeChat
  openid, enforcing the same invitation-code rules as web registration.

The setup ticket is a short-lived HS256 JWT (audience
"trainsight:wechat-setup") that carries the verified openid. It exists
because Tencent's jscode2session codes are single-use, so the second leg
of the onboarding flow can't re-exchange the original code.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta

import httpx
import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi_users.password import PasswordHelper
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from api.invitations import (
    consume_invitation,
    find_valid_invitation,
    is_admin_email,
)
from api.users import SECRET
from db.models import User
from db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/wechat", tags=["auth"])

TENCENT_JSCODE_URL = "https://api.weixin.qq.com/sns/jscode2session"

ACCESS_TOKEN_AUDIENCE = "fastapi-users:auth"
ACCESS_TOKEN_LIFETIME_SECS = int(
    os.environ.get("TRAINSIGHT_JWT_LIFETIME_SECS", str(7 * 24 * 3600))
)

SETUP_TICKET_AUDIENCE = "trainsight:wechat-setup"
SETUP_TICKET_LIFETIME_SECS = 600  # 10 minutes

_password_helper = PasswordHelper()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class WeChatLoginRequest(BaseModel):
    js_code: str = Field(..., min_length=1)


class WeChatLoginResponse(BaseModel):
    status: str  # "ok" | "needs_setup"
    access_token: str | None = None
    wechat_login_ticket: str | None = None


class WeChatLinkRequest(BaseModel):
    wechat_login_ticket: str = Field(..., min_length=1)
    email: EmailStr
    password: str = Field(..., min_length=1)


class WeChatRegisterRequest(BaseModel):
    wechat_login_ticket: str = Field(..., min_length=1)
    invitation_code: str = ""
    email: EmailStr | None = None
    password: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None


class WeChatAuthResponse(BaseModel):
    access_token: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _issue_access_token(user_id: str) -> str:
    """Issue a JWT matching the format accepted by api/auth.py:get_current_user_id."""
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "aud": ACCESS_TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=ACCESS_TOKEN_LIFETIME_SECS),
    }
    return pyjwt.encode(payload, SECRET, algorithm="HS256")


def _mint_setup_ticket(openid: str, unionid: str | None) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": openid,
        "unionid": unionid,
        "aud": SETUP_TICKET_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=SETUP_TICKET_LIFETIME_SECS),
    }
    return pyjwt.encode(payload, SECRET, algorithm="HS256")


def _verify_setup_ticket(ticket: str) -> tuple[str, str | None]:
    """Decode a setup ticket. Returns (openid, unionid)."""
    try:
        payload = pyjwt.decode(
            ticket,
            SECRET,
            algorithms=["HS256"],
            audience=SETUP_TICKET_AUDIENCE,
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(400, "WECHAT_TICKET_EXPIRED")
    except pyjwt.InvalidTokenError:
        raise HTTPException(400, "WECHAT_TICKET_INVALID")
    openid = payload.get("sub")
    if not openid:
        raise HTTPException(400, "WECHAT_TICKET_MALFORMED")
    return openid, payload.get("unionid")


async def _jscode2session(js_code: str) -> dict:
    """Exchange a mini-program js_code for an openid via Tencent.

    Returns {openid, unionid (optional), session_key}. Raises HTTPException
    on configuration or upstream errors. Kept async because this is called
    from FastAPI async handlers; httpx.AsyncClient is the natural fit.

    Note on secret handling: Tencent's jscode2session API only accepts
    credentials as query-string parameters, so `secret` ends up on the
    request URL. We silence httpx's INFO logger for the duration of
    this call to keep the secret out of structured logs (Azure App
    Insights, local `uvicorn` terminal, etc.). Transport errors still
    log at WARNING, without the URL.
    """
    appid = os.environ.get("WECHAT_MINIAPP_APPID", "")
    secret = os.environ.get("WECHAT_MINIAPP_SECRET", "")
    if not appid or not secret:
        raise HTTPException(503, "WECHAT_NOT_CONFIGURED")

    params = {
        "appid": appid,
        "secret": secret,
        "js_code": js_code,
        "grant_type": "authorization_code",
    }
    httpx_logger = logging.getLogger("httpx")
    previous_level = httpx_logger.level
    httpx_logger.setLevel(logging.WARNING)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(TENCENT_JSCODE_URL, params=params)
            except httpx.HTTPError as exc:
                logger.warning("jscode2session transport error: %s", type(exc).__name__)
                raise HTTPException(502, "WECHAT_UPSTREAM_ERROR")
    finally:
        httpx_logger.setLevel(previous_level)

    try:
        data = resp.json()
    except ValueError:
        logger.warning("jscode2session returned non-JSON: %r", resp.text[:200])
        raise HTTPException(502, "WECHAT_UPSTREAM_ERROR")

    errcode = data.get("errcode", 0)
    if errcode:
        logger.warning("jscode2session errcode=%s errmsg=%s", errcode, data.get("errmsg"))
        raise HTTPException(400, f"WECHAT_CODE_ERROR_{errcode}")

    openid = data.get("openid")
    if not openid:
        logger.warning("jscode2session returned no openid: %r", data)
        raise HTTPException(502, "WECHAT_UPSTREAM_ERROR")

    return {
        "openid": openid,
        "unionid": data.get("unionid"),
        "session_key": data.get("session_key"),
    }


def _synthetic_email(openid: str) -> str:
    """Deterministic placeholder for the email column for WeChat-only users.

    The DB schema keeps `email NOT NULL UNIQUE` for FastAPI-Users
    compatibility. WeChat-only users have no real email; we store a
    deterministic sentinel that: (1) satisfies NOT NULL + UNIQUE, (2)
    cannot collide with any real RFC-5322 address (colon is not valid in
    an email local part without quoting), and (3) is easy to identify in
    the DB. We insert via SQLAlchemy directly so Pydantic's EmailStr
    never validates this value.
    """
    return f"wechat:{openid}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=WeChatLoginResponse)
async def wechat_login(
    body: WeChatLoginRequest,
    db: Session = Depends(get_db),
) -> WeChatLoginResponse:
    """Exchange a Tencent js_code for a JWT or a setup ticket.

    Returning user (openid already bound) → JWT.
    New device / new user (openid unknown) → setup ticket; the mini program
    then directs the user to either link or register.
    """
    session = await _jscode2session(body.js_code)
    openid = session["openid"]
    unionid = session.get("unionid")

    user = db.query(User).filter(User.wechat_openid == openid).first()
    if user and user.is_active:
        return WeChatLoginResponse(
            status="ok",
            access_token=_issue_access_token(user.id),
        )

    return WeChatLoginResponse(
        status="needs_setup",
        wechat_login_ticket=_mint_setup_ticket(openid, unionid),
    )


@router.post("/link-with-password", response_model=WeChatAuthResponse)
def wechat_link_with_password(
    body: WeChatLinkRequest,
    db: Session = Depends(get_db),
) -> WeChatAuthResponse:
    """Bind the WeChat openid from the setup ticket to an existing account.

    The user must prove control of the existing account with email+password.
    This is the primary cross-device linking path for users who already
    registered on the web.
    """
    openid, unionid = _verify_setup_ticket(body.wechat_login_ticket)

    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.is_active:
        raise HTTPException(400, "WECHAT_LINK_INVALID_CREDENTIALS")

    valid, _updated_hash = _password_helper.verify_and_update(
        body.password, user.hashed_password
    )
    if not valid:
        raise HTTPException(400, "WECHAT_LINK_INVALID_CREDENTIALS")

    # Prevent stealing an already-linked account.
    if user.wechat_openid and user.wechat_openid != openid:
        raise HTTPException(409, "WECHAT_LINK_ACCOUNT_ALREADY_LINKED")

    # Prevent one openid from being bound to two different Trainsight users.
    conflict = (
        db.query(User)
        .filter(User.wechat_openid == openid, User.id != user.id)
        .first()
    )
    if conflict:
        raise HTTPException(409, "WECHAT_LINK_OPENID_ALREADY_BOUND")

    user.wechat_openid = openid
    if unionid:
        user.wechat_unionid = unionid
    db.commit()

    return WeChatAuthResponse(access_token=_issue_access_token(user.id))


@router.post("/register", response_model=WeChatAuthResponse)
async def wechat_register(
    body: WeChatRegisterRequest,
    db: Session = Depends(get_db),
) -> WeChatAuthResponse:
    """Create a new account bound to the WeChat openid from the setup ticket.

    Email + password are optional. If omitted, the user is WeChat-only
    (synthetic email, random unusable password) — they can still log in on
    the web later by going through an account-recovery flow.

    Invitation rules match the web register endpoint: first user becomes
    admin, configured admin email bypasses the check, everyone else needs
    a valid invitation code.
    """
    openid, unionid = _verify_setup_ticket(body.wechat_login_ticket)

    # Refuse double-registration: the openid must not be bound yet.
    existing = db.query(User).filter(User.wechat_openid == openid).first()
    if existing:
        raise HTTPException(409, "WECHAT_REGISTER_OPENID_ALREADY_BOUND")

    # Resolve the email/password we'll actually persist. WeChat-only users
    # get a deterministic synthetic email and an unusable random password.
    wants_web_login = bool(body.email and body.password)
    if wants_web_login:
        email_to_use = body.email
        password_to_use = body.password
        # If the email is already taken by a web user, the right flow is
        # link-with-password, not register. Surface that clearly.
        if db.query(User).filter(User.email == email_to_use).first():
            raise HTTPException(400, "REGISTER_USER_ALREADY_EXISTS")
    else:
        email_to_use = _synthetic_email(openid)
        password_to_use = secrets.token_urlsafe(32)

    admin_email_bypass = is_admin_email(email_to_use) if wants_web_login else False

    # Pre-validate invitation (sync); first-user check is atomic inside the async session.
    invitation = None
    if not admin_email_bypass and body.invitation_code:
        invitation = find_valid_invitation(db, body.invitation_code)

    # Direct ORM insert (not via fastapi-users' BaseUserCreate) because that
    # schema uses Pydantic EmailStr which rejects reserved TLDs and the
    # synthetic "wechat:<openid>" form. We still hash the password using
    # the same PasswordHelper fastapi-users uses so web-login-enabled users
    # can authenticate through the standard /api/auth/login path.
    from sqlalchemy import func, select
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as async_session:
        user_count_result = await async_session.execute(
            select(func.count()).select_from(User)
        )
        user_count = user_count_result.scalar() or 0
        is_first_user = user_count == 0
        is_admin = bool(is_first_user or admin_email_bypass)

        if not is_first_user and not admin_email_bypass:
            if not invitation:
                if not body.invitation_code:
                    raise HTTPException(400, detail="REGISTER_INVITATION_REQUIRED")
                raise HTTPException(400, detail="REGISTER_INVALID_INVITATION")

        new_user = User(
            email=email_to_use,
            hashed_password=_password_helper.hash(password_to_use),
            is_active=True,
            is_superuser=is_admin,
            is_verified=True,
            wechat_openid=openid,
            wechat_unionid=unionid,
            wechat_nickname=body.nickname,
            wechat_avatar_url=body.avatar_url,
        )
        async_session.add(new_user)
        try:
            await async_session.flush()
        except Exception as exc:
            await async_session.rollback()
            raise HTTPException(400, detail=str(exc))
        new_user_id = new_user.id
        await async_session.commit()

    if invitation:
        consume_invitation(db, invitation, new_user_id)

    return WeChatAuthResponse(access_token=_issue_access_token(new_user_id))
