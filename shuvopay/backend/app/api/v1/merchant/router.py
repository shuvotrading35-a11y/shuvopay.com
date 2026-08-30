import secrets
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import generate_api_key, hash_api_key
from app.db.models import ApiKey, AuditLog, Invoice, Merchant, ParserRule, SmsLog
from app.db.session import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/merchant", tags=["Merchant"])


class ApiKeyCreateRequest(BaseModel):
    label: str | None = None
    scope: str = "read:invoices,write:invoices"
    expires_days: int | None = None


class ApiKeyOut(BaseModel):
    id: str
    label: str | None
    scope: str
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None

    class Config:
        from_attributes = True


class ApiKeyCreatedOut(ApiKeyOut):
    key: str  # raw — shown once


class ParserRuleUpsertRequest(BaseModel):
    rule_id: str
    provider: str
    sender_pattern: str
    message_pattern: str
    fields: dict
    currency: str = "BDT"
    direction: str = "INBOUND"
    enabled: bool = True


async def _get_merchant(user, db) -> Merchant:
    result = await db.execute(
        select(Merchant).where(Merchant.user_id == user.id, Merchant.deleted_at.is_(None))
    )
    m = result.scalar_one_or_none()
    if not m:
        raise ForbiddenError("No merchant profile")
    return m


@router.get("/dashboard")
async def merchant_dashboard(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant(user, db)

    total_inv = await db.execute(
        select(func.count(Invoice.id)).where(Invoice.merchant_id == merchant.id)
    )
    paid_inv = await db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.merchant_id == merchant.id, Invoice.status == "paid"
        )
    )
    pending_inv = await db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.merchant_id == merchant.id, Invoice.status == "pending"
        )
    )
    total_sms = await db.execute(
        select(func.count(SmsLog.id)).where(SmsLog.merchant_id == merchant.id)
    )

    return {
        "merchant_id": str(merchant.id),
        "total_invoices": total_inv.scalar(),
        "paid_invoices": paid_inv.scalar(),
        "pending_invoices": pending_inv.scalar(),
        "total_sms_received": total_sms.scalar(),
    }


@router.get("/transactions")
async def list_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    provider: str | None = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant(user, db)
    query = select(Invoice).where(Invoice.merchant_id == merchant.id, Invoice.deleted_at.is_(None))

    if status:
        query = query.where(Invoice.status == status)
    if provider:
        query = query.where(Invoice.provider == provider)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar()

    query = query.order_by(Invoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": str(i.id),
                "invoice_number": i.invoice_number,
                "amount": float(i.amount),
                "currency": i.currency,
                "provider": i.provider,
                "status": i.status,
                "created_at": i.created_at.isoformat(),
                "expires_at": i.expires_at.isoformat(),
            }
            for i in items
        ],
    }


@router.post("/api-key", response_model=ApiKeyCreatedOut)
async def generate_key(
    body: ApiKeyCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant(user, db)
    raw, hashed = generate_api_key()

    expires_at = None
    if body.expires_days:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days)

    api_key = ApiKey(
        merchant_id=merchant.id,
        key_hash=hashed,
        label=body.label,
        scope=body.scope,
        expires_at=expires_at,
        is_active=True,
    )
    db.add(api_key)
    await db.flush()

    audit = AuditLog(
        actor_id=user.id,
        action="api_key_created",
        resource_type="api_key",
        resource_id=str(api_key.id),
    )
    db.add(audit)

    return ApiKeyCreatedOut(
        id=str(api_key.id),
        label=api_key.label,
        scope=api_key.scope,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        last_used_at=None,
        key=raw,
    )


@router.delete("/api-key/{key_id}", status_code=204)
async def revoke_key(
    key_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant(user, db)
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.merchant_id == merchant.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise NotFoundError("ApiKey")

    key.is_active = False
    db.add(key)

    audit = AuditLog(
        actor_id=user.id,
        action="api_key_revoked",
        resource_type="api_key",
        resource_id=key_id,
    )
    db.add(audit)


@router.put("/parser-rules", status_code=200)
async def upsert_parser_rules(
    rules: list[ParserRuleUpsertRequest],
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant(user, db)
    created, updated = 0, 0

    for r in rules:
        existing = await db.execute(
            select(ParserRule).where(
                ParserRule.rule_id == r.rule_id,
                ParserRule.merchant_id == merchant.id,
            )
        )
        rule = existing.scalar_one_or_none()
        if rule:
            rule.provider = r.provider
            rule.sender_pattern = r.sender_pattern
            rule.message_pattern = r.message_pattern
            rule.fields = r.fields
            rule.currency = r.currency
            rule.direction = r.direction
            rule.enabled = r.enabled
            updated += 1
        else:
            rule = ParserRule(
                merchant_id=merchant.id,
                rule_id=r.rule_id,
                provider=r.provider,
                sender_pattern=r.sender_pattern,
                message_pattern=r.message_pattern,
                fields=r.fields,
                currency=r.currency,
                direction=r.direction,
                enabled=r.enabled,
            )
            created += 1
        db.add(rule)

    return {"created": created, "updated": updated}
