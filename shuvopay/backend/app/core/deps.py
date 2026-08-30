from typing import Annotated
from uuid import UUID

import jwt as pyjwt
import structlog
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token, verify_device_key
from app.db.models import Device, DeviceApiKey, Merchant, User
from app.db.session import get_db

log = structlog.get_logger()
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise UnauthorizedError("Bearer token required")
    try:
        payload = decode_token(credentials.credentials)
    except pyjwt.ExpiredSignatureError:
        raise UnauthorizedError("Token expired")
    except pyjwt.PyJWTError:
        raise UnauthorizedError("Invalid token")

    if payload.get("type") != "access":
        raise UnauthorizedError("Not an access token")

    user_id = payload.get("sub")
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None), User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found or inactive")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise ForbiddenError("Admin access required")
    return user


async def require_merchant(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("merchant", "admin"):
        raise ForbiddenError("Merchant access required")
    return user


async def get_authenticated_device(
    request: Request,
    x_device_key: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> Device:
    if not x_device_key:
        raise UnauthorizedError("X-Device-Key header required")

    # Load all active device keys and check in Python (PBKDF2 is not reversible)
    result = await db.execute(
        select(DeviceApiKey, Device)
        .join(Device, DeviceApiKey.device_id == Device.id)
        .where(DeviceApiKey.is_active == True)
    )
    rows = result.all()

    for key_row, device_row in rows:
        if verify_device_key(x_device_key, key_row.key_hash):
            # Check expiry
            from datetime import datetime, timezone
            if key_row.expires_at and key_row.expires_at < datetime.now(timezone.utc):
                raise UnauthorizedError("Device key expired")
            return device_row

    raise UnauthorizedError("Invalid device key")


async def replay_protection(
    request: Request,
    x_request_id: Annotated[str | None, Header()] = None,
) -> str:
    from app.core.redis_client import get_redis
    if not x_request_id:
        raise HTTPException(status_code=400, detail="X-Request-ID header required")

    redis = await get_redis()
    key = f"replay:{x_request_id}"
    exists = await redis.exists(key)
    if exists:
        raise HTTPException(status_code=409, detail="Duplicate request ID")

    # Store for 24 hours
    await redis.setex(key, 86400, "1")
    return x_request_id
