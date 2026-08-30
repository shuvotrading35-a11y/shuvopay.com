package com.shuvopay.worker

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.*
import com.shuvopay.data.local.entity.AppDatabase
import com.shuvopay.data.local.entity.SmsUploadStatus
import com.shuvopay.data.remote.api.SmsApi
import com.shuvopay.data.remote.dto.SmsReportRequest
import com.shuvopay.util.CryptoHelper
import com.shuvopay.util.SecurePrefs
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import timber.log.Timber
import java.math.BigDecimal
import java.time.Instant
import java.util.UUID
import java.util.concurrent.TimeUnit

@HiltWorker
class SmsUploadWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val db: AppDatabase,
    private val smsApi: SmsApi,
    private val cryptoHelper: CryptoHelper,
    private val securePrefs: SecurePrefs,
) : CoroutineWorker(context, params) {

    companion object {
        private const val WORK_NAME = "sms_upload"
        private const val BATCH_SIZE = 10

        /**
         * Enqueue an immediate upload attempt.
         * ExistingWorkPolicy.KEEP means if one is already running, we don't duplicate.
         */
        fun enqueue(context: Context) {
            val request = OneTimeWorkRequestBuilder<SmsUploadWorker>()
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    15,
                    TimeUnit.SECONDS,
                )
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                WORK_NAME,
                ExistingWorkPolicy.KEEP,
                request,
            )
        }

        /** Scheduled periodic flush — every 15 minutes while network available. */
        fun schedulePeriodicFlush(context: Context) {
            val request = PeriodicWorkRequestBuilder<SmsUploadWorker>(15, TimeUnit.MINUTES)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .setInitialDelay(1, TimeUnit.MINUTES)
                .build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                "sms_upload_periodic",
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
        }
    }

    override suspend fun doWork(): Result {
        val deviceKey = securePrefs.getDeviceApiKey()
        if (deviceKey == null) {
            Timber.w("SmsUploadWorker: no device key — skipping")
            return Result.success()
        }

        val pending = db.smsQueueDao().getPending(limit = BATCH_SIZE)
        if (pending.isEmpty()) {
            Timber.d("SmsUploadWorker: nothing to upload")
            return Result.success()
        }

        Timber.i("SmsUploadWorker: uploading ${pending.size} SMS")
        var anyFailed = false

        for (sms in pending) {
            db.smsQueueDao().updateStatus(sms.id, SmsUploadStatus.UPLOADING)

            try {
                val decryptedRaw = cryptoHelper.decrypt(sms.rawSmsEncrypted)
                val request = SmsReportRequest(
                    provider = sms.provider,
                    transactionId = sms.transactionId,
                    amount = sms.amount?.let { BigDecimal(it).toDouble() },
                    currency = sms.currency,
                    senderNumber = sms.senderNumber,
                    senderName = sms.senderName,
                    receiverAccount = sms.receiverAccount,
                    smsTimestamp = Instant.ofEpochMilli(sms.smsTimestampMs).toString(),
                    parseConfidence = sms.parseConfidence,
                    rawSms = decryptedRaw,
                )

                val response = smsApi.reportSms(
                    deviceKey = "Bearer $deviceKey",
                    requestId = sms.requestId,
                    body = request,
                )

                if (response.isSuccessful) {
                    val serverId = response.body()?.smsId ?: ""
                    db.smsQueueDao().markUploaded(sms.id, serverId)
                    Timber.d("SmsUploadWorker: uploaded id=${sms.id} serverId=$serverId")
                } else {
                    val code = response.code()
                    Timber.w("SmsUploadWorker: server error $code for id=${sms.id}")
                    // 409 = duplicate request ID — treat as success
                    if (code == 409) {
                        db.smsQueueDao().markUploaded(sms.id, "duplicate")
                    } else {
                        db.smsQueueDao().updateStatus(sms.id, SmsUploadStatus.FAILED)
                        anyFailed = true
                    }
                }
            } catch (e: Exception) {
                Timber.e(e, "SmsUploadWorker: network error for id=${sms.id}")
                db.smsQueueDao().updateStatus(sms.id, SmsUploadStatus.FAILED)
                anyFailed = true
            }
        }

        // Prune uploaded entries older than 7 days
        val sevenDaysAgo = System.currentTimeMillis() - (7 * 24 * 60 * 60 * 1000L)
        db.smsQueueDao().pruneUploaded(sevenDaysAgo)

        return if (anyFailed) Result.retry() else Result.success()
    }
}
