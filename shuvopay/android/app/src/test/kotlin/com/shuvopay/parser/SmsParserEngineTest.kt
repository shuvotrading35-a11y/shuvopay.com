package com.shuvopay.parser

import com.shuvopay.data.local.entity.ParserRuleEntity
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.MethodSource
import java.time.Instant

class SmsParserEngineTest {

    private val engine = SmsParserEngine()

    // ── Parser Rules ──────────────────────────────────────────────────────────

    private val bkashRule = ParserRuleEntity(
        ruleId = "bkash_v3",
        provider = "bKash",
        senderPattern = """^bKash$""",
        messagePattern = """You have received Tk (\d+\.?\d*) from (\d{11})\..*TrxID (\w+)""",
        fields = mapOf("amount" to "group_1", "sender_number" to "group_2", "transaction_id" to "group_3"),
        currency = "BDT",
        direction = "INBOUND",
        enabled = true,
        fetchedAtMs = System.currentTimeMillis(),
        etag = null,
    )

    private val nagadRule = ParserRuleEntity(
        ruleId = "nagad_v2",
        provider = "Nagad",
        senderPattern = """^Nagad$""",
        messagePattern = """Apnar Nagad Account-e Tk\.(\d+\.?\d*) jama hoyeche\..*TrxID:(\w+)""",
        fields = mapOf("amount" to "group_1", "transaction_id" to "group_2"),
        currency = "BDT",
        direction = "INBOUND",
        enabled = true,
        fetchedAtMs = System.currentTimeMillis(),
        etag = null,
    )

    private val rocketRule = ParserRuleEntity(
        ruleId = "rocket_v2",
        provider = "Rocket",
        senderPattern = """^DBBLMFS$""",
        messagePattern = """Tk\.(\d+\.?\d*) received from (\d{11})\. TxnID:(\w+)""",
        fields = mapOf("amount" to "group_1", "sender_number" to "group_2", "transaction_id" to "group_3"),
        currency = "BDT",
        direction = "INBOUND",
        enabled = true,
        fetchedAtMs = System.currentTimeMillis(),
        etag = null,
    )

    private val allRules = listOf(bkashRule, nagadRule, rocketRule)

    // ── bKash Tests ──────────────────────────────────────────────────────────

    @Test
    fun `bKash standard message parsed correctly`() {
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 500 from 01712345678. TrxID ABC123456 at bKash.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        assertEquals("bKash", result!!.provider)
        assertEquals("500", result.amount?.toPlainString())
        assertEquals("01712345678", result.senderNumber)
        assertEquals("ABC123456", result.transactionId)
        assertEquals("BDT", result.currency)
    }

    @Test
    fun `bKash decimal amount parsed correctly`() {
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 1250.75 from 01898765432. TrxID XYZ9876543 confirmed.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        assertEquals("1250.75", result!!.amount?.toPlainString())
    }

    @Test
    fun `bKash large amount parsed without float precision error`() {
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 99999.99 from 01700000001. TrxID BIG123456.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        // BigDecimal must preserve exact value — no float rounding
        assertEquals("99999.99", result!!.amount?.toPlainString())
    }

    @Test
    fun `bKash message with extra text still parsed`() {
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 300 from 01600123456. Fee: 0 Tk. TrxID QWE789012 Balance: 5000 Tk.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        assertEquals("QWE789012", result!!.transactionId)
    }

