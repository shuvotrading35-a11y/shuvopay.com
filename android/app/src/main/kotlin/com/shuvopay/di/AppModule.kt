package com.shuvopay.di

import android.content.Context
import androidx.room.Room
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import com.shuvopay.data.local.entity.AppDatabase
import com.shuvopay.data.remote.api.AuthApi
import com.shuvopay.data.remote.api.DeviceApi
import com.shuvopay.data.remote.api.SmsApi
import com.shuvopay.util.SecurePrefs
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.CertificatePinner
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideJson(): Json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        explicitNulls = false
    }

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): AppDatabase =
        Room.databaseBuilder(context, AppDatabase::class.java, "shuvopay.db")
            .fallbackToDestructiveMigration()
            .build()

    @Provides fun provideSmsQueueDao(db: AppDatabase) = db.smsQueueDao()
    @Provides fun provideParserRuleDao(db: AppDatabase) = db.parserRuleDao()
    @Provides fun provideDeviceInfoDao(db: AppDatabase) = db.deviceInfoDao()

    @Provides
    @Singleton
    fun provideOkHttpClient(securePrefs: SecurePrefs): OkHttpClient {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }

        // Certificate pinning — add your server's SHA-256 pins here.
        // Generate with: openssl x509 -in cert.pem -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | base64
        val certificatePinner = CertificatePinner.Builder()
            // .add("api.shuvopay.com", "sha256/REPLACE_WITH_YOUR_REAL_PIN=")
            .build()

        return OkHttpClient.Builder()
            .certificatePinner(certificatePinner)
            .addInterceptor { chain ->
                val token = securePrefs.getAccessToken()
                val request = if (token != null) {
                    chain.request().newBuilder()
                        .header("Authorization", "Bearer $token")
                        .build()
                } else {
                    chain.request()
                }
                chain.proceed(request)
            }
            .addInterceptor(logging)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    @Provides
    @Singleton
    fun provideRetrofit(
        okHttpClient: OkHttpClient,
        securePrefs: SecurePrefs,
        json: Json,
    ): Retrofit = Retrofit.Builder()
        .baseUrl(securePrefs.getServerUrl().trimEnd('/') + "/")
        .client(okHttpClient)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()

    @Provides @Singleton fun provideAuthApi(retrofit: Retrofit): AuthApi =
        retrofit.create(AuthApi::class.java)

    @Provides @Singleton fun provideDeviceApi(retrofit: Retrofit): DeviceApi =
        retrofit.create(DeviceApi::class.java)

    @Provides @Singleton fun provideSmsApi(retrofit: Retrofit): SmsApi =
        retrofit.create(SmsApi::class.java)
}
