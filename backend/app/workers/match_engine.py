"""
Match Engine — runs as a Celery task or RQ job.
Called every time a new SMS is reported.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AuditLog, Invoice, PaymentMatch, SmsLog
from app.db.session import async_session

log = structlog.get_logger()


# ─── Scoring weights ────────────────────────────────────────────────────────
WEIGHT_PROVIDER = 0.0       # binary prerequisite (no match = skip)
WEIGHT_AMOUNT = 0.35
WEIGHT_TIME_WINDOW = 0.30
WEIGHT_TXN_UNIQUE = 0.25
WEIGHT_RECEIVER = 0.10


class MatchScore:
    def __init__(self):
        self.breakdown: dict = {}
        self.total: float = 0.0

    def add(self, key: str, weight: float, matched: bool):
        score = weight if matched else 0.0
        self.breakdown[key] = {"weight": weight, "score": score, "matched": matched}
        self.total += score

    def finalize(self) -> float:
        return round(self.total, 4)


async def run_match_for_sms(sms_id: str):
    async with async_session() as db:
        try:
            await _match(db, sms_id)
            await db.commit()
        except Exception as e:
            await db.rollback()
            log.exception("match_engine_error", sms_id=sms_id, error=str(e))


async def _match(db: AsyncSession, sms_id: str):
    sms_result = await db.execute(select(SmsLog).where(SmsLog.id == sms_id))
    sms: Optional[SmsLog] = sms_result.scalar_one_or_none()

    if not sms:
        log.warning("match_sms_not_found", sms_id=sms_id)
        return

    if sms.status in ("matched",):
        log.info("match_already_matched", sms_id=sms_id)
        return

    if not sms.amount or not sms.provider:
        log.info("match_insufficient_fields", sms_id=sms_id)
        return

    # Fetch open invoices for same merchant + provider
    now = datetime.now(timezone.utc)
    inv_result = await db.execute(
        select(Invoice).where(
            Invoice.merchant_id == sms.merchant_id,
            Invoice.provider == sms.provider,
            Invoice.status == "pending",
            Invoice.deleted_at.is_(None),
            Invoice.expires_at >= sms.sms_timestamp,  # not yet expired at SMS time
        )
    )
    invoices = inv_result.scalars().all()

    if not invoices:
        log.info("match_no_candidates", sms_id=sms_id, provider=sms.provider)
        sms.status = "unmatched"
        db.add(sms)
        return

    tolerance = Decimal(str(settings.MATCH_ENGINE_TOLERANCE))
    sms_amount = Decimal(str(sms.amount))

    candidates = []

    for invoice in invoices:
        scorer = MatchScore()
        inv_amount = Decimal(str(invoice.amount))

        # 1. Amount match
        amount_match = abs(sms_amount - inv_amount) <= tolerance
        scorer.add("amount", WEIGHT_AMOUNT, amount_match)

        # 2. Time window
        window_start = invoice.created_at
        window_end = invoice.created_at.replace(tzinfo=timezone.utc) + \
            __import__("datetime").timedelta(minutes=invoice.time_window_minutes)
        sms_ts = sms.sms_timestamp
        if sms_ts.tzinfo is None:
            sms_ts = sms_ts.replace(tzinfo=timezone.utc)
        time_match = window_start.replace(tzinfo=timezone.utc) <= sms_ts <= window_end
        scorer.add("time_window", WEIGHT_TIME_WINDOW, time_match)

        # 3. Transaction ID uniqueness
        if sms.transaction_id:
            existing_match = await db.execute(
                select(PaymentMatch)
                .join(SmsLog, PaymentMatch.sms_log_id == SmsLog.id)
                .where(
                    SmsLog.transaction_id == sms.transaction_id,
                    PaymentMatch.status.in_(["pending", "approved"]),
                )
            )
            txn_unique = existing_match.first() is None
        else:
            txn_unique = True  # no txn ID — can't check uniqueness, give benefit
        scorer.add("txn_unique", WEIGHT_TXN_UNIQUE, txn_unique)

        # 4. Receiver account match (optional)
        if invoice.receiver_account and sms.receiver_account:
            receiver_match = invoice.receiver_account.strip() == sms.receiver_account.strip()
        else:
            receiver_match = True  # not specified — pass
        scorer.add("receiver_account", WEIGHT_RECEIVER, receiver_match)

        confidence = scorer.finalize()

        # Only consider candidates with amount + time matched
        if not amount_match or not time_match or not txn_unique:
            continue

        candidates.append((invoice, confidence, scorer.breakdown))

    if not candidates:
        sms.status = "unmatched"
        db.add(sms)
        log.info("match_no_valid_candidates", sms_id=sms_id)
        return

    threshold = settings.MATCH_CONFIDENCE_THRESHOLD

    high_conf = [(inv, score, bd) for inv, score, bd in candidates if score >= threshold]

    if len(high_conf) == 1:
        invoice, confidence, breakdown = high_conf[0]
        await _finalize_match(db, sms, invoice, confidence, breakdown, status="approved")
        log.info("match_paid", sms_id=sms_id, invoice_id=str(invoice.id), confidence=confidence)

    elif len(high_conf) > 1:
        # Ambiguous — multiple high-confidence matches
        invoice, confidence, breakdown = high_conf[0]  # best candidate
        await _finalize_match(db, sms, invoice, confidence, breakdown, status="pending")
        invoice.status = "review_required"
        db.add(invoice)
        sms.status = "review_required"
        db.add(sms)
        log.warning("match_ambiguous", sms_id=sms_id, candidates=len(high_conf))

    else:
        # Low confidence
        invoice, confidence, breakdown = candidates[0]
        await _finalize_match(db, sms, invoice, confidence, breakdown, status="pending")
        invoice.status = "review_required"
        db.add(invoice)
        sms.status = "review_required"
        db.add(sms)
        log.info("match_low_confidence", sms_id=sms_id, confidence=confidence)


async def _finalize_match(
    db: AsyncSession,
    sms: SmsLog,
    invoice: Invoice,
    confidence: float,
    breakdown: dict,
    status: str,
):
    from app.workers.webhook_worker import enqueue_webhook

    match = PaymentMatch(
        invoice_id=invoice.id,
        sms_log_id=sms.id,
        confidence_score=confidence,
        scoring_breakdown=breakdown,
        status=status,
        matched_at=datetime.now(timezone.utc),
    )
    db.add(match)
    await db.flush()

    if status == "approved":
        invoice.status = "paid"
        sms.status = "matched"
        db.add(invoice)
        db.add(sms)

        # Audit
        audit = AuditLog(
            action="payment_matched",
            resource_type="invoice",
            resource_id=str(invoice.id),
            metadata={
                "sms_id": str(sms.id),
                "confidence": confidence,
                "transaction_id": sms.transaction_id,
            },
        )
        db.add(audit)
        await db.flush()

        # Enqueue webhook + WebSocket push
        await enqueue_webhook(str(match.id))
        await _push_websocket(str(invoice.merchant_id), invoice, sms, confidence)


async def _push_websocket(merchant_id: str, invoice: Invoice, sms: SmsLog, confidence: float):
    """Push live update to connected merchant WebSocket sessions."""
    from app.api.v1.websocket import manager
    try:
        await manager.broadcast_to_merchant(
            merchant_id,
            {
                "event": "payment.confirmed",
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "amount": float(invoice.amount),
                "provider": sms.provider,
                "transaction_id": sms.transaction_id,
                "confidence": confidence,
            },
        )
    except Exception as e:
        log.warning("websocket_push_failed", error=str(e))


# ─── Celery/RQ task enqueue stub ─────────────────────────────────────────────

async def enqueue_match(sms_id: str):
    """
    In production: enqueue to Celery or RQ.
    For simplicity here, runs async inline.
    Replace with: celery_app.send_task("match_engine.run", args=[sms_id])
    """
    import asyncio
    asyncio.create_task(run_match_for_sms(sms_id))
