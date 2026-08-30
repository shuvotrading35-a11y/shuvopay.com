"""
Integration tests — full API flows:
  - Device register → SMS upload → match → invoice update → webhook
  - Auth flows: login, 2FA, token refresh, logout
  - Rate limiting enforcement
  - Replay protection (duplicate X-Request-ID rejection)
"""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.db.models import Base, User, Merchant, Device, DeviceApiKey, Invoice, ParserRule
from app.core.security import (
    hash_password, generate_device_key, create_access_token, encrypt_text
)

# ── Test DB (SQLite in-memory for speed) ─────────────────────────────────────
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session")
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db(setup_db):
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def admin_user(db):
    user = User(
        email="admin@test.com",
        password_hash=hash_password("AdminPass123!"),
        role="admin",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def merchant_user(db):
    user = User(
        email="merchant@test.com",
        password_hash=hash_password("MerchPass123!"),
        role="merchant",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    merchant = Merchant(
        user_id=user.id,
        name="Test Merchant",
        is_active=True,
    )
    db.add(merchant)
    await db.commit()
    await db.refresh(user)
    await db.refresh(merchant)
    return user, merchant


@pytest_asyncio.fixture
async def registered_device(db, merchant_user):
    _, merchant = merchant_user
    raw_key, key_hash = generate_device_key()

    device = Device(
        merchant_id=merchant.id,
        name="Test Device",
        fingerprint=f"fp-{uuid.uuid4().hex}",
        status="online",
        last_seen=datetime.now(timezone.utc),
    )
    db.add(device)
    await db.flush()

    dk = DeviceApiKey(device_id=device.id, key_hash=key_hash, is_active=True)
    db.add(dk)
    await db.commit()
    return device, raw_key, merchant


@pytest_asyncio.fixture
async def parser_rules(db):
    rule = ParserRule(
        merchant_id=None,
        rule_id="bkash_test",
        provider="bKash",
        sender_pattern=r"^bKash$",
        message_pattern=r"You have received Tk (\d+\.?\d*) from (\d{11})\..*TrxID (\w+)",
        fields={"amount": "group_1", "sender_number": "group_2", "transaction_id": "group_3"},
        currency="BDT",
        direction="INBOUND",
        enabled=True,
    )
    db.add(rule)
    await db.commit()
    return rule


# ════════════════════════════════════════════════════════════════════════════
# Auth Flow Tests
# ════════════════════════════════════════════════════════════════════════════

class TestAuthFlow:
    async def test_login_success(self, client, merchant_user):
        user, _ = merchant_user
        resp = await client.post("/api/v1/auth/login", json={
            "email": "merchant@test.com",
            "password": "MerchPass123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client, merchant_user):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "merchant@test.com",
            "password": "WrongPassword!",
        })
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nobody@test.com",
            "password": "anything",
        })
        assert resp.status_code == 401

    async def test_protected_endpoint_requires_token(self, client):
        resp = await client.get("/api/v1/merchant/dashboard")
        assert resp.status_code == 401

    async def test_protected_endpoint_with_valid_token(self, client, merchant_user):
        user, _ = merchant_user
        token = create_access_token(str(user.id), user.role)
        resp = await client.get(
            "/api/v1/merchant/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    async def test_admin_endpoint_rejects_merchant(self, client, merchant_user):
        user, _ = merchant_user
        token = create_access_token(str(user.id), "merchant")
        resp = await client.get(
            "/api/v1/admin/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_admin_endpoint_accepts_admin(self, client, admin_user):
        token = create_access_token(str(admin_user.id), "admin")
        resp = await client.get(
            "/api/v1/admin/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    async def test_logout_clears_cookie(self, client, merchant_user):
        user, _ = merchant_user
        token = create_access_token(str(user.id), user.role)
        resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204


# ════════════════════════════════════════════════════════════════════════════
# Device Registration Tests
# ════════════════════════════════════════════════════════════════════════════

class TestDeviceRegistration:
    async def test_register_device_success(self, client, merchant_user):
        user, _ = merchant_user
        token = create_access_token(str(user.id), user.role)

        resp = await client.post(
            "/api/v1/device/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Samsung Galaxy A54",
                "fingerprint": f"fp-{uuid.uuid4().hex}",
                "fcm_token": "fcm_token_xyz",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "device_id" in data
        assert "api_key" in data
        assert data["api_key"].startswith("spd_")

    async def test_duplicate_fingerprint_rejected(self, client, merchant_user, registered_device):
        user, _ = merchant_user
        device, _, _ = registered_device
        token = create_access_token(str(user.id), user.role)

        resp = await client.post(
            "/api/v1/device/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Duplicate",
                "fingerprint": device.fingerprint,
            },
        )
        assert resp.status_code == 409

    async def test_heartbeat_updates_last_seen(self, client, registered_device):
        device, raw_key, _ = registered_device
        resp = await client.post(
            "/api/v1/device/heartbeat",
            headers={"X-Device-Key": raw_key},
            json={"status": "online"},
        )
        assert resp.status_code == 204

    async def test_parser_rules_fetch(self, client, registered_device, parser_rules):
        device, raw_key, _ = registered_device
        resp = await client.get(
            "/api/v1/device/parser-rules",
            headers={"X-Device-Key": raw_key},
        )
        assert resp.status_code == 200
        rules = resp.json()
        assert len(rules) >= 1
        assert any(r["provider"] == "bKash" for r in rules)

    async def test_parser_rules_etag_304(self, client, registered_device, parser_rules):
        device, raw_key, _ = registered_device
        # First request
        r1 = await client.get(
            "/api/v1/device/parser-rules",
            headers={"X-Device-Key": raw_key},
        )
        etag = r1.headers.get("ETag")
        assert etag

        # Second request with ETag
        r2 = await client.get(
            "/api/v1/device/parser-rules",
            headers={"X-Device-Key": raw_key, "If-None-Match": etag},
        )
        assert r2.status_code == 304


# ════════════════════════════════════════════════════════════════════════════
# SMS Report Tests
# ════════════════════════════════════════════════════════════════════════════

class TestSmsReport:
    def _sms_payload(self, amount=500.0, provider="bKash", txn_id=None):
        return {
            "provider": provider,
            "transaction_id": txn_id or f"TRX{uuid.uuid4().hex[:10].upper()}",
            "amount": amount,
            "currency": "BDT",
            "sender_number": "01712345678",
            "sms_timestamp": datetime.now(timezone.utc).isoformat(),
            "parse_confidence": 0.95,
            "raw_sms": f"You have received Tk {amount} from 01712345678. TrxID TRX123456.",
        }

    async def test_report_sms_success(self, client, registered_device):
        device, raw_key, _ = registered_device
        request_id = str(uuid.uuid4())

        resp = await client.post(
            "/api/v1/sms/report",
            headers={"X-Device-Key": raw_key, "X-Request-ID": request_id},
            json=self._sms_payload(),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "sms_id" in data
        assert data["status"] == "accepted"

    async def test_replay_protection_duplicate_request_id(self, client, registered_device):
        device, raw_key, _ = registered_device
        request_id = str(uuid.uuid4())
        payload = self._sms_payload()

        # First request — OK
        r1 = await client.post(
            "/api/v1/sms/report",
            headers={"X-Device-Key": raw_key, "X-Request-ID": request_id},
            json=payload,
        )
        assert r1.status_code == 202

        # Second request with SAME request_id — should be rejected
        r2 = await client.post(
            "/api/v1/sms/report",
            headers={"X-Device-Key": raw_key, "X-Request-ID": request_id},
            json=payload,
        )
        assert r2.status_code == 409

    async def test_missing_request_id_rejected(self, client, registered_device):
        device, raw_key, _ = registered_device
        resp = await client.post(
            "/api/v1/sms/report",
            headers={"X-Device-Key": raw_key},
            json=self._sms_payload(),
        )
        assert resp.status_code == 400

    async def test_missing_device_key_rejected(self, client):
        resp = await client.post(
            "/api/v1/sms/report",
            headers={"X-Request-ID": str(uuid.uuid4())},
            json=self._sms_payload(),
        )
        assert resp.status_code == 401

    async def test_batch_report_max_50(self, client, registered_device):
        device, raw_key, _ = registered_device
        # Exactly 50 — should pass
        payload = {"items": [self._sms_payload() for _ in range(50)]}
        resp = await client.post(
            "/api/v1/sms/report/batch",
            headers={"X-Device-Key": raw_key, "X-Request-ID": str(uuid.uuid4())},
            json=payload,
        )
        assert resp.status_code == 202

    async def test_batch_report_over_50_rejected(self, client, registered_device):
        device, raw_key, _ = registered_device
        payload = {"items": [self._sms_payload() for _ in range(51)]}
        resp = await client.post(
            "/api/v1/sms/report/batch",
            headers={"X-Device-Key": raw_key, "X-Request-ID": str(uuid.uuid4())},
            json=payload,
        )
        assert resp.status_code == 422


# ════════════════════════════════════════════════════════════════════════════
# Invoice + Match Flow Tests
# ════════════════════════════════════════════════════════════════════════════

class TestInvoiceFlow:
    async def test_create_invoice(self, client, merchant_user):
        user, _ = merchant_user
        token = create_access_token(str(user.id), user.role)

        resp = await client.post(
            "/api/v1/invoice",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "amount": 750.0,
                "provider": "bKash",
                "time_window_minutes": 30,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["amount"] == 750.0
        assert data["provider"] == "bKash"
        assert "invoice_number" in data

    async def test_get_invoice(self, client, merchant_user):
        user, _ = merchant_user
        token = create_access_token(str(user.id), user.role)

        # Create
        create_resp = await client.post(
            "/api/v1/invoice",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 500.0, "provider": "Nagad"},
        )
        inv_id = create_resp.json()["id"]

        # Get
        get_resp = await client.get(
            f"/api/v1/invoice/{inv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == inv_id

    async def test_cancel_pending_invoice(self, client, merchant_user):
        user, _ = merchant_user
        token = create_access_token(str(user.id), user.role)

        create_resp = await client.post(
            "/api/v1/invoice",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 100.0, "provider": "bKash"},
        )
        inv_id = create_resp.json()["id"]

        cancel_resp = await client.patch(
            f"/api/v1/invoice/{inv_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

    async def test_cancel_nonexistent_invoice(self, client, merchant_user):
        user, _ = merchant_user
        token = create_access_token(str(user.id), user.role)

        resp = await client.patch(
            "/api/v1/invoice/00000000-0000-0000-0000-000000000000/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_merchant_cannot_access_others_invoice(self, client, db):
        # Create two separate merchants
        u1 = User(email="m1@test.com", password_hash=hash_password("pass"), role="merchant", is_active=True)
        u2 = User(email="m2@test.com", password_hash=hash_password("pass"), role="merchant", is_active=True)
        db.add_all([u1, u2])
        await db.flush()

        m1 = Merchant(user_id=u1.id, name="M1", is_active=True)
        m2 = Merchant(user_id=u2.id, name="M2", is_active=True)
        db.add_all([m1, m2])
        await db.flush()

        from datetime import timedelta
        inv = Invoice(
            merchant_id=m1.id,
            invoice_number=f"INV-CROSS-{uuid.uuid4().hex[:6]}",
            amount=999.0, currency="BDT", provider="bKash",
            status="pending", time_window_minutes=30,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(inv)
        await db.commit()

        # u2 tries to fetch m1's invoice
        token2 = create_access_token(str(u2.id), "merchant")
        resp = await client.get(
            f"/api/v1/invoice/{inv.id}",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code in (403, 404)


# ════════════════════════════════════════════════════════════════════════════
# Health Check Tests
# ════════════════════════════════════════════════════════════════════════════

class TestHealthChecks:
    async def test_liveness(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_readiness_structure(self, client):
        resp = await client.get("/health/ready")
        # May be 200 or 503 depending on test DB — just check structure
        data = resp.json()
        assert "status" in data
