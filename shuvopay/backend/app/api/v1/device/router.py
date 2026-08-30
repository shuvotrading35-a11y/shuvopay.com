import hashlib
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_authenticated_device, get_current_user
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import generate_device_key
from app.db.models import AuditLog, Device, DeviceApiKey, Merchant, ParserRule
from app.db.session import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/device", tags=["Device"])


class DeviceRegisterRequest(BaseModel):
    name: str
    fingerprint: str
    fcm_token: str | None = None


class DeviceRegisterResponse(BaseModel):
    device_id: str
    api_key: str  # raw key — shown once only


class HeartbeatRequest(BaseModel):
    status: str = "online"


class ParserRuleOut(BaseModel):
    rule_id: str
    provider: str
    sender_pattern: str
    message_pattern: str
    fields: dict
    currency: str
    direction: str
    enabled: bool

    class Config:
        from_attributes = True


@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(
    body: DeviceRegisterRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Resolve merchant for this user
    result = await db.execute(
        select(Merchant).where(Merchant.user_id == user.id, Merchant.deleted_at.is_(None))
    )
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise ForbiddenError("No merchant profile found")

    # Check fingerprint uniqueness
    existing = await db.execute(
        select(Device).where(Device.fingerprint == body.fingerprint)
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Device with this fingerprint already registered")

    device = Device(
        merchant_id=merchant.id,
        name=body.name,
        fingerprint=body.fingerprint,
        fcm_token=body.fcm_token,
        status="offline",
        last_seen=datetime.now(timezone.utc),
    )
    db.add(device)
    await db.flush()

    raw_key, key_hash = generate_device_key()
    api_key = DeviceApiKey(
        device_id=device.id,
        key_hash=key_hash,
        is_active=True,
    )
    db.add(api_key)

    audit = AuditLog(
        actor_id=user.id,
        action="device_registered",
        resource_type="device",
        resource_id=str(device.id),
    )
    db.add(audit)

    log.info("device_registered", device_id=str(device.id), merchant_id=str(merchant.id))
    return DeviceRegisterResponse(device_id=str(device.id), api_key=raw_key)


@router.post("/heartbeat", status_code=204)
async def heartbeat(
    body: HeartbeatRequest,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_db),
):
    device.status = body.status
    device.last_seen = datetime.now(timezone.utc)
    db.add(device)


@router.get("/parser-rules", response_model=list[ParserRuleOut])
async def get_parser_rules(
    request: Request,
    response: Response,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ParserRule).where(
            (ParserRule.merchant_id == device.merchant_id) | (ParserRule.merchant_id.is_(None)),
            ParserRule.enabled == True,
        )
    )
    rules = result.scalars().all()

    # ETag caching: hash of rule IDs + updated_at
    etag_source = "".join(str(r.id) + str(r.updated_at) for r in rules)
    etag = hashlib.sha256(etag_source.encode()).hexdigest()[:16]

    if_none_match = request.headers.get("If-None-Match")
    if if_none_match == etag:
        return Response(status_code=304)

    response.headers["ETag"] = etag
    return [ParserRuleOut.model_validate(r) for r in rules]


@router.delete("/{device_id}", status_code=204)
async def deregister_device(
    device_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise NotFoundError("Device")

    # Verify ownership
    merchant_result = await db.execute(
        select(Merchant).where(Merchant.user_id == user.id)
    )
    merchant = merchant_result.scalar_one_or_none()
    if not merchant or device.merchant_id != merchant.id:
        if user.role != "admin":
            raise ForbiddenError("Not your device")

    # Revoke all device keys
    keys_result = await db.execute(
        select(DeviceApiKey).where(DeviceApiKey.device_id == device.id)
    )
    for key in keys_result.scalars():
        key.is_active = False
        db.add(key)

    device.status = "offline"
    db.add(device)

    audit = AuditLog(
        actor_id=user.id,
        action="device_deregistered",
        resource_type="device",
        resource_id=device_id,
    )
    db.add(audit)
