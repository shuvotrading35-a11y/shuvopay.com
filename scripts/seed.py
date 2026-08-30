#!/usr/bin/env python3
"""
Seed script: creates admin, 2 merchants, 5 devices, parser rules, 50 SMS logs, 30 invoices.
Run: python scripts/seed.py
"""
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings
from app.core.security import hash_password, encrypt_text, generate_device_key, generate_api_key
from app.db.models import (
    ApiKey, AuditLog, Base, Device, DeviceApiKey,
    Invoice, Merchant, ParserRule, PaymentMatch, SmsLog, User,
)

engine = create_async_engine(str(settings.DATABASE_URL), echo=False)
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

PROVIDERS = ["bKash", "Nagad", "Rocket", "Upay"]
BD_SENDERS = {
    "bKash": "bKash",
    "Nagad": "Nagad",
    "Rocket": "DBBLMFS",
    "Upay": "Upay",
}

PARSER_RULES = [
    {
        "rule_id": "bkash_v3",
        "provider": "bKash",
        "sender_pattern": r"^bKash$",
        "message_pattern": r"You have received Tk (\d+\.?\d*) from (\d{11})\..*TrxID (\w+).*",
        "fields": {"amount": "group_1", "sender_number": "group_2", "transaction_id": "group_3"},
        "currency": "BDT",
        "direction": "INBOUND",
    },
    {
        "rule_id": "nagad_v2",
        "provider": "Nagad",
        "sender_pattern": r"^Nagad$",
        "message_pattern": r"Apnar Nagad Account-e Tk\.(\d+\.?\d*) jama hoyeche\..*TrxID:(\w+)",
        "fields": {"amount": "group_1", "transaction_id": "group_2"},
        "currency": "BDT",
        "direction": "INBOUND",
    },
    {
        "rule_id": "rocket_v2",
        "provider": "Rocket",
        "sender_pattern": r"^DBBLMFS$",
        "message_pattern": r"Tk\.(\d+\.?\d*) received from (\d{11})\. TxnID:(\w+)",
        "fields": {"amount": "group_1", "sender_number": "group_2", "transaction_id": "group_3"},
        "currency": "BDT",
        "direction": "INBOUND",
    },
    {
        "rule_id": "upay_v1",
        "provider": "Upay",
        "sender_pattern": r"^Upay$",
        "message_pattern": r"BDT (\d+\.?\d*) received\. Ref:(\w+)",
        "fields": {"amount": "group_1", "transaction_id": "group_2"},
        "currency": "BDT",
        "direction": "INBOUND",
    },
    {
        "rule_id": "dbbl_v1",
        "provider": "Dutch-Bangla Bank",
        "sender_pattern": r"^DBBL$",
        "message_pattern": r"Credited BDT (\d+\.?\d*) to your account.*Ref:(\w+)",
        "fields": {"amount": "group_1", "transaction_id": "group_2"},
        "currency": "BDT",
        "direction": "INBOUND",
    },
    {
        "rule_id": "brac_v1",
        "provider": "BRAC Bank",
        "sender_pattern": r"^BRACBank$",
        "message_pattern": r"BDT (\d+\.?\d*) credited.*Tran ID:(\w+)",
        "fields": {"amount": "group_1", "transaction_id": "group_2"},
        "currency": "BDT",
        "direction": "INBOUND",
    },
    {
        "rule_id": "city_v1",
        "provider": "City Bank",
        "sender_pattern": r"^CityBank$",
        "message_pattern": r"Received BDT (\d+\.?\d*) from (\d{11}).*Ref (\w+)",
        "fields": {"amount": "group_1", "sender_number": "group_2", "transaction_id": "group_3"},
        "currency": "BDT",
        "direction": "INBOUND",
    },
]


