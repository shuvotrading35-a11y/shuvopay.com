package com.shuvopay.util

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SecurePrefs @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs = EncryptedSharedPreferences.create(
        context,
        "shuvopay_secure_prefs",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun getAccessToken(): String? = prefs.getString("access_token", null)
    fun setAccessToken(token: String) = prefs.edit().putString("access_token", token).apply()
    fun clearAccessToken() = prefs.edit().remove("access_token").apply()

    fun getServerUrl(): String = prefs.getString("server_url", "https://api.shuvopay.com") ?: "https://api.shuvopay.com"
    fun setServerUrl(url: String) = prefs.edit().putString("server_url", url).apply()

    fun getDeviceId(): String? = prefs.getString("device_id", null)
    fun setDeviceId(id: String) = prefs.edit().putString("device_id", id).apply()
}
