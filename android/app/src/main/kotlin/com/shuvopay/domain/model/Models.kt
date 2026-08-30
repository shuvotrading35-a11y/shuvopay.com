package com.shuvopay.domain.model

import java.math.BigDecimal
import java.time.Instant

data class ParsedSms(
    val provider: String,
    val transactionId: String?,
    val amount: BigDecimal?,
    val currency: String,
    val senderNumber: String?,
    val senderName: String?,
    val receiverAccount: String?,
    val smsTimestamp: Instant,
    val rawSms: String,
    val parseConfidence: Double,
    val ruleId: String,
)

data class DeviceInfo(
    val deviceId: String,
    val merchantId: String,
    val name: String,
    val status: DeviceStatus,
    val lastSeen: Instant?,
    val queueDepth: Int,
)

enum class DeviceStatus { ONLINE, OFFLINE, SYNCING }

data class SmsQueueStats(
    val pending: Int,
    val uploading: Int,
    val uploaded: Int,
    val failed: Int,
)

data class DashboardStats(
    val todayReceived: Int,
    val todayMatched: Int,
    val todayFailed: Int,
    val todayPending: Int,
    val queueDepth: Int,
    val deviceStatus: DeviceStatus,
    val lastSyncAt: Instant?,
)
