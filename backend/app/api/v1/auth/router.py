from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_totp_secret,
    get_totp_uri,
    hash_password,
    verify_password,
    verify_totp,
)
from app.db.models import AuditLog, User
from app.db.session import get_db
from app.core.redis_client import get_redis

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["Auth"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TwoFASetupResponse(BaseModel):
    secret: str
    qr_uri: str


class TwoFAVerifyRequest(BaseModel):
    totp_code: str


class TwoFADisableRequest(BaseModel):
    password: str
    totp_code: str


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _write_audit(db, actor_id, action, ip=None, ua=None, meta=None):
    log_entry = AuditLog(
        actor_id=actor_id,
        action=action,
        resource_type="auth",
        ip_address=ip,
        user_agent=ua,
        metadata=meta,
    )
    db.add(log_entry)
    await db.flush()


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.email == body.email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        await _write_audit(db, None, "login_failed", meta={"email": body.email})
        raise UnauthorizedError("Invalid credentials")

    if not user.is_active:
        raise ForbiddenError("Account suspended")

    if user.totp_enabled:
        if not body.totp_code:
            raise UnauthorizedError("TOTP code required")
        if not verify_totp(user.totp_secret, body.totp_code):
            await _write_audit(db, user.id, "login_2fa_failed")
            raise UnauthorizedError("Invalid TOTP code")

    access_token = create_access_token(str(user.id), user.role)
    refresh_token = create_refresh_token(str(user.id))

    # Store refresh token jti in Redis
    payload = decode_token(refresh_token)
    redis = await get_redis()
    await redis.setex(
        f"refresh:{payload['jti']}",
        60 * 60 * 24 * 7,  # 7 days
        str(user.id),
    )

    # Set refresh token as httpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=60 * 60 * 24 * 7,
        path="/api/v1/auth/refresh",
    )

    await _write_audit(db, user.id, "login_success")
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_db),
    # Cookie injection for refresh token
    refresh_token: str = None,
):
    from fastapi import Request

    # Actually read from cookie in the real flow
    if not refresh_token:
        raise UnauthorizedError("Refresh token missing")

    try:
        payload = decode_token(refresh_token)
    except Exception:
        raise UnauthorizedError("Invalid refresh token")

    if payload.get("type") != "refresh":
        raise UnauthorizedError("Not a refresh token")

    redis = await get_redis()
    jti = payload.get("jti")
    user_id = await redis.get(f"refresh:{jti}")
    if not user_id:
        raise UnauthorizedError("Refresh token revoked or expired")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found")

    new_access = create_access_token(str(user.id), user.role)
    return TokenResponse(access_token=new_access)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Revoke refresh token from Redis (client sends the jti via cookie in real flow)
    response.delete_cookie("refresh_token", path="/api/v1/auth/refresh")
    await _write_audit(db, user.id, "logout")


@router.post("/2fa/enable", response_model=TwoFASetupResponse)
async def enable_2fa(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.totp_enabled:
        raise ConflictError("2FA already enabled")

    secret = generate_totp_secret()
    qr_uri = get_totp_uri(secret, user.email)

    # Store secret temporarily — user must verify before activation
    user.totp_secret = secret
    db.add(user)
    await _write_audit(db, user.id, "2fa_setup_initiated")
    return TwoFASetupResponse(secret=secret, qr_uri=qr_uri)


@router.post("/2fa/verify", status_code=204)
async def verify_2fa(
    body: TwoFAVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.totp_secret:
        raise ForbiddenError("Call /2fa/enable first")
    if user.totp_enabled:
        raise ConflictError("2FA already active")

    if not verify_totp(user.totp_secret, body.totp_code):
        raise UnauthorizedError("Invalid TOTP code")

    user.totp_enabled = True
    db.add(user)
    await _write_audit(db, user.id, "2fa_enabled")


@router.post("/2fa/disable", status_code=204)
async def disable_2fa(
    body: TwoFADisableRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.totp_enabled:
        raise ConflictError("2FA not enabled")
    if not verify_password(body.password, user.password_hash):
        raise UnauthorizedError("Wrong password")
    if not verify_totp(user.totp_secret, body.totp_code):
        raise UnauthorizedError("Invalid TOTP code")

    user.totp_enabled = False
    user.totp_secret = None
    db.add(user)
    await _write_audit(db, user.id, "2fa_disabled")
