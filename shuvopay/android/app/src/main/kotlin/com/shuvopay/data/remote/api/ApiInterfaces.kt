package com.shuvopay.data.remote.api

import com.shuvopay.data.remote.dto.*
import retrofit2.Response
import retrofit2.http.*

interface AuthApi {
    @POST("api/v1/auth/login")
    suspend fun login(@Body body: LoginRequest): Response<TokenResponse>

    @POST("api/v1/auth/refresh")
    suspend fun refresh(): Response<TokenResponse>

    @POST("api/v1/auth/logout")
    suspend fun logout(): Response<Unit>

    @POST("api/v1/auth/2fa/enable")
    suspend fun enable2fa(@Header("Authorization") token: String): Response<TwoFASetupResponse>

    @POST("api/v1/auth/2fa/verify")
    suspend fun verify2fa(
        @Header("Authorization") token: String,
        @Body body: TwoFAVerifyRequest,
    ): Response<Unit>
}

interface DeviceApi {
    @POST("api/v1/device/register")
    suspend fun registerDevice(
        @Header("Authorization") token: String,
        @Body body: DeviceRegisterRequest,
    ): Response<DeviceRegisterResponse>

    @POST("api/v1/device/heartbeat")
    suspend fun heartbeat(
        @Header("X-Device-Key") deviceKey: String,
    ): Response<Unit>

    @GET("api/v1/device/parser-rules")
    suspend fun getParserRules(
        @Header("X-Device-Key") deviceKey: String,
        @Header("If-None-Match") ifNoneMatch: String?,
    ): Response<List<ParserRuleDto>>

    @DELETE("api/v1/device/{deviceId}")
    suspend fun deregisterDevice(
        @Header("Authorization") token: String,
        @Path("deviceId") deviceId: String,
    ): Response<Unit>
}

interface SmsApi {
    @POST("api/v1/sms/report")
    suspend fun reportSms(
        @Header("X-Device-Key") deviceKey: String,
        @Header("X-Request-ID") requestId: String,
        @Body body: SmsReportRequest,
    ): Response<SmsReportResponse>

    @POST("api/v1/sms/report/batch")
    suspend fun reportSmsBatch(
        @Header("X-Device-Key") deviceKey: String,
        @Header("X-Request-ID") requestId: String,
        @Body body: SmsBatchRequest,
    ): Response<SmsBatchResponse>
}

interface InvoiceApi {
    @GET("api/v1/invoice/{invoiceId}")
    suspend fun getInvoice(
        @Header("Authorization") token: String,
        @Path("invoiceId") invoiceId: String,
    ): Response<InvoiceDto>
}
