import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
import pyotp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


# ─── JWT (RS256) ────────────────────────────────────────────────────────────

def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm="RS256")


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
        "jti": secrets.token_urlsafe(32),
    }
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm="RS256")


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.JWT_PUBLIC_KEY,
        algorithms=["RS256"],
        options={"verify_exp": True},
    )


# ─── Password Hashing ───────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ─── Device API Key ─────────────────────────────────────────────────────────

def generate_device_key() -> tuple[str, str]:
    """Returns (raw_key, pbkdf2_hash). Store only the hash."""
    raw = "spd_" + secrets.token_urlsafe(48)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode(), b"shuvopay_device", 200_000)
    return raw, base64.b64encode(dk).decode()


def verify_device_key(raw: str, stored_hash: str) -> bool:
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode(), b"shuvopay_device", 200_000)
    candidate = base64.b64encode(dk).decode()
    return hmac.compare_digest(candidate, stored_hash)


# ─── API Key ────────────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key, sha256_hash). Store only the hash."""
    raw = "spk_" + secrets.token_urlsafe(48)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ─── AES-256-GCM Encryption ─────────────────────────────────────────────────

def _get_aes_key() -> bytes:
    key_hex = settings.AES_ENCRYPTION_KEY
    key_bytes = bytes.fromhex(key_hex)
    if len(key_bytes) != 32:
        raise ValueError("AES_ENCRYPTION_KEY must be exactly 32 bytes (64 hex chars)")
    return key_bytes


def encrypt_text(plaintext: str) -> str:
    """Encrypt with AES-256-GCM. Returns base64(nonce + ciphertext + tag)."""
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_text(ciphertext_b64: str) -> str:
    """Decrypt AES-256-GCM ciphertext (base64 encoded)."""
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(ciphertext_b64)
    nonce, ct = raw[:12], raw[12:]
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")


# ─── TOTP (RFC 6238) ────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=email, issuer_name="ShuvoPay"
    )


def verify_totp(secret: str, token: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(token, valid_window=1)


# ─── Webhook HMAC Signing ───────────────────────────────────────────────────

def sign_webhook_payload(payload: bytes, secret: str) -> str:
    """Returns sha256=<hex_digest>"""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = sign_webhook_payload(payload, secret)
    return hmac.compare_digest(expected, signature)


# ─── Bcrypt for webhook secrets ─────────────────────────────────────────────

def hash_webhook_secret(secret: str) -> str:
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_webhook_secret(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())
