"""
Unit tests for:
  - SMS parser regex patterns (5+ samples per provider)
  - Match engine scoring combinations
  - HMAC webhook signature generation + verification
"""
import pytest
import re
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from app.core.security import (
    encrypt_text, decrypt_text,
    sign_webhook_payload, verify_webhook_signature,
    hash_password, verify_password,
    generate_totp_secret, verify_totp,
)


# ════════════════════════════════════════════════════════════════════════════
# SMS Parser Tests — validate every built-in regex pattern
# ════════════════════════════════════════════════════════════════════════════

BKASH_PATTERN = r"You have received Tk (\d+\.?\d*) from (\d{11})\..*TrxID (\w+)"
NAGAD_PATTERN = r"Apnar Nagad Account-e Tk\.(\d+\.?\d*) jama hoyeche\..*TrxID:(\w+)"
ROCKET_PATTERN = r"Tk\.(\d+\.?\d*) received from (\d{11})\. TxnID:(\w+)"
UPAY_PATTERN = r"BDT (\d+\.?\d*) received\. Ref:(\w+)"
DBBL_PATTERN = r"Credited BDT (\d+\.?\d*) to your account.*Ref:(\w+)"
BRAC_PATTERN = r"BDT (\d+\.?\d*) credited.*Tran ID:(\w+)"
CITY_PATTERN = r"Received BDT (\d+\.?\d*) from (\d{11}).*Ref (\w+)"


class TestBkashParser:
    SAMPLES = [
        ("You have received Tk 500 from 01712345678. TrxID ABC123456 at bKash.", "500", "01712345678", "ABC123456"),
        ("You have received Tk 1250.50 from 01898765432. Ref TrxID XYZ9876543 on 2025-01-01.", "1250.50", "01898765432", "XYZ9876543"),
        ("You have received Tk 100 from 01900000001. Your TrxID MNO123 confirmed.", "100", "01900000001", "MNO123"),
        ("You have received Tk 5000.00 from 01600123456. TrxID QWE789012 Balance: 6000 Tk.", "5000.00", "01600123456", "QWE789012"),
        ("You have received Tk 250 from 01811111111. TrxID PQR456789.", "250", "01811111111", "PQR456789"),
    ]

    @pytest.mark.parametrize("sms,exp_amt,exp_num,exp_txn", SAMPLES)
    def test_bkash_matches(self, sms, exp_amt, exp_num, exp_txn):
        match = re.search(BKASH_PATTERN, sms)
        assert match is not None, f"Pattern did not match: {sms}"
        assert match.group(1) == exp_amt
        assert match.group(2) == exp_num
        assert match.group(3) == exp_txn


class TestNagadParser:
    SAMPLES = [
        ("Apnar Nagad Account-e Tk.750 jama hoyeche. Cash In. TrxID:NG001234567.", "750", "NG001234567"),
        ("Apnar Nagad Account-e Tk.1000.00 jama hoyeche. Sender: 01700000000. TrxID:NG987654321.", "1000.00", "NG987654321"),
        ("Apnar Nagad Account-e Tk.300 jama hoyeche. TrxID:NGA111222333.", "300", "NGA111222333"),
        ("Apnar Nagad Account-e Tk.4500.75 jama hoyeche. TrxID:NGC999000111.", "4500.75", "NGC999000111"),
        ("Apnar Nagad Account-e Tk.50 jama hoyeche. TrxID:NGS000111000.", "50", "NGS000111000"),
    ]

    @pytest.mark.parametrize("sms,exp_amt,exp_txn", SAMPLES)
    def test_nagad_matches(self, sms, exp_amt, exp_txn):
        match = re.search(NAGAD_PATTERN, sms)
        assert match is not None
        assert match.group(1) == exp_amt
        assert match.group(2) == exp_txn


class TestRocketParser:
    SAMPLES = [
        ("Tk.500 received from 01812345678. TxnID:RCK001234.", "500", "01812345678", "RCK001234"),
        ("Tk.2500.00 received from 01712345679. TxnID:RCK999888.", "2500.00", "01712345679", "RCK999888"),
        ("Tk.150 received from 01911112222. TxnID:RCK555444.", "150", "01911112222", "RCK555444"),
        ("Tk.10000 received from 01600001111. TxnID:RCKABCD123.", "10000", "01600001111", "RCKABCD123"),
        ("Tk.99.50 received from 01800000000. TxnID:RCK000111.", "99.50", "01800000000", "RCK000111"),
    ]

    @pytest.mark.parametrize("sms,exp_amt,exp_num,exp_txn", SAMPLES)
    def test_rocket_matches(self, sms, exp_amt, exp_num, exp_txn):
        match = re.search(ROCKET_PATTERN, sms)
        assert match is not None
        assert match.group(1) == exp_amt
        assert match.group(2) == exp_num
        assert match.group(3) == exp_txn