    @Test
    fun `bKash sender case insensitive match`() {
        val result = engine.parse(
            sender = "BKASH",
            rawBody = "You have received Tk 100 from 01800000000. TrxID PQR111222.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
    }

    // ── Nagad Tests ──────────────────────────────────────────────────────────

    @Test
    fun `Nagad standard message parsed correctly`() {
        val result = engine.parse(
            sender = "Nagad",
            rawBody = "Apnar Nagad Account-e Tk.750 jama hoyeche. Cash In. TrxID:NG001234567.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        assertEquals("Nagad", result!!.provider)
        assertEquals("750", result.amount?.toPlainString())
        assertEquals("NG001234567", result.transactionId)
    }

    @Test
    fun `Nagad decimal amount`() {
        val result = engine.parse(
            sender = "Nagad",
            rawBody = "Apnar Nagad Account-e Tk.4500.50 jama hoyeche. TrxID:NGC999000111.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        assertEquals("4500.50", result!!.amount?.toPlainString())
    }

    // ── Rocket Tests ─────────────────────────────────────────────────────────

    @Test
    fun `Rocket standard message parsed correctly`() {
        val result = engine.parse(
            sender = "DBBLMFS",
            rawBody = "Tk.500 received from 01812345678. TxnID:RCK001234.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        assertEquals("Rocket", result!!.provider)
        assertEquals("500", result.amount?.toPlainString())
        assertEquals("01812345678", result.senderNumber)
        assertEquals("RCK001234", result.transactionId)
    }

    // ── No Match Tests ───────────────────────────────────────────────────────

    @Test
    fun `OTP SMS returns null`() {
        val result = engine.parse(
            sender = "BankOTP",
            rawBody = "Your OTP is 123456. Valid for 5 minutes. Do not share.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNull(result)
    }

    @Test
    fun `promotional SMS returns null`() {
        val result = engine.parse(
            sender = "MarketingCo",
            rawBody = "Get 50% off your next purchase! Visit our website.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNull(result)
    }

    @Test
    fun `wrong sender for bKash returns null`() {
        val result = engine.parse(
            sender = "NotBkash",
            rawBody = "You have received Tk 500 from 01712345678. TrxID ABC123456.",
            receivedAt = Instant.now(),
            rules = listOf(bkashRule),
        )
        assertNull(result)
    }

    @Test
    fun `disabled rule is not applied`() {
        val disabledRule = bkashRule.copy(enabled = false)
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 500 from 01712345678. TrxID ABC123456.",
            receivedAt = Instant.now(),
            rules = listOf(disabledRule),
        )
        assertNull(result)
    }

    @Test
    fun `empty rules list returns null`() {
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 500 from 01712345678. TrxID ABC123456.",
            receivedAt = Instant.now(),
            rules = emptyList(),
        )
        assertNull(result)
    }

    // ── Confidence Tests ─────────────────────────────────────────────────────

    @Test
    fun `fully matched SMS has high confidence`() {
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 500 from 01712345678. TrxID ABC123456.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        assertTrue(result!!.parseConfidence >= 0.9, "Expected confidence ≥ 0.9, got ${result.parseConfidence}")
    }

    @Test
    fun `confidence is between 0 and 1`() {
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 500 from 01712345678. TrxID ABC123456.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        if (result != null) {
            assertTrue(result.parseConfidence in 0.0..1.0)
        }
    }

    // ── SMS Timestamp Tests ───────────────────────────────────────────────────

    @Test
    fun `sms timestamp is device receive time not parsed from body`() {
        val before = Instant.now()
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 500 from 01712345678. TrxID ABC123456 on 2020-01-01.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        val after = Instant.now()
        assertNotNull(result)
        // Timestamp must be device receive time, NOT "2020-01-01" from body
        assertTrue(result!!.smsTimestamp >= before)
        assertTrue(result.smsTimestamp <= after)
    }

    // ── Multi-part SMS Tests ──────────────────────────────────────────────────

    @Test
    fun `raw sms field is preserved exactly`() {
        val rawBody = "You have received Tk 500 from 01712345678. TrxID ABC123456 at bKash."
        val result = engine.parse(
            sender = "bKash",
            rawBody = rawBody,
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        assertEquals(rawBody, result!!.rawSms)
    }

    @Test
    fun `rule id is recorded in result`() {
        val result = engine.parse(
            sender = "bKash",
            rawBody = "You have received Tk 500 from 01712345678. TrxID ABC123456.",
            receivedAt = Instant.now(),
            rules = allRules,
        )
        assertNotNull(result)
        assertEquals("bkash_v3", result!!.ruleId)
    }
}
