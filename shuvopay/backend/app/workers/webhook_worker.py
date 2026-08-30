"""
Webhook delivery worker — HMAC-signed, 7-attempt exponential backoff.
Retry schedule: 10s → 30s → 2m → 10m → 30m → 2h → 6h
"""
import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AuditLog, Invoice, Merchant, PaymentMatch, SmsLog, Webhook
from app.db.session import async_session

log = structlog.get_logger()

# Retry intervals in seconds
RETRY_SCHEDULE = [10, 30, 120, 600, 1800, 7200, 21600]


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _build_payload(match: PaymentMatch, invoice: Invoice, sms: SmsLog) -> dict:
    return {
        "event": "payment.confirmed",
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "merchant_id": str(invoice.merchant_id),
        "status": invoice.status,
        "amount": float(invoice.amount),
        "currency": invoice.currency,
        "provider": sms.provider,
        "transaction_id": sms.transaction_id,
        "matched_at": match.matched_at.isoformat() if match.matched_at else None,
        "confidence": match.confidence_score,
    }


async def enqueue_webhook(match_id: str):
    """Create a webhook record and trigger delivery."""
    async with async_session() as db:
        match_result = await db.execute(
            select(PaymentMatch, Invoice, SmsLog, Merchant)
            .join(Invoice, PaymentMatch.invoice_id == Invoice.id)
            .join(SmsLog, PaymentMatch.sms_log_id == SmsLog.id)
            .join(Merchant, Invoice.merchant_id == Merchant.id)
            .where(PaymentMatch.id == match_id)
        )
        row = match_result.first()
        if not row:
            log.warning("webhook_enqueue_match_not_found", match_id=match_id)
            return

        match, invoice, sms, merchant = row

        if not merchant.webhook_url:
            log.info("webhook_no_url_configured", merchant_id=str(merchant.id))
            return

        payload = _build_payload(match, invoice, sms)
        webhook = Webhook(
            merchant_id=merchant.id,
            payment_match_id=match.id,
            payload=payload,
            status="pending",
            attempt_count=0,
            next_retry_at=datetime.now(timezone.utc),
        )
        db.add(webhook)
        await db.commit()

        asyncio.create_task(deliver_webhook(str(webhook.id)))


async def deliver_webhook(webhook_id: str):
    async with async_session() as db:
        result = await db.execute(
            select(Webhook, Merchant)
            .join(Merchant, Webhook.merchant_id == Merchant.id)
            .where(Webhook.id == webhook_id)
        )
        row = result.first()
        if not row:
            return

        webhook, merchant = row

        if not merchant.webhook_url:
            webhook.status = "dead"
            db.add(webhook)
            await db.commit()
            return

        attempt = webhook.attempt_count
        if attempt >= settings.WEBHOOK_MAX_RETRIES:
            webhook.status = "dead"
            db.add(webhook)
            await db.commit()
            log.error("webhook_dead", webhook_id=webhook_id, attempts=attempt)
            await _alert_admin_dead_webhook(webhook_id, str(merchant.id))
            return

        payload_bytes = json.dumps(webhook.payload, sort_keys=True).encode()
        timestamp = str(int(time.time()))

        # Reconstruct signing secret (we stored hash — in production store encrypted)
        # For demo: use merchant ID as signing material fallback
        secret = merchant.webhook_secret_hash or merchant.id.hex
        signature = _sign_payload(payload_bytes, secret)

        headers = {
            "Content-Type": "application/json",
            "X-ShuvoPay-Signature": signature,
            "X-ShuvoPay-Timestamp": timestamp,
            "X-Webhook-ID": webhook_id,
            "User-Agent": "ShuvoPay-Webhook/1.0",
        }

        try:
            async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    merchant.webhook_url,
                    content=payload_bytes,
                    headers=headers,
                )
            success = 200 <= resp.status_code < 300
            webhook.last_response_status = resp.status_code
            webhook.last_response_body = resp.text[:1000]  # truncate
        except Exception as e:
            log.warning("webhook_delivery_error", webhook_id=webhook_id, error=str(e))
            success = False
            webhook.last_response_body = str(e)[:1000]

        webhook.attempt_count += 1
        webhook.last_attempted_at = datetime.now(timezone.utc)

        if success:
            webhook.status = "delivered"
            log.info("webhook_delivered", webhook_id=webhook_id, attempt=attempt + 1)
        else:
            next_attempt_idx = min(attempt, len(RETRY_SCHEDULE) - 1)
            delay = RETRY_SCHEDULE[next_attempt_idx]
            webhook.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            webhook.status = "failed"
            log.warning(
                "webhook_failed",
                webhook_id=webhook_id,
                attempt=attempt + 1,
                next_retry_in=delay,
                status=getattr(webhook, "last_response_status", None),
            )
            # Schedule retry
            asyncio.get_event_loop().call_later(
                delay, lambda: asyncio.create_task(deliver_webhook(webhook_id))
            )

        db.add(webhook)
        await db.commit()


async def _alert_admin_dead_webhook(webhook_id: str, merchant_id: str):
    """In production: send FCM notification or email to admin."""
    log.error("webhook_dead_alert", webhook_id=webhook_id, merchant_id=merchant_id)