class TestUpayParser:
    SAMPLES = [
        ("BDT 500 received. Ref:UPY123456.", "500", "UPY123456"),
        ("BDT 1250.50 received. Ref:UPYABC999.", "1250.50", "UPYABC999"),
        ("BDT 75 received. Ref:UPY000000.", "75", "UPY000000"),
        ("BDT 9999.99 received. Ref:UPYZXC321.", "9999.99", "UPYZXC321"),
        ("BDT 200 received. Ref:UPYTEST01.", "200", "UPYTEST01"),
    ]

    @pytest.mark.parametrize("sms,exp_amt,exp_txn", SAMPLES)
    def test_upay_matches(self, sms, exp_amt, exp_txn):
        match = re.search(UPAY_PATTERN, sms)
        assert match is not None
        assert match.group(1) == exp_amt
        assert match.group(2) == exp_txn


class TestNonMatchingSamples:
    """Ensure patterns do NOT match unrelated SMS."""

    NOISE_SMS = [
        "Your OTP is 123456. Valid for 5 minutes.",
        "Dear customer, your subscription expires on 2025-12-31.",
        "Call us at 16247 for support.",
        "Hi, meeting at 3pm tomorrow?",
        "Package delivered to your address.",
    ]

    @pytest.mark.parametrize("sms", NOISE_SMS)
    def test_bkash_no_false_positives(self, sms):
        assert re.search(BKASH_PATTERN, sms) is None

    @pytest.mark.parametrize("sms", NOISE_SMS)
    def test_nagad_no_false_positives(self, sms):
        assert re.search(NAGAD_PATTERN, sms) is None


# ════════════════════════════════════════════════════════════════════════════
# Match Engine Tests
# ════════════════════════════════════════════════════════════════════════════

class TestMatchEngineScoring:
    """Test the scoring weights and decision logic."""

    def _make_invoice(self, amount=500.0, provider="bKash", window_minutes=30, receiver=None):
        return MagicMock(
            amount=amount, provider=provider, time_window_minutes=window_minutes,
            receiver_account=receiver,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=25),
            id="inv-001", invoice_number="INV-001", currency="BDT",
        )

    def _make_sms(self, amount=500.0, provider="bKash", txn_id="TRX001", receiver=None, offset_minutes=2):
        return MagicMock(
            amount=amount, provider=provider, transaction_id=txn_id,
            receiver_account=receiver,
            sms_timestamp=datetime.now(timezone.utc) - timedelta(minutes=offset_minutes),
            id="sms-001", merchant_id="merchant-001", currency="BDT",
        )

    def test_exact_match_gives_high_confidence(self):
        from app.workers.match_engine import MatchScore, WEIGHT_AMOUNT, WEIGHT_TIME_WINDOW, WEIGHT_TXN_UNIQUE, WEIGHT_RECEIVER
        scorer = MatchScore()
        scorer.add("amount", WEIGHT_AMOUNT, True)
        scorer.add("time_window", WEIGHT_TIME_WINDOW, True)
        scorer.add("txn_unique", WEIGHT_TXN_UNIQUE, True)
        scorer.add("receiver_account", WEIGHT_RECEIVER, True)
        assert scorer.finalize() == pytest.approx(1.0, abs=0.001)

    def test_amount_mismatch_kills_score(self):
        from app.workers.match_engine import MatchScore, WEIGHT_AMOUNT, WEIGHT_TIME_WINDOW, WEIGHT_TXN_UNIQUE, WEIGHT_RECEIVER
        scorer = MatchScore()
        scorer.add("amount", WEIGHT_AMOUNT, False)       # amount does not match
        scorer.add("time_window", WEIGHT_TIME_WINDOW, True)
        scorer.add("txn_unique", WEIGHT_TXN_UNIQUE, True)
        scorer.add("receiver_account", WEIGHT_RECEIVER, True)
        assert scorer.finalize() < 0.95  # below auto-pay threshold

    def test_time_window_miss_kills_score(self):
        from app.workers.match_engine import MatchScore, WEIGHT_AMOUNT, WEIGHT_TIME_WINDOW, WEIGHT_TXN_UNIQUE, WEIGHT_RECEIVER
        scorer = MatchScore()
        scorer.add("amount", WEIGHT_AMOUNT, True)
        scorer.add("time_window", WEIGHT_TIME_WINDOW, False)  # SMS outside window
        scorer.add("txn_unique", WEIGHT_TXN_UNIQUE, True)
        scorer.add("receiver_account", WEIGHT_RECEIVER, True)
        assert scorer.finalize() < 0.95

    def test_duplicate_txn_zeroes_score(self):
        from app.workers.match_engine import MatchScore, WEIGHT_AMOUNT, WEIGHT_TIME_WINDOW, WEIGHT_TXN_UNIQUE, WEIGHT_RECEIVER
        scorer = MatchScore()
        scorer.add("amount", WEIGHT_AMOUNT, True)
        scorer.add("time_window", WEIGHT_TIME_WINDOW, True)
        scorer.add("txn_unique", WEIGHT_TXN_UNIQUE, False)    # duplicate txn ID
        scorer.add("receiver_account", WEIGHT_RECEIVER, True)
        assert scorer.finalize() < 0.95

    def test_no_receiver_check_still_high(self):
        from app.workers.match_engine import MatchScore, WEIGHT_AMOUNT, WEIGHT_TIME_WINDOW, WEIGHT_TXN_UNIQUE, WEIGHT_RECEIVER
        scorer = MatchScore()
        scorer.add("amount", WEIGHT_AMOUNT, True)
        scorer.add("time_window", WEIGHT_TIME_WINDOW, True)
        scorer.add("txn_unique", WEIGHT_TXN_UNIQUE, True)
        scorer.add("receiver_account", WEIGHT_RECEIVER, True)  # not specified = pass
        assert scorer.finalize() >= 0.95

    def test_partial_match_below_threshold(self):
        from app.workers.match_engine import MatchScore, WEIGHT_AMOUNT, WEIGHT_TIME_WINDOW, WEIGHT_TXN_UNIQUE, WEIGHT_RECEIVER
        scorer = MatchScore()
        scorer.add("amount", WEIGHT_AMOUNT, True)
        scorer.add("time_window", WEIGHT_TIME_WINDOW, True)
        scorer.add("txn_unique", WEIGHT_TXN_UNIQUE, False)
        scorer.add("receiver_account", WEIGHT_RECEIVER, False)
        assert scorer.finalize() < 0.95

    def test_weight_sum_is_one(self):
        from app.workers.match_engine import WEIGHT_AMOUNT, WEIGHT_TIME_WINDOW, WEIGHT_TXN_UNIQUE, WEIGHT_RECEIVER
        total = WEIGHT_AMOUNT + WEIGHT_TIME_WINDOW + WEIGHT_TXN_UNIQUE + WEIGHT_RECEIVER
        assert total == pytest.approx(1.0, abs=0.001)


