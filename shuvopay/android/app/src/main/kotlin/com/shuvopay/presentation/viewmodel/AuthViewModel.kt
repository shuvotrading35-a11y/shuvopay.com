package com.shuvopay.presentation.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shuvopay.data.remote.api.AuthApi
import com.shuvopay.data.remote.dto.LoginRequest
import com.shuvopay.util.SecurePrefs
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject

sealed interface AuthUiState {
    data object Idle : AuthUiState
    data object Loading : AuthUiState
    data object Requires2FA : AuthUiState
    data object LoggedIn : AuthUiState
    data class Error(val message: String) : AuthUiState
}

@HiltViewModel
class AuthViewModel @Inject constructor(
    private val authApi: AuthApi,
    private val securePrefs: SecurePrefs,
) : ViewModel() {

    private val _uiState = MutableStateFlow<AuthUiState>(AuthUiState.Idle)
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    fun login(email: String, password: String, totpCode: String?) {
        viewModelScope.launch {
            _uiState.value = AuthUiState.Loading
            try {
                val response = authApi.login(
                    LoginRequest(email = email, password = password, totpCode = totpCode)
                )
                when {
                    response.isSuccessful -> {
                        val token = response.body()?.accessToken
                        if (token != null) {
                            securePrefs.saveAccessToken(token)
                            _uiState.value = AuthUiState.LoggedIn
                        } else {
                            _uiState.value = AuthUiState.Error("No token received")
                        }
                    }
                    response.code() == 401 && totpCode == null -> {
                        // Server may be asking for 2FA
                        val body = response.errorBody()?.string() ?: ""
                        if ("TOTP" in body || "totp" in body || "2fa" in body.lowercase()) {
                            _uiState.value = AuthUiState.Requires2FA
                        } else {
                            _uiState.value = AuthUiState.Error("Invalid email or password")
                        }
                    }
                    response.code() == 401 -> _uiState.value = AuthUiState.Error("Invalid credentials or TOTP code")
                    response.code() == 403 -> _uiState.value = AuthUiState.Error("Account suspended — contact support")
                    else -> _uiState.value = AuthUiState.Error("Server error: ${response.code()}")
                }
            } catch (e: Exception) {
                Timber.e(e, "Login failed")
                _uiState.value = AuthUiState.Error("Network error: ${e.message}")
            }
        }
    }

    fun logout() {
        viewModelScope.launch {
            try {
                authApi.logout()
            } catch (_: Exception) {}
            securePrefs.clearAll()
            _uiState.value = AuthUiState.Idle
        }
    }
}
