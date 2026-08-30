package com.shuvopay.presentation.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shuvopay.data.local.entity.AppDatabase
import com.shuvopay.data.local.entity.SmsUploadStatus
import com.shuvopay.data.remote.api.DeviceApi
import com.shuvopay.domain.model.DashboardStats
import com.shuvopay.domain.model.DeviceStatus
import com.shuvopay.util.SecurePrefs
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.Instant
import javax.inject.Inject

// ─── MVI State ───────────────────────────────────────────────────────────────

sealed interface DashboardUiState {
    data object Loading : DashboardUiState
    data class Success(val stats: DashboardStats) : DashboardUiState
    data class Error(val message: String) : DashboardUiState
}

sealed interface DashboardIntent {
    data object Refresh : DashboardIntent
    data object ForceSync : DashboardIntent
    data object TestConnection : DashboardIntent
}

// ─── ViewModel ───────────────────────────────────────────────────────────────

@HiltViewModel
class DashboardViewModel @Inject constructor(
    private val db: AppDatabase,
    private val deviceApi: DeviceApi,
    private val securePrefs: SecurePrefs,
) : ViewModel() {

    private val _uiState = MutableStateFlow<DashboardUiState>(DashboardUiState.Loading)
    val uiState: StateFlow<DashboardUiState> = _uiState.asStateFlow()

    private val _pingLatencyMs = MutableStateFlow<Long?>(null)
    val pingLatencyMs: StateFlow<Long?> = _pingLatencyMs.asStateFlow()

    val queueDepth: Flow<Int> = db.smsQueueDao().observePendingCount()

    val recentSms = db.smsQueueDao().observeRecent(10)

    init {
        loadStats()
    }

    fun onIntent(intent: DashboardIntent) {
        when (intent) {
            DashboardIntent.Refresh -> loadStats()
            DashboardIntent.ForceSync -> forceSync()
            DashboardIntent.TestConnection -> testConnection()
        }
    }

    private fun loadStats() {
        viewModelScope.launch {
            _uiState.value = DashboardUiState.Loading
            try {
                val pending = db.smsQueueDao().countByStatus(SmsUploadStatus.PENDING)
                val uploaded = db.smsQueueDao().countByStatus(SmsUploadStatus.UPLOADED)
                val failed = db.smsQueueDao().countByStatus(SmsUploadStatus.FAILED)
                val uploading = db.smsQueueDao().countByStatus(SmsUploadStatus.UPLOADING)

                val today = Instant.now().toEpochMilli() - (24 * 60 * 60 * 1000L)

                _uiState.value = DashboardUiState.Success(
                    stats = DashboardStats(
                        todayReceived = pending + uploaded + failed + uploading,
                        todayMatched = uploaded,
                        todayFailed = failed,
                        todayPending = pending,
                        queueDepth = pending,
                        deviceStatus = DeviceStatus.ONLINE,
                        lastSyncAt = securePrefs.getDeviceId()?.let { Instant.now() },
                    )
                )
            } catch (e: Exception) {
                Timber.e(e, "DashboardViewModel: loadStats failed")
                _uiState.value = DashboardUiState.Error(e.message ?: "Unknown error")
            }
        }
    }

    private fun forceSync() {
        viewModelScope.launch {
            try {
                // Trigger immediate upload
                com.shuvopay.worker.SmsUploadWorker.enqueue(
                    /* context injected via application */ TODO()
                )
                Timber.i("DashboardViewModel: force sync triggered")
            } catch (e: Exception) {
                Timber.e(e, "DashboardViewModel: force sync failed")
            }
        }
    }

    private fun testConnection() {
        viewModelScope.launch {
            val start = System.currentTimeMillis()
            try {
                val deviceKey = securePrefs.getDeviceApiKey() ?: return@launch
                val resp = deviceApi.heartbeat(deviceKey)
                _pingLatencyMs.value = System.currentTimeMillis() - start
                Timber.d("Ping: ${_pingLatencyMs.value}ms status=${resp.code()}")
            } catch (e: Exception) {
                _pingLatencyMs.value = null
                Timber.e(e, "Ping failed")
            }
        }
    }
}
