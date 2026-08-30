from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.db.models import AuditLog, Device, Invoice, Merchant, ParserRule, PaymentMatch, SmsLog, User, Webhook
from app.db.session import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["Admin"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class UserStatusUpdate(BaseModel):
    is_active: bool


class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str
    role: str = "merchant"
    merchant_name: str | None = None


class GlobalSettingsUpdate(BaseModel):
    match_engine_tolerance: float | None = None
    match_time_window_minutes: int | None = None
    match_confidence_threshold: float | None = None
    webhook_max_retries: int | None = None
    audit_log_retention_days: int | None = None


# ─── Dashboard ──────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def admin_dashboard(
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total_devices = (await db.execute(select(func.count(Device.id)))).scalar()
    online_devices = (await db.execute(
        select(func.count(Device.id)).where(Device.status == "online")
    )).scalar()
    total_sms = (await db.execute(select(func.count(SmsLog.id)))).scalar()
    matched_sms = (await db.execute(
        select(func.count(SmsLog.id)).where(SmsLog.status == "matched")
    )).scalar()
    pending_review = (await db.execute(
        select(func.count(PaymentMatch.id)).where(PaymentMatch.status == "pending")
    )).scalar()
    dead_webhooks = (await db.execute(
        select(func.count(Webhook.id)).where(Webhook.status == "dead")
    )).scalar()
    total_merchants = (await db.execute(
        select(func.count(Merchant.id)).where(Merchant.deleted_at.is_(None))
    )).scalar()

    return {
        "total_devices": total_devices,
        "online_devices": online_devices,
        "total_sms": total_sms,
        "matched_sms": matched_sms,
        "match_rate": round(matched_sms / max(total_sms, 1) * 100, 2),
        "pending_review": pending_review,
        "dead_webhooks": dead_webhooks,
        "total_merchants": total_merchants,
    }


# ─── Users ──────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    search: str | None = None,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(User).where(User.deleted_at.is_(None))
    if search:
        q = q.where(User.email.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
    q = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    users = result.scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "totp_enabled": u.totp_enabled,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ],
    }


@router.post("/users", status_code=201)
async def create_user(
    body: UserCreateRequest,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    new_user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    if body.role == "merchant" and body.merchant_name:
        merchant = Merchant(
            user_id=new_user.id,
            name=body.merchant_name,
            is_active=True,
        )
        db.add(merchant)

    audit = AuditLog(
        actor_id=admin.id,
        action="user_created",
        resource_type="user",
        resource_id=str(new_user.id),
        metadata={"role": body.role, "email": body.email},
    )
    db.add(audit)
    return {"id": str(new_user.id), "email": new_user.email}


@router.patch("/users/{user_id}/status", status_code=204)
async def update_user_status(
    user_id: str,
    body: UserStatusUpdate,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise NotFoundError("User")
    u.is_active = body.is_active
    db.add(u)

    audit = AuditLog(
        actor_id=admin.id,
        action="user_status_changed",
        resource_type="user",
        resource_id=user_id,
        metadata={"is_active": body.is_active},
    )
    db.add(audit)


# ─── Devices ────────────────────────────────────────────────────────────────

@router.get("/devices")
async def list_devices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(Device)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
    result = await db.execute(
        q.order_by(desc(Device.last_seen)).offset((page - 1) * page_size).limit(page_size)
    )
    devices = result.scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": str(d.id),
                "merchant_id": str(d.merchant_id),
                "name": d.name,
                "status": d.status,
                "last_seen": d.last_seen.isoformat() if d.last_seen else None,
            }
            for d in devices
        ],
    }


# ─── SMS Logs (all merchants) ────────────────────────────────────────────────

