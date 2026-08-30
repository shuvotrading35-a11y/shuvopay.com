package com.shuvopay.parser

import android.telephony.SmsMessage
import com.shuvopay.data.local.entity.ParserRuleEntity
import com.shuvopay.domain.model.ParsedSms
import timber.log.Timber
import java.math.BigDecimal
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

/**
 * SmsParserEngine
 *
 * Rules are fetched from the backend and cached in Room.
 * Each rule is a JSON-configurable regex with named field groups.
 *
 * Parse confidence is 0.0–1.0 based on fields successfully extracted.
 * Uses BigDecimal for amount to avoid float precision issues.
 */
@Singleton
class SmsParserEngine @Inject constructor() {

    /**
     * Attempt to parse [rawBody] from [sender] using all active [rules].
     * Returns null if no rule matches.
     */
    fun parse(
        sender: String,
        rawBody: String,
        receivedAt: Instant,
        rules: List<ParserRuleEntity>,
    ): ParsedSms? {
        val enabledRules = rules.filter { it.enabled }

        for (rule in enabledRules) {
            try {
                val senderRegex = Regex(rule.senderPattern, RegexOption.IGNORE_CASE)
                if (!senderRegex.containsMatchIn(sender)) continue

                val msgRegex = Regex(rule.messagePattern, RegexOption.DOT_MATCHES_ALL)
                val match = msgRegex.find(rawBody) ?: continue

                val groups = match.groupValues // index 0 = full, 1+ = capture groups
                val fieldMap = rule.fields     // e.g. {"amount":"group_1","transaction_id":"group_3"}

                val extracted = mutableMapOf<String, String>()
                for ((fieldName, groupRef) in fieldMap) {
                    val idx = groupRef.removePrefix("group_").toIntOrNull() ?: continue
                    val value = groups.getOrNull(idx)?.trim()
                    if (!value.isNullOrEmpty()) {
                        extracted[fieldName] = value
                    }
                }

                val confidence = calculateConfidence(extracted, fieldMap.keys.toSet())

                val amount = extracted["amount"]?.let { rawAmt ->
                    try {
                        BigDecimal(rawAmt.replace(",", ""))
                    } catch (e: NumberFormatException) {
                        Timber.w("Parser: failed to parse amount '$rawAmt' for rule ${rule.ruleId}")
                        null
                    }
                }

                Timber.d("Parser: matched rule=${rule.ruleId} provider=${rule.provider} confidence=$confidence")

                return ParsedSms(
                    provider = rule.provider,
                    transactionId = extracted["transaction_id"],
                    amount = amount,
                    currency = rule.currency,
                    senderNumber = extracted["sender_number"],
                    senderName = extracted["sender_name"],
                    receiverAccount = extracted["receiver_account"],
                    smsTimestamp = receivedAt,
                    rawSms = rawBody,
                    parseConfidence = confidence,
                    ruleId = rule.ruleId,
                )
            } catch (e: Exception) {
                Timber.e(e, "Parser: exception evaluating rule ${rule.ruleId}")
            }
        }

        Timber.d("Parser: no rule matched sender='$sender'")
        return null
    }

    /**
     * Score = (successfully extracted required fields) / (total declared fields)
     * Bonus 0.1 if transactionId is present (high-value field).
     */
    private fun calculateConfidence(
        extracted: Map<String, String>,
        declaredFields: Set<String>,
    ): Double {
        if (declaredFields.isEmpty()) return 0.0
        val matched = extracted.keys.intersect(declaredFields).size.toDouble()
        val base = matched / declaredFields.size.toDouble()
        val txnBonus = if (extracted.containsKey("transaction_id")) 0.0 else 0.0
        return (base + txnBonus).coerceIn(0.0, 1.0)
    }

    /**
     * Parse raw PDU bytes from BroadcastReceiver extras into individual SmsMessage objects.
     * Handles multi-part SMS correctly.
     */
    fun extractFromPdus(pdus: Array<*>, format: String?): Pair<String, String> {
        val messages = pdus.mapNotNull { pdu ->
            if (pdu is ByteArray) {
                if (format != null) {
                    SmsMessage.createFromPdu(pdu, format)
                } else {
                    @Suppress("DEPRECATION")
                    SmsMessage.createFromPdu(pdu)
                }
            } else null
        }
        val sender = messages.firstOrNull()?.originatingAddress ?: ""
        val body = messages.joinToString("") { it.messageBody ?: "" }
        return sender to body
    }
}