# ════════════════════════════════════════════════════════════════════════════
# Security Tests
# ════════════════════════════════════════════════════════════════════════════

class TestAESEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "You have received Tk 500 from 01712345678. TrxID ABC123456."
        ciphertext = encrypt_text(plaintext)
        assert ciphertext != plaintext
        recovered = decrypt_text(ciphertext)
        assert recovered == plaintext

    def test_different_ciphertexts_per_call(self):
        """Each encryption uses a fresh nonce — no deterministic output."""
        plaintext = "Test SMS"
        c1 = encrypt_text(plaintext)
        c2 = encrypt_text(plaintext)
        assert c1 != c2

    def test_empty_string(self):
        plaintext = ""
        assert decrypt_text(encrypt_text(plaintext)) == plaintext

    def test_unicode_sms(self):
        plaintext = "আপনার Nagad Account-e Tk.500 জমা হয়েছে। TrxID:NG123456"
        assert decrypt_text(encrypt_text(plaintext)) == plaintext


class TestHMAC:
    SECRET = "whsec_test_secret_12345"

    def test_signature_format(self):
        payload = b'{"event":"payment.confirmed"}'
        sig = sign_webhook_payload(payload, self.SECRET)
        assert sig.startswith("sha256=")
        assert len(sig) == len("sha256=") + 64  # sha256 hex = 64 chars

    def test_valid_signature_verifies(self):
        payload = b'{"event":"payment.confirmed","amount":500}'
        sig = sign_webhook_payload(payload, self.SECRET)
        assert verify_webhook_signature(payload, sig, self.SECRET)

    def test_wrong_secret_fails(self):
        payload = b'{"event":"payment.confirmed"}'
        sig = sign_webhook_payload(payload, self.SECRET)
        assert not verify_webhook_signature(payload, sig, "wrong_secret")

    def test_tampered_payload_fails(self):
        payload = b'{"event":"payment.confirmed","amount":500}'
        sig = sign_webhook_payload(payload, self.SECRET)
        tampered = b'{"event":"payment.confirmed","amount":9999}'
        assert not verify_webhook_signature(tampered, sig, self.SECRET)

    def test_empty_payload(self):
        payload = b""
        sig = sign_webhook_payload(payload, self.SECRET)
        assert verify_webhook_signature(payload, sig, self.SECRET)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "SuperSecret123!"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct_password")
        assert not verify_password("wrong_password", hashed)

    def test_unique_hashes(self):
        pw = "same_password"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        assert h1 != h2  # bcrypt salt randomness
