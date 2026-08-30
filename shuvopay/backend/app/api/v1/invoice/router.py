from datetime import datetime, timedelta, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_admin
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import hash_api_key
from app.db.models import ApiKey, AuditLog, Invoice, Merchant, PaymentMatch, SmsLog
from app.db.session import get_db
from app.workers.match_engine import enqueue_match

log = structlog.get_logger()
router = APIRouter(tags=["Invoices & Payments"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class InvoiceCreateRequest(BaseModel):
    amount: float
    currency: str = "BDT"
    provider: str
    receiver_account: str | None = None
    time_window_minutes: int = 30
    metadata: dict | None = None


class InvoiceOut(BaseModel):
    id: str
    invoice_number: str
    amount: float
    currency: str
    provider: str
    receiver_account: str | None
    status: str
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class PaymentStatusOut(BaseModel):
    invoice_id: str
    status: str
    matched_at: datetime | None = None
    confidence: float | None = None
    provider: str | None = None
    transaction_id: str | None = None


class ManualMatchRequest(BaseModel):
    sms_log_id: str


class ReviewActionRequest(BaseModel):
    reason: str


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _get_merchant_for_user(user, db) -> Merchant:
    result = await db.execute(
        select(Merchant).where(Merchant.user_id == user.id, Merchant.deleted_at.is_(None))
    )
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise ForbiddenError("No merchant profile")
    return merchant


async def _get_merchant_by_api_key(api_key_raw: str, db) -> Merchant:
    key_hash = hash_api_key(api_key_raw)
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(ApiKey, Merchant)
        .join(Merchant, ApiKey.merchant_id == Merchant.id)
        .where(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active == True,
            (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
            Merchant.is_active == True,
        )
    )
    row = result.first()
    if not row:
        raise UnauthorizedError("Invalid or expired API key")
    api_key_obj, merchant = row

    # Update last_used
    api_key_obj.last_used_at = now
    db.add(api_key_obj)

    return merchant


import uuid as uuid_lib


def _generate_invoice_number() -> str:
    return f"INV-{uuid_lib.uuid4().hex[:8].upper()}"


# ─── Invoice Endpoints ───────────────────────────────────────────────────────

@router.post("/invoice", response_model=InvoiceOut)
async def create_invoice(
    body: InvoiceCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant_for_user(user, db)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=body.time_window_minutes)
    invoice = Invoice(
        merchant_id=merchant.id,
        invoice_number=_generate_invoice_number(),
        amount=body.amount,
        currency=body.currency,
        provider=body.provider,
        receiver_account=body.receiver_account,
        time_window_minutes=body.time_window_minutes,
        expires_at=expires_at,
        metadata=body.metadata,
        status="pending",
    )
    db.add(invoice)
    await db.flush()

    audit = AuditLog(
        actor_id=user.id,
        action="invoice_created",
        resource_type="invoice",
        resource_id=str(invoice.id),
        metadata={"amount": body.amount, "provider": body.provider},
    )
    db.add(audit)

    log.info("invoice_created", invoice_id=str(invoice.id), merchant_id=str(merchant.id))
    return InvoiceOut.model_validate(invoice)


@router.get("/invoice/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(
    invoice_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.deleted_at.is_(None))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise NotFoundError("Invoice")

    if user.role != "admin":
        merchant = await _get_merchant_for_user(user, db)
        if invoice.merchant_id != merchant.id:
            raise ForbiddenError("Not your invoice")

    return InvoiceOut.model_validate(invoice)


@router.patch("/invoice/{invoice_id}/cancel", response_model=InvoiceOut)
async def cancel_invoice(
    invoice_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.deleted_at.is_(None))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise NotFoundError("Invoice")

    if user.role != "admin":
        merchant = await _get_merchant_for_user(user, db)
        if invoice.merchant_id != merchant.id:
            raise ForbiddenError("Not your invoice")

    if invoice.status not in ("pending",):
        raise ConflictError(f"Cannot cancel invoice with status '{invoice.status}'")

    invoice.status = "cancelled"
    db.add(invoice)

    audit = AuditLog(
        actor_id=user.id,
        action="invoice_cancelled",
        resource_type="invoice",
        resource_id=invoice_id,
    )
    db.add(audit)
    return InvoiceOut.model_validate(invoice)


# ─── Public Payment Status (API Key auth) ───────────────────────────────────

@router.get("/payment/status/{invoice_id}", response_model=PaymentStatusOut)
async def public_payment_status(
    invoice_id: str,
    x_api_key: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
):
    if not x_api_key:
        raise UnauthorizedError("X-Api-Key header required")

    merchant = await _get_merchant_by_api_key(x_api_key, db)

    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.deleted_at.is_(None))
    )
    invoice = result.scalar_one_or_none()
    if not invoice or invoice.merchant_id != merchant.id:
        raise NotFoundError("Invoice")

    # Get latest match if any
    match_result = await db.execute(
        select(PaymentMatch, SmsLog)
        .join(SmsLog, PaymentMatch.sms_log_id == SmsLog.id)
        .where(PaymentMatch.invoice_id == invoice_id, PaymentMatch.status == "approved")
        .order_by(PaymentMatch.matched_at.desc())
        .limit(1)
    )
    row = match_result.first()

    return PaymentStatusOut(
        invoice_id=invoice_id,
        status=invoice.status,
        matched_at=row[0].matched_at if row else None,
        confidence=row[0].confidence_score if row else None,
        provider=row[1].provider if row else None,
        transaction_id=row[1].transaction_id if row else None,
    )


