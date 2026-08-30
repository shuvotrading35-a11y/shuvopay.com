import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index,
    Integer, Interval, Numeric, String, Text, func, text
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def gen_uuid():
    return str(uuid.uuid4())


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SoftDeleteMixin:
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class User(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="merchant")  # merchant | admin
    totp_secret = Column(String(255), nullable=True)
    totp_enabled = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    merchant = relationship("Merchant", back_populates="user", uselist=False)
    audit_logs = relationship("AuditLog", back_populates="actor")


class Merchant(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "merchants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    webhook_url = Column(String(2048), nullable=True)
    webhook_secret_hash = Column(String(255), nullable=True)  # bcrypt — revealed only once
    is_active = Column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="merchant")
    devices = relationship("Device", back_populates="merchant")
    invoices = relationship("Invoice", back_populates="merchant")
    api_keys = relationship("ApiKey", back_populates="merchant")
    parser_rules = relationship("ParserRule", back_populates="merchant")
    sms_logs = relationship("SmsLog", back_populates="merchant")
    webhooks = relationship("Webhook", back_populates="merchant")


class Device(TimestampMixin, Base):
    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    fingerprint = Column(String(512), nullable=False, unique=True)
    fcm_token = Column(String(512), nullable=True)
    status = Column(String(50), default="offline")  # online | offline | syncing
    last_seen = Column(DateTime(timezone=True), nullable=True)

    merchant = relationship("Merchant", back_populates="devices")
    api_keys = relationship("DeviceApiKey", back_populates="device")
    sms_logs = relationship("SmsLog", back_populates="device")

    __table_args__ = (
        Index("idx_devices_merchant_status", "merchant_id", "status"),
    )


class DeviceApiKey(TimestampMixin, Base):
    __tablename__ = "device_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    key_hash = Column(String(255), nullable=False)  # PBKDF2-hashed
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    device = relationship("Device", back_populates="api_keys")


class SmsLog(TimestampMixin, Base):
    __tablename__ = "sms_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False, index=True)
    request_id = Column(String(36), nullable=False, unique=True)  # replay protection
    raw_sms_encrypted = Column(Text, nullable=False)              # AES-256-GCM ciphertext
    provider = Column(String(100), nullable=True, index=True)
    transaction_id = Column(String(255), nullable=True, index=True)
    amount = Column(Numeric(precision=15, scale=2), nullable=True)
    currency = Column(String(10), default="BDT", nullable=False)
    sender_number = Column(String(50), nullable=True)
    sender_name = Column(String(255), nullable=True)
    receiver_account = Column(String(255), nullable=True)
    sms_timestamp = Column(DateTime(timezone=True), nullable=False)
    parse_confidence = Column(Float, default=0.0, nullable=False)
    status = Column(String(50), default="unmatched", nullable=False, index=True)
    # status: unmatched | matched | review_required | duplicate

    device = relationship("Device", back_populates="sms_logs")
    merchant = relationship("Merchant", back_populates="sms_logs")
    payment_matches = relationship("PaymentMatch", back_populates="sms_log")

    __table_args__ = (
        Index("idx_sms_logs_provider_amount", "provider", "amount"),
        Index("idx_sms_logs_sms_timestamp", "sms_timestamp"),
        Index("idx_sms_logs_transaction_id", "transaction_id"),
    )


class Invoice(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False, index=True)
    invoice_number = Column(String(100), nullable=False, unique=True)
    amount = Column(Numeric(precision=15, scale=2), nullable=False)
    currency = Column(String(10), default="BDT", nullable=False)
    provider = Column(String(100), nullable=False, index=True)
    receiver_account = Column(String(255), nullable=True)
    status = Column(String(50), default="pending", nullable=False, index=True)
    # status: pending | paid | review_required | unmatched | cancelled
    time_window_minutes = Column(Integer, default=30, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    metadata = Column(JSONB, nullable=True)  # custom merchant metadata

    merchant = relationship("Merchant", back_populates="invoices")
    payment_matches = relationship("PaymentMatch", back_populates="invoice")

    __table_args__ = (
        Index("idx_invoices_status_provider", "status", "provider"),
        Index("idx_invoices_expires_at", "expires_at"),
    )


class PaymentMatch(TimestampMixin, Base):
    __tablename__ = "payment_matches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    sms_log_id = Column(UUID(as_uuid=True), ForeignKey("sms_logs.id"), nullable=False, index=True)
    confidence_score = Column(Float, nullable=False)
    scoring_breakdown = Column(JSONB, nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    # status: pending | approved | rejected
    reviewed_by = Column(String(255), nullable=True)  # admin user email
    matched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    invoice = relationship("Invoice", back_populates="payment_matches")
    sms_log = relationship("SmsLog", back_populates="payment_matches")
    webhooks = relationship("Webhook", back_populates="payment_match")


class Webhook(TimestampMixin, Base):
    __tablename__ = "webhooks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False, index=True)
    payment_match_id = Column(UUID(as_uuid=True), ForeignKey("payment_matches.id"), nullable=True, index=True)
    payload = Column(JSONB, nullable=False)
    status = Column(String(50), default="pending", nullable=False, index=True)
    # status: pending | delivered | failed | dead
    attempt_count = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    last_response_status = Column(Integer, nullable=True)
    last_response_body = Column(Text, nullable=True)

    merchant = relationship("Merchant", back_populates="webhooks")
    payment_match = relationship("PaymentMatch", back_populates="webhooks")

    __table_args__ = (
        Index("idx_webhooks_status_next_retry", "status", "next_retry_at"),
    )


class AuditLog(Base):
    """Immutable — no update/delete endpoints for this table."""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(255), nullable=True)
    ip_address = Column(INET, nullable=True)
    user_agent = Column(Text, nullable=True)
    metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    actor = relationship("User", back_populates="audit_logs")


class ParserRule(TimestampMixin, Base):
    __tablename__ = "parser_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=True, index=True)
    # NULL merchant_id = global rule
    rule_id = Column(String(100), nullable=False, unique=True)
    provider = Column(String(100), nullable=False)
    sender_pattern = Column(String(500), nullable=False)
    message_pattern = Column(Text, nullable=False)
    fields = Column(JSONB, nullable=False)   # {"amount": "group_1", ...}
    currency = Column(String(10), default="BDT", nullable=False)
    direction = Column(String(20), default="INBOUND", nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    etag = Column(String(64), nullable=True)  # for cache invalidation

    merchant = relationship("Merchant", back_populates="parser_rules")


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False, index=True)
    key_hash = Column(String(255), nullable=False)  # SHA-256 hashed
    label = Column(String(255), nullable=True)
    scope = Column(String(255), default="read:invoices,write:invoices", nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    merchant = relationship("Merchant", back_populates="api_keys")