@router.get("/sms-logs")
async def admin_sms_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    status: str | None = None,
    provider: str | None = None,
    transaction_id: str | None = None,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(SmsLog)
    if status:
        q = q.where(SmsLog.status == status)
    if provider:
        q = q.where(SmsLog.provider == provider)
    if transaction_id:
        q = q.where(SmsLog.transaction_id == transaction_id)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
    result = await db.execute(
        q.order_by(desc(SmsLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    )
    items = result.scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": str(s.id),
                "merchant_id": str(s.merchant_id),
                "provider": s.provider,
                "transaction_id": s.transaction_id,
                "amount": float(s.amount) if s.amount else None,
                "currency": s.currency,
                "status": s.status,
                "parse_confidence": s.parse_confidence,
                "sms_timestamp": s.sms_timestamp.isoformat(),
                "created_at": s.created_at.isoformat(),
            }
            for s in items
        ],
    }


# ─── Pending Reviews ─────────────────────────────────────────────────────────

@router.get("/pending-reviews")
async def pending_reviews(
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PaymentMatch, Invoice, SmsLog)
        .join(Invoice, PaymentMatch.invoice_id == Invoice.id)
        .join(SmsLog, PaymentMatch.sms_log_id == SmsLog.id)
        .where(PaymentMatch.status == "pending")
        .order_by(desc(PaymentMatch.matched_at))
        .limit(100)
    )
    rows = result.all()
    return [
        {
            "match_id": str(m.id),
            "invoice_id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "invoice_amount": float(inv.amount),
            "sms_provider": sms.provider,
            "sms_amount": float(sms.amount) if sms.amount else None,
            "sms_transaction_id": sms.transaction_id,
            "confidence": m.confidence_score,
            "breakdown": m.scoring_breakdown,
            "matched_at": m.matched_at.isoformat(),
        }
        for m, inv, sms in rows
    ]


# ─── Audit Logs ──────────────────────────────────────────────────────────────

@router.get("/audit-logs")
async def audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, le=200),
    action: str | None = None,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action == action)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
    result = await db.execute(
        q.order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    )
    items = result.scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": str(a.id),
                "actor_id": str(a.actor_id) if a.actor_id else None,
                "action": a.action,
                "resource_type": a.resource_type,
                "resource_id": a.resource_id,
                "ip_address": str(a.ip_address) if a.ip_address else None,
                "metadata": a.metadata,
                "created_at": a.created_at.isoformat(),
            }
            for a in items
        ],
    }


# ─── Parser Rules (global) ───────────────────────────────────────────────────

@router.get("/settings")
async def get_settings(admin=Depends(require_admin)):
    from app.core.config import settings
    return {
        "match_engine_tolerance": settings.MATCH_ENGINE_TOLERANCE,
        "match_time_window_minutes": settings.MATCH_TIME_WINDOW_MINUTES,
        "match_confidence_threshold": settings.MATCH_CONFIDENCE_THRESHOLD,
        "webhook_max_retries": settings.WEBHOOK_MAX_RETRIES,
        "audit_log_retention_days": settings.AUDIT_LOG_RETENTION_DAYS,
    }


@router.put("/settings", status_code=204)
async def update_settings(
    body: GlobalSettingsUpdate,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Runtime settings update — in production, persist to DB or config service.
    Here we update in-memory config (pod restart resets to env defaults).
    """
    from app.core import config as cfg_module
    s = cfg_module.settings
    if body.match_engine_tolerance is not None:
        s.MATCH_ENGINE_TOLERANCE = body.match_engine_tolerance
    if body.match_time_window_minutes is not None:
        s.MATCH_TIME_WINDOW_MINUTES = body.match_time_window_minutes
    if body.match_confidence_threshold is not None:
        s.MATCH_CONFIDENCE_THRESHOLD = body.match_confidence_threshold
    if body.webhook_max_retries is not None:
        s.WEBHOOK_MAX_RETRIES = body.webhook_max_retries

    audit = AuditLog(
        actor_id=admin.id,
        action="global_settings_updated",
        resource_type="settings",
        metadata=body.model_dump(exclude_none=True),
    )
    db.add(audit)
