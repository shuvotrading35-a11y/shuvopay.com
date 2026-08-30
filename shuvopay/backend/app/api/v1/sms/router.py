from datetime import datetime
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, condecimal, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_authenticated_device, get_current_user, replay_protection, require_admin
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import encrypt_text, decrypt_text
from app.db.models import AuditLog, Device, SmsLog
from app.db.session import get_db
from app.workers.match_engine import enqueue_match

log = structlog.get_logger()
router = APIRouter(prefix="/sms", tags=["SMS"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class SmsReportRequest(BaseModel):
    provider: str | None = None
    transaction_id: str | None = None
    amount: float | None = None
    currency: str = "BDT"
    sender_number: str | None = None
    sender_name: str | None = None
    receiver_account: str | None = None
    sms_timestamp: datetime
    parse_confidence: float = 0.0
    raw_sms: str  # plaintext — will be encrypted at rest

    @field_validator("parse_confidence")
    @classmethod
    def clamp_confidence(cls, v):
        return max(0.0, min(1.0, v))


class SmsBatchRequest(BaseModel):
    items: list[SmsReportRequest]

    @field_validator("items")
    @classmethod
    def max_50(cls, v):
        if len(v) > 50:
            raise ValueError("Batch size cannot exceed 50")
        return v


class SmsLogOut(BaseModel):
    id: str
    provider: str | None
    transaction_id: str | None
    amount: float | None
    currency: str
    sender_number: str | None
    sms_timestamp: datetime
    parse_confidence: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class SmsLogDetail(SmsLogOut):
    raw_sms: str  # decrypted for authorized viewers
    sender_name: str | None
    receiver_account: str | None


class PaginatedSmsLogs(BaseModel):
    items: list[SmsLogOut]
    total: int
    page: int
    page_size: int


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _save_sms(db: AsyncSession, device: Device, req: SmsReportRequest, request_id: str) -> SmsLog:
    encrypted_raw = encrypt_text(req.raw_sms)

    sms = SmsLog(
        device_id=device.id,
        merchant_id=device.merchant_id,
        request_id=request_id,
        raw_sms_encrypted=encrypted_raw,
        provider=req.provider,
        transaction_id=req.transaction_id,
        amount=req.amount,
        currency=req.currency,
        sender_number=req.sender_number,
        sender_name=req.sender_name,
        receiver_account=req.receiver_account,
        sms_timestamp=req.sms_timestamp,
        parse_confidence=req.parse_confidence,
        status="unmatched",
    )
    db.add(sms)
    return sms


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/report", status_code=202)
async def report_sms(
    body: SmsReportRequest,
    device: Device = Depends(get_authenticated_device),
    request_id: str = Depends(replay_protection),
    db: AsyncSession = Depends(get_db),
):
    sms = await _save_sms(db, device, body, request_id)
    await db.flush()

    # Enqueue async match
    await enqueue_match(str(sms.id))

    log.info("sms_reported", sms_id=str(sms.id), device_id=str(device.id))
    return {"sms_id": str(sms.id), "status": "accepted"}


@router.post("/report/batch", status_code=202)
async def report_sms_batch(
    body: SmsBatchRequest,
    device: Device = Depends(get_authenticated_device),
    request_id: str = Depends(replay_protection),
    db: AsyncSession = Depends(get_db),
):
    created_ids = []
    for i, item in enumerate(body.items):
        # Each item gets a unique sub-request-id
        sub_id = f"{request_id}-{i}"
        sms = await _save_sms(db, device, item, sub_id)
        await db.flush()
        created_ids.append(str(sms.id))
        await enqueue_match(str(sms.id))

    log.info("sms_batch_reported", count=len(created_ids), device_id=str(device.id))
    return {"accepted": len(created_ids), "sms_ids": created_ids}


@router.get("/logs", response_model=PaginatedSmsLogs)
async def list_sms_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    provider: str | None = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.db.models import Merchant

    query = select(SmsLog)

    if user.role != "admin":
        merchant_result = await db.execute(
            select(Merchant).where(Merchant.user_id == user.id)
        )
        merchant = merchant_result.scalar_one_or_none()
        if not merchant:
            raise ForbiddenError("No merchant profile")
        query = query.where(SmsLog.merchant_id == merchant.id)

    if status:
        query = query.where(SmsLog.status == status)
    if provider:
        query = query.where(SmsLog.provider == provider)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    query = query.order_by(SmsLog.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return PaginatedSmsLogs(
        items=[SmsLogOut.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/logs/{sms_id}", response_model=SmsLogDetail)
async def get_sms_log(
    sms_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SmsLog).where(SmsLog.id == sms_id))
    sms = result.scalar_one_or_none()
    if not sms:
        raise NotFoundError("SmsLog")

    if user.role != "admin":
        from app.db.models import Merchant
        merchant_result = await db.execute(
            select(Merchant).where(Merchant.user_id == user.id)
        )
        merchant = merchant_result.scalar_one_or_none()
        if not merchant or sms.merchant_id != merchant.id:
            raise ForbiddenError("Not your SMS log")

    # Decrypt raw SMS for authorized viewer
    raw = decrypt_text(sms.raw_sms_encrypted)

    # Write audit log for sensitive data access
    audit = AuditLog(
        actor_id=user.id,
        action="sms_log_viewed",
        resource_type="sms_log",
        resource_id=sms_id,
    )
    db.add(audit)

    return SmsLogDetail(
        id=str(sms.id),
        provider=sms.provider,
        transaction_id=sms.transaction_id,
        amount=float(sms.amount) if sms.amount else None,
        currency=sms.currency,
        sender_number=sms.sender_number,
        sender_name=sms.sender_name,
        receiver_account=sms.receiver_account,
        sms_timestamp=sms.sms_timestamp,
        parse_confidence=sms.parse_confidence,
        status=sms.status,
        created_at=sms.created_at,
        raw_sms=raw,
    )


@router.delete("/logs/{sms_id}", status_code=204)
async def delete_sms_log(
    sms_id: str,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hard delete — GDPR compliance (admin only)."""
    result = await db.execute(select(SmsLog).where(SmsLog.id == sms_id))
    sms = result.scalar_one_or_none()
    if not sms:
        raise NotFoundError("SmsLog")

    await db.delete(sms)

    audit = AuditLog(
        actor_id=user.id,
        action="sms_log_deleted",
        resource_type="sms_log",
        resource_id=sms_id,
        metadata={"reason": "GDPR hard delete"},
    )
    db.add(audit)
    log.warning("sms_log_hard_deleted", sms_id=sms_id, actor=str(user.id))
