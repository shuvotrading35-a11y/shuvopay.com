package com.shuvopay.data.local.entity

import androidx.room.*
import kotlinx.coroutines.flow.Flow

// ─── Entities ───────────────────────────────────────────────────────────────

@Entity(tableName = "sms_queue")
data class SmsQueueEntity(
    @PrimaryKey val id: String,          // UUID
    val requestId: String,               // For replay protection header
    val rawSmsEncrypted: String,         // AES-256-GCM encrypted
    val provider: String?,
    val transactionId: String?,
    val amount: String?,                 // BigDecimal as String to avoid float
    val currency: String,
    val senderNumber: String?,
    val senderName: String?,
    val receiverAccount: String?,
    val smsTimestampMs: Long,            // epoch millis
    val parseConfidence: Double,
    val status: SmsUploadStatus,         // PENDING | UPLOADING | UPLOADED | FAILED
    val attemptCount: Int = 0,
    val lastAttemptMs: Long? = null,
    val serverSmsId: String? = null,     // returned by backend on success
    val createdAtMs: Long,
)

enum class SmsUploadStatus { PENDING, UPLOADING, UPLOADED, FAILED }

@Entity(tableName = "parser_rules")
data class ParserRuleEntity(
    @PrimaryKey val ruleId: String,
    val provider: String,
    val senderPattern: String,
    val messagePattern: String,
    @TypeConverters(RoomConverters::class)
    val fields: Map<String, String>,     // {"amount":"group_1", ...}
    val currency: String,
    val direction: String,
    val enabled: Boolean,
    val fetchedAtMs: Long,
    val etag: String?,
)

@Entity(tableName = "device_info")
data class DeviceInfoEntity(
    @PrimaryKey val id: Int = 1,         // Singleton row
    val deviceId: String?,
    val merchantId: String?,
    val deviceName: String?,
    val apiKey: String?,                 // stored encrypted via EncryptedSharedPreferences
    val serverUrl: String,
    val fcmToken: String?,
    val lastSyncMs: Long?,
)


// ─── TypeConverters ──────────────────────────────────────────────────────────

class RoomConverters {
    @TypeConverter
    fun fromMap(map: Map<String, String>?): String {
        if (map == null) return "{}"
        return map.entries.joinToString(",", "{", "}") { (k, v) -> "\"$k\":\"$v\"" }
    }

    @TypeConverter
    fun toMap(json: String?): Map<String, String> {
        if (json.isNullOrBlank() || json == "{}") return emptyMap()
        return try {
            json.trim('{', '}').split(",").associate { entry ->
                val (k, v) = entry.split(":").map { it.trim('"') }
                k to v
            }
        } catch (e: Exception) {
            emptyMap()
        }
    }

    @TypeConverter
    fun fromStatus(status: SmsUploadStatus): String = status.name

    @TypeConverter
    fun toStatus(name: String): SmsUploadStatus = SmsUploadStatus.valueOf(name)
}


// ─── DAOs ────────────────────────────────────────────────────────────────────

@Dao
interface SmsQueueDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(sms: SmsQueueEntity)

    @Query("SELECT * FROM sms_queue WHERE status = 'PENDING' ORDER BY createdAtMs ASC LIMIT :limit")
    suspend fun getPending(limit: Int = 50): List<SmsQueueEntity>

    @Query("UPDATE sms_queue SET status = :status, attemptCount = attemptCount + 1, lastAttemptMs = :now WHERE id = :id")
    suspend fun updateStatus(id: String, status: SmsUploadStatus, now: Long = System.currentTimeMillis())

    @Query("UPDATE sms_queue SET status = 'UPLOADED', serverSmsId = :serverId WHERE id = :id")
    suspend fun markUploaded(id: String, serverId: String)

    @Query("SELECT COUNT(*) FROM sms_queue WHERE status = 'PENDING'")
    fun observePendingCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM sms_queue WHERE status = :status")
    suspend fun countByStatus(status: SmsUploadStatus): Int

    @Query("SELECT * FROM sms_queue ORDER BY createdAtMs DESC LIMIT :limit")
    fun observeRecent(limit: Int = 10): Flow<List<SmsQueueEntity>>

    @Query("DELETE FROM sms_queue WHERE status = 'UPLOADED' AND createdAtMs < :beforeMs")
    suspend fun pruneUploaded(beforeMs: Long)
}

@Dao
interface ParserRuleDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(rules: List<ParserRuleEntity>)

    @Query("SELECT * FROM parser_rules WHERE enabled = 1 ORDER BY ruleId ASC")
    suspend fun getEnabledRules(): List<ParserRuleEntity>

    @Query("SELECT MAX(fetchedAtMs) FROM parser_rules")
    suspend fun lastFetchedAt(): Long?

    @Query("SELECT etag FROM parser_rules LIMIT 1")
    suspend fun getCurrentEtag(): String?

    @Query("DELETE FROM parser_rules")
    suspend fun clearAll()
}

@Dao
interface DeviceInfoDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(info: DeviceInfoEntity)

    @Query("SELECT * FROM device_info WHERE id = 1")
    suspend fun get(): DeviceInfoEntity?

    @Query("SELECT * FROM device_info WHERE id = 1")
    fun observe(): Flow<DeviceInfoEntity?>
}


// ─── Database ────────────────────────────────────────────────────────────────

@Database(
    entities = [SmsQueueEntity::class, ParserRuleEntity::class, DeviceInfoEntity::class],
    version = 1,
    exportSchema = true,
)
@TypeConverters(RoomConverters::class)
abstract class AppDatabase : RoomDatabase() {
    abstract fun smsQueueDao(): SmsQueueDao
    abstract fun parserRuleDao(): ParserRuleDao
    abstract fun deviceInfoDao(): DeviceInfoDao
}
