package com.shuvopay.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// ─── Auth ────────────────────────────────────────────────────────────────────

@Serializable
data class LoginRequest(
    val email: String,
    val password: String,
    @SerialName("totp_code") val totpCode: String? = null,
)

@Serializable
data class TokenResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("token_type") val tokenType: String = "bearer",
)

@Serializable
data class TwoFASetupResponse(
    val secret: String,
    @SerialName("qr_uri") val qrUri: String,
)

@Serializable
data class TwoFAVerifyRequest(
    @SerialName("totp_code") val totpCode: String,
)

// ─── Device ──────────────────────────────────────────────────────────────────

@Serializable
data class DeviceRegisterRequest(
    val name: String,
    val fingerprint: String,
    @SerialName("fcm_token") val fcmToken: String? = null,
)

@Serializable
data class DeviceRegisterResponse(
    @SerialName("device_id") val deviceId: String,
    @SerialName("api_key") val apiKey: String,
)

@Serializable
data class ParserRuleDto(
    @SerialName("rule_id") val ruleId: String,
    val provider: String,
    @SerialName("sender_pattern") val senderPattern: String,
    @SerialName("message_pattern") val messagePattern: String,
    val fields: Map<String, String>,
    val currency: String,
    val direction: String,
    val enabled: Boolean,
)

// ─── SMS ─────────────────────────────────────────────────────────────────────

@Serializable
data class SmsReportRequest(
    val provider: String?,
    @SerialName("transaction_id") val transactionId: String?,
    val amount: Double?,
    val currency: String,
    @SerialName("sender_number") val senderNumber: String?,
    @SerialName("sender_name") val senderName: String?,
    @SerialName("receiver_account") val receiverAccount: String?,
    @SerialName("sms_timestamp") val smsTimestamp: String,
    @SerialName("parse_confidence") val parseConfidence: Double,
    @SerialName("raw_sms") val rawSms: String,
)

@Serializable
data class SmsReportResponse(
    @SerialName("sms_id") val smsId: String,
    val status: String,
)

@Serializable
data class SmsBatchRequest(
    val items: List<SmsReportRequest>,
)

@Serializable
data class SmsBatchResponse(
    val accepted: Int,
    @SerialName("sms_ids") val smsIds: List<String>,
)

// ─── Invoice ─────────────────────────────────────────────────────────────────

@Serializable
data class InvoiceDto(
    val id: String,
    @SerialName("invoice_number") val invoiceNumber: String,
    val amount: Double,
    val currency: String,
    val provider: String,
    val status: String,
    @SerialName("expires_at") val expiresAt: String,
    @SerialName("created_at") val createdAt: String,
)
