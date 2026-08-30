import secrets
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import hash_webhook_secret
from app.db.models import AuditLog, Merchant, Webhook
from app.db.session import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/webhook", tags=["Webhooks"])


class WebhookSettingsRequest(BaseModel):
    webhook_url: str
    rotate_secret: bool = False


class WebhookSettingsResponse(BaseModel):
    webhook_url: str
    secret: str | None = None  # only shown when rotated/set


class WebhookLogOut(BaseModel):
    id: str
    status: str
    attempt_count: int
    last_attempted_at: datetime | None
    last_response_status: int | None
    next_retry_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


async def _get_merchant(user, db) -> Merchant:
    result = await db.execute(
        select(Merchant).where(Merchant.user_id == user.id, Merchant.deleted_at.is_(None))
    )
    m = result.scalar_one_or_none()
    if not m:
        raise ForbiddenError("No merchant profile")
    return m


@router.post("/settings", response_model=WebhookSettingsResponse)
async def set_webhook(
    body: WebhookSettingsRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant(user, db)
    merchant.webhook_url = body.webhook_url

    raw_secret = None
    if body.rotate_secret or not merchant.webhook_secret_hash:
        raw_secret = "whsec_" + secrets.token_urlsafe(32)
        merchant.webhook_secret_hash = hash_webhook_secret(raw_secret)

    db.add(merchant)

    audit = AuditLog(
        actor_id=user.id,
        action="webhook_settings_updated",
        resource_type="merchant",
        resource_id=str(merchant.id),
    )
    db.add(audit)

    return WebhookSettingsResponse(
        webhook_url=merchant.webhook_url,
        secret=raw_secret,  # None if not rotated
    )


@router.get("/logs", response_model=list[WebhookLogOut])
async def webhook_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant(user, db)
    result = await db.execute(
        select(Webhook)
        .where(Webhook.merchant_id == merchant.id)
        .order_by(Webhook.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [WebhookLogOut.model_validate(w) for w in result.scalars()]


@router.post("/test", response_model=dict)
async def test_webhook(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant(user, db)
    if not merchant.webhook_url:
        raise ForbiddenError("Configure a webhook URL first")

    import httpx, json, hashlib, hmac, time

    test_payload = {
        "event": "webhook.test",
        "merchant_id": str(merchant.id),
        "message": "ShuvoPay webhook test — if you receive this, your endpoint is configured correctly.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload_bytes = json.dumps(test_payload, sort_keys=True).encode()
    ts = str(int(time.time()))
    secret = merchant.webhook_secret_hash or merchant.id.hex
    sig = "sha256=" + hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                merchant.webhook_url,
                content=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-ShuvoPay-Signature": sig,
                    "X-ShuvoPay-Timestamp": ts,
                },
            )
        return {"status": resp.status_code, "success": 200 <= resp.status_code < 300}
    except Exception as e:
        return {"status": 0, "success": False, "error": str(e)}


@router.post("/retry/{webhook_id}", response_model=dict)
async def retry_webhook(
    webhook_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    merchant = await _get_merchant(user, db)
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.merchant_id == merchant.id)
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise NotFoundError("Webhook")

    webhook.status = "pending"
    webhook.next_retry_at = datetime.now(timezone.utc)
    db.add(webhook)

    from app.workers.webhook_worker import deliver_webhook
    import asyncio
    asyncio.create_task(deliver_webhook(webhook_id))

    return {"queued": True}