# ─── Admin Match Controls ────────────────────────────────────────────────────

@router.post("/payment/match", status_code=202)
async def trigger_manual_match(
    body: ManualMatchRequest,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await enqueue_match(body.sms_log_id)
    audit = AuditLog(
        actor_id=user.id,
        action="manual_match_triggered",
        resource_type="sms_log",
        resource_id=body.sms_log_id,
    )
    db.add(audit)
    return {"queued": True}


@router.patch("/payment/{match_id}/approve", response_model=dict)
async def approve_match(
    match_id: str,
    body: ReviewActionRequest,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PaymentMatch).where(PaymentMatch.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise NotFoundError("PaymentMatch")

    match.status = "approved"
    match.reviewed_by = user.email
    match.reviewed_at = datetime.now(timezone.utc)
    db.add(match)

    # Update invoice
    inv_result = await db.execute(select(Invoice).where(Invoice.id == match.invoice_id))
    invoice = inv_result.scalar_one_or_none()
    if invoice:
        invoice.status = "paid"
        db.add(invoice)

    # Update sms_log
    sms_result = await db.execute(select(SmsLog).where(SmsLog.id == match.sms_log_id))
    sms = sms_result.scalar_one_or_none()
    if sms:
        sms.status = "matched"
        db.add(sms)

    audit = AuditLog(
        actor_id=user.id,
        action="match_approved",
        resource_type="payment_match",
        resource_id=match_id,
        metadata={"reason": body.reason},
    )
    db.add(audit)

    # Re-enqueue webhook delivery
    from app.workers.webhook_worker import enqueue_webhook
    if invoice:
        await enqueue_webhook(match_id)

    return {"status": "approved"}


@router.patch("/payment/{match_id}/reject", response_model=dict)
async def reject_match(
    match_id: str,
    body: ReviewActionRequest,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PaymentMatch).where(PaymentMatch.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise NotFoundError("PaymentMatch")

    match.status = "rejected"
    match.reviewed_by = user.email
    match.reviewed_at = datetime.now(timezone.utc)
    db.add(match)

    # Revert invoice to pending
    inv_result = await db.execute(select(Invoice).where(Invoice.id == match.invoice_id))
    invoice = inv_result.scalar_one_or_none()
    if invoice and invoice.status == "review_required":
        invoice.status = "pending"
        db.add(invoice)

    audit = AuditLog(
        actor_id=user.id,
        action="match_rejected",
        resource_type="payment_match",
        resource_id=match_id,
        metadata={"reason": body.reason},
    )
    db.add(audit)
    return {"status": "rejected"}
