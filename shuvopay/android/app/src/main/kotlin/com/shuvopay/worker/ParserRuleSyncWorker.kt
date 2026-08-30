package com.shuvopay.worker

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.*
import com.shuvopay.data.local.entity.AppDatabase
import com.shuvopay.data.local.entity.ParserRuleEntity
import com.shuvopay.data.remote.api.DeviceApi
import com.shuvopay.util.SecurePrefs
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import timber.log.Timber
import java.util.concurrent.TimeUnit

@HiltWorker
class ParserRuleSyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val db: AppDatabase,
    private val deviceApi: DeviceApi,
    private val securePrefs: SecurePrefs,
) : CoroutineWorker(context, params) {

    companion object {
        fun schedulePeriodicSync(context: Context) {
            val request = PeriodicWorkRequestBuilder<ParserRuleSyncWorker>(30, TimeUnit.MINUTES)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                "parser_rule_sync",
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
        }

        fun enqueueOnce(context: Context) {
            val request = OneTimeWorkRequestBuilder<ParserRuleSyncWorker>()
                .setConstraints(
                    Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
                )
                .build()
            WorkManager.getInstance(context).enqueue(request)
        }
    }

    override suspend fun doWork(): Result {
        val deviceKey = securePrefs.getDeviceApiKey() ?: return Result.success()
        val currentEtag = db.parserRuleDao().getCurrentEtag()

        return try {
            val response = deviceApi.getParserRules(
                deviceKey = deviceKey,
                ifNoneMatch = currentEtag,
            )

            when {
                response.code() == 304 -> {
                    Timber.d("ParserRuleSync: rules up to date (ETag match)")
                    Result.success()
                }
                response.isSuccessful -> {
                    val rules = response.body() ?: emptyList()
                    val newEtag = response.headers()["ETag"]
                    val now = System.currentTimeMillis()

                    val entities = rules.map { dto ->
                        ParserRuleEntity(
                            ruleId = dto.ruleId,
                            provider = dto.provider,
                            senderPattern = dto.senderPattern,
                            messagePattern = dto.messagePattern,
                            fields = dto.fields,
                            currency = dto.currency,
                            direction = dto.direction,
                            enabled = dto.enabled,
                            fetchedAtMs = now,
                            etag = newEtag,
                        )
                    }

                    db.parserRuleDao().clearAll()
                    db.parserRuleDao().upsertAll(entities)
                    Timber.i("ParserRuleSync: updated ${entities.size} rules")
                    Result.success()
                }
                else -> {
                    Timber.w("ParserRuleSync: error ${response.code()}")
                    Result.retry()
                }
            }
        } catch (e: Exception) {
            Timber.e(e, "ParserRuleSync: network error")
            Result.retry()
        }
    }
}
