package com.shuvopay.receiver

import android.app.*
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.provider.Telephony
import androidx.core.app.NotificationCompat
import com.shuvopay.R
import com.shuvopay.data.local.entity.AppDatabase
import com.shuvopay.data.local.entity.SmsQueueEntity
import com.shuvopay.data.local.entity.SmsUploadStatus
import com.shuvopay.parser.SmsParserEngine
import com.shuvopay.util.CryptoHelper
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.Instant
import java.util.UUID
import javax.inject.Inject

/**
 * SmsReceiver — registered for SMS_RECEIVED broadcast.
 *
 * IMPORTANT: This receiver reads only SMS delivered to THIS device's SIM.
 * It does NOT access messages from other devices, contacts, or stored SMS history.
 *
 * On receipt:
 *  1. Hands off to SmsProcessingService (ForegroundService) immediately
 *  2. Service parses + encrypts + stores in Room
 *  3. WorkManager handles upload with retry
 */
@AndroidEntryPoint
class SmsReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val serviceIntent = Intent(context, SmsProcessingService::class.java).apply {
            putExtras(intent)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(serviceIntent)
        } else {
            context.startService(serviceIntent)
        }
    }
}


/**
 * SmsProcessingService — Foreground service for reliable background SMS processing.
 *
 * A persistent notification is ALWAYS shown while this service is active,
 * informing the user that SMS monitoring is running. This is required by
 * Android OS and is non-dismissible while the service runs.
 *
 * Note on OEM restrictions:
 *   - Xiaomi/MIUI: User must enable "Autostart" in Security app
 *   - Samsung OneUI: Battery optimization must be disabled for this app
 *   - Oppo/ColorOS: App must be whitelisted in Battery settings
 *   The app shows warnings and deep-links to these settings where needed.
 */
@AndroidEntryPoint
class SmsProcessingService : Service() {

    @Inject lateinit var parserEngine: SmsParserEngine
    @Inject lateinit var db: AppDatabase
    @Inject lateinit var cryptoHelper: CryptoHelper

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    companion object {
        const val NOTIFICATION_ID = 1001
        const val CHANNEL_ID = "sms_monitoring"
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        intent?.let { processIntent(it) }
        return START_STICKY   // restart if killed
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun processIntent(intent: Intent) {
        val pdus = intent.extras?.get("pdus") as? Array<*> ?: return
        val format = intent.extras?.getString("format")

        serviceScope.launch {
            try {
                val (sender, body) = parserEngine.extractFromPdus(pdus, format)
                if (sender.isEmpty() || body.isEmpty()) return@launch

                Timber.d("SMS received from '$sender', length=${body.length}")

                val rules = db.parserRuleDao().getEnabledRules()
                val parsed = parserEngine.parse(sender, body, Instant.now(), rules)

                // Encrypt raw SMS body before storage (AES-256-GCM)
                val encryptedRaw = cryptoHelper.encrypt(body)

                val queueEntry = SmsQueueEntity(
                    id = UUID.randomUUID().toString(),
                    requestId = UUID.randomUUID().toString(),
                    rawSmsEncrypted = encryptedRaw,
                    provider = parsed?.provider,
                    transactionId = parsed?.transactionId,
                    amount = parsed?.amount?.toPlainString(),
                    currency = parsed?.currency ?: "BDT",
                    senderNumber = parsed?.senderNumber ?: sender,
                    senderName = parsed?.senderName,
                    receiverAccount = parsed?.receiverAccount,
                    smsTimestampMs = Instant.now().toEpochMilli(),
                    parseConfidence = parsed?.parseConfidence ?: 0.0,
                    status = SmsUploadStatus.PENDING,
                    createdAtMs = System.currentTimeMillis(),
                )

                db.smsQueueDao().insert(queueEntry)
                Timber.i("SMS queued id=${queueEntry.id} provider=${queueEntry.provider} confidence=${queueEntry.parseConfidence}")

                // Trigger upload worker immediately
                com.shuvopay.worker.SmsUploadWorker.enqueue(applicationContext)
            } catch (e: Exception) {
                Timber.e(e, "Failed to process SMS")
            }
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "SMS Payment Monitoring",
                NotificationManager.IMPORTANCE_LOW,  // silent — not intrusive
            ).apply {
                description = "ShuvoPay is monitoring incoming payment SMS to verify transactions"
                setShowBadge(false)
            }
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        val stopIntent = PendingIntent.getService(
            this, 0,
            Intent(this, SmsProcessingService::class.java).apply { action = "STOP" },
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("ShuvoPay Active")
            .setContentText("Monitoring incoming payment SMS")
            .setSmallIcon(R.drawable.ic_notification)
            .setOngoing(true)                    // non-dismissible
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .addAction(0, "Stop Monitoring", stopIntent)
            .build()
    }
}