def rand_txn():
    return "TRX" + uuid.uuid4().hex[:10].upper()


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as db:
        # ── Admin ────────────────────────────────────────────────────────────
        admin = User(
            email=settings.ADMIN_EMAIL,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        await db.flush()
        print(f"  ✓ Admin: {admin.email}")

        # ── Global parser rules ──────────────────────────────────────────────
        for rule_data in PARSER_RULES:
            rule = ParserRule(merchant_id=None, enabled=True, **rule_data)
            db.add(rule)
        print(f"  ✓ {len(PARSER_RULES)} parser rules")

        # ── Merchants ────────────────────────────────────────────────────────
        merchants = []
        raw_api_keys = []
        for i in range(2):
            u = User(
                email=f"merchant{i+1}@shuvopay.dev",
                password_hash=hash_password("merchant123!"),
                role="merchant",
                is_active=True,
            )
            db.add(u)
            await db.flush()

            m = Merchant(
                user_id=u.id,
                name=f"Demo Merchant {i+1}",
                webhook_url=f"https://example{i+1}.com/webhook",
                is_active=True,
            )
            db.add(m)
            await db.flush()
            merchants.append(m)
            print(f"  ✓ Merchant {i+1}: {u.email}")

            # API key for each merchant
            raw_key, hashed = generate_api_key()
            raw_api_keys.append((i + 1, raw_key))
            api_key = ApiKey(
                merchant_id=m.id,
                key_hash=hashed,
                label="Default key",
                scope="read:invoices,write:invoices",
                is_active=True,
            )
            db.add(api_key)

        # ── Devices (5 total, distributed across merchants) ─────────────────
        devices = []
        raw_device_keys = []
        for i in range(5):
            merchant = merchants[i % 2]
            device = Device(
                merchant_id=merchant.id,
                name=f"Device {i+1}",
                fingerprint=f"fingerprint-seed-{uuid.uuid4().hex}",
                status=random.choice(["online", "offline"]),
                last_seen=datetime.now(timezone.utc) - timedelta(minutes=random.randint(0, 60)),
            )
            db.add(device)
            await db.flush()
            devices.append(device)

            raw_k, hashed_k = generate_device_key()
            raw_device_keys.append((i + 1, raw_k))
            dk = DeviceApiKey(device_id=device.id, key_hash=hashed_k, is_active=True)
            db.add(dk)

        print(f"  ✓ 5 devices created")

        # ── Invoices (30) ────────────────────────────────────────────────────
        invoices = []
        statuses = ["pending"] * 15 + ["paid"] * 10 + ["unmatched"] * 5
        random.shuffle(statuses)
        for i in range(30):
            merchant = random.choice(merchants)
            provider = random.choice(PROVIDERS)
            amt = round(random.uniform(100, 10000), 2)
            status = statuses[i]
            inv = Invoice(
                merchant_id=merchant.id,
                invoice_number=f"INV-SEED-{i+1:04d}",
                amount=amt,
                currency="BDT",
                provider=provider,
                status=status,
                time_window_minutes=30,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=random.randint(1, 48)),
            )
            db.add(inv)
            invoices.append(inv)
        print(f"  ✓ 30 invoices created")

        await db.flush()

        # ── SMS Logs (50) ────────────────────────────────────────────────────
        sms_statuses = ["matched"] * 20 + ["unmatched"] * 20 + ["review_required"] * 10
        random.shuffle(sms_statuses)
        for i in range(50):
            device = random.choice(devices)
            provider = random.choice(PROVIDERS)
            amt = round(random.uniform(100, 10000), 2)
            raw_text = f"You have received Tk {amt} from 01700000001. TrxID {rand_txn()} at ShuvoPay."

            sms = SmsLog(
                device_id=device.id,
                merchant_id=device.merchant_id,
                request_id=str(uuid.uuid4()),
                raw_sms_encrypted=encrypt_text(raw_text),
                provider=provider,
                transaction_id=rand_txn(),
                amount=amt,
                currency="BDT",
                sender_number="01700000001",
                sms_timestamp=datetime.now(timezone.utc) - timedelta(minutes=random.randint(1, 1440)),
                parse_confidence=round(random.uniform(0.7, 1.0), 2),
                status=sms_statuses[i],
            )
            db.add(sms)
        print(f"  ✓ 50 SMS logs created")

        await db.commit()

    print("\n─── Seed Credentials ───────────────────────────────────────")
    print(f"  Admin:      {settings.ADMIN_EMAIL} / {settings.ADMIN_PASSWORD}")
    print(f"  Merchant 1: merchant1@shuvopay.dev / merchant123!")
    print(f"  Merchant 2: merchant2@shuvopay.dev / merchant123!")
    for idx, key in raw_api_keys:
        print(f"  Merchant {idx} API Key: {key}")
    for idx, key in raw_device_keys:
        print(f"  Device {idx} Key: {key}")
    print("────────────────────────────────────────────────────────────")


if __name__ == "__main__":
    print("Seeding database...")
    asyncio.run(seed())
    print("Done.")
