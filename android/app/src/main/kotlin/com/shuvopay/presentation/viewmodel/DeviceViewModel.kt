package com.shuvopay.presentation.viewmodel

import android.content.Context
import android.provider.Settings
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shuvopay.data.remote.api.DeviceApi
import com.shuvopay.data.remote.dto.DeviceRegisterRequest
import com.shuvopay.util.SecurePrefs
import com.shuvopay.worker.SmsUploadWorker
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject

sealed interface DeviceState {
    data object Idle : DeviceState
    data object Registering : DeviceState
    data object Registered : DeviceState
    data class Error(val message: String) : DeviceState
}

@HiltViewModel
class DeviceViewModel @Inject constructor(
    private val deviceApi: DeviceApi,
    private val securePrefs: SecurePrefs,
    @ApplicationContext private val context: Context,
) : ViewModel() {

    private val _state = MutableStateFlow<DeviceState>(DeviceState.Idle)
    val state = _state.asStateFlow()

    fun registerIfNeeded() {
        // Already registered
        if (securePrefs.getDeviceApiKey() != null) {
            _state.value = DeviceState.Registered
            SmsUploadWorker.schedulePeriodicFlush(context)
            return
        }
        register()
    }

    private fun register() {
        viewModelScope.launch {
            _state.value = DeviceState.Registering
            try {
                val token = securePrefs.getAccessToken() ?: run {
                    _state.value = DeviceState.Error("Not authenticated")
                    return@launch
                }
                val androidId = Settings.Secure.getString(
                    context.contentResolver,
                    Settings.Secure.ANDROID_ID
                )
                val response = deviceApi.registerDevice(
                    token = "Bearer $token",
                    body = DeviceRegisterRequest(
                        name = android.os.Build.MODEL,
                        fingerprint = androidId,
                    )
                )
                if (response.isSuccessful) {
                    val body = response.body()!!
                    securePrefs.saveDeviceId(body.deviceId)
                    securePrefs.saveDeviceApiKey(body.apiKey)
                    SmsUploadWorker.schedulePeriodicFlush(context)
                    _state.value = DeviceState.Registered
                    Timber.i("Device registered: ${body.deviceId}")
                } else {
                    _state.value = DeviceState.Error("Registration failed: ${response.code()}")
                    Timber.w("Device registration failed: ${response.code()}")
                }
            } catch (e: Exception) {
                _state.value = DeviceState.Error("Network error: ${e.message}")
                Timber.e(e, "Device registration error")
            }
        }
    }

    fun syncParserRules() {
        viewModelScope.launch {
            try {
                val deviceKey = securePrefs.getDeviceApiKey() ?: return@launch
                val response = deviceApi.getParserRules(deviceKey, null)
                if (response.isSuccessful) {
                    Timber.i("Parser rules synced: ${response.body()?.size} rules")
                }
            } catch (e: Exception) {
                Timber.e(e, "Parser rules sync failed")
            }
        }
    }
}
