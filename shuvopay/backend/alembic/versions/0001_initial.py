"""Initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="merchant"),
        sa.Column("totp_secret", sa.String(255)),
        sa.Column("totp_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # merchants
    op.create_table(
        "merchants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("webhook_url", sa.String(2048)),
        sa.Column("webhook_secret_hash", sa.String(255)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_merchants_user_id", "merchants", ["user_id"])

    # devices
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("fingerprint", sa.String(512), nullable=False),
        sa.Column("fcm_token", sa.String(512)),
        sa.Column("status", sa.String(50), server_default="offline"),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_devices_fingerprint", "devices", ["fingerprint"], unique=True)
    op.create_index("ix_devices_merchant_id", "devices", ["merchant_id"])

    # device_api_keys
    op.create_table(
        "device_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # invoices
    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("invoice_number", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="BDT"),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("receiver_account", sa.String(255)),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("time_window_minutes", sa.Integer, nullable=False, server_default="30"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_invoices_invoice_number", "invoices", ["invoice_number"], unique=True)
    op.create_index("ix_invoices_merchant_status", "invoices", ["merchant_id", "status"])
    op.create_index("ix_invoices_expires_at", "invoices", ["expires_at"])

    # sms_logs
    op.create_table(
        "sms_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("raw_sms_encrypted", sa.Text, nullable=False),
        sa.Column("provider", sa.String(100)),
        sa.Column("transaction_id", sa.String(255)),
        sa.Column("amount", sa.Numeric(15, 2)),
        sa.Column("currency", sa.String(10), nullable=False, server_default="BDT"),
        sa.Column("sender_number", sa.String(50)),
        sa.Column("sender_name", sa.String(255)),
        sa.Column("receiver_account", sa.String(255)),
        sa.Column("sms_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parse_confidence", sa.Float, server_default="0.0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="unmatched"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sms_logs_request_id", "sms_logs", ["request_id"], unique=True)
    op.create_index("ix_sms_logs_transaction_id", "sms_logs", ["transaction_id"])
    op.create_index("ix_sms_logs_provider_amount", "sms_logs", ["provider", "amount"])

    # payment_matches
    op.create_table(
        "payment_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("sms_log_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sms_logs.id"), nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("scoring_breakdown", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # webhooks
    op.create_table(
        "webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("payment_match_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_matches.id")),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("last_response_status", sa.Integer),
        sa.Column("last_response_body", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_webhooks_status_retry", "webhooks", ["status", "next_retry_at"])

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100)),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("ip_address", postgresql.INET),
        sa.Column("user_agent", sa.Text),
        sa.Column("metadata", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])

    # parser_rules
    op.create_table(
        "parser_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id")),
        sa.Column("rule_id", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("sender_pattern", sa.String(500), nullable=False),
        sa.Column("message_pattern", sa.Text, nullable=False),
        sa.Column("fields", postgresql.JSONB, nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="BDT"),
        sa.Column("direction", sa.String(20), nullable=False, server_default="INBOUND"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("etag", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_parser_rules_rule_id", "parser_rules", ["rule_id"], unique=True)

    # api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("label", sa.String(255)),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("api_keys")
    op.drop_table("parser_rules")
    op.drop_table("audit_logs")
    op.drop_table("webhooks")
    op.drop_table("payment_matches")
    op.drop_table("sms_logs")
    op.drop_table("invoices")
    op.drop_table("device_api_keys")
    op.drop_table("devices")
    op.drop_table("merchants")
    op.drop_table("users")
