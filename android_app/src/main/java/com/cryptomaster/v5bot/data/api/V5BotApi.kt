package com.cryptomaster.v5bot.data.api

import com.cryptomaster.v5bot.data.models.HealthResponse
import com.cryptomaster.v5bot.data.models.LearningHistory
import com.cryptomaster.v5bot.data.models.MetricsSnapshot
import retrofit2.http.GET

interface V5BotApi {
    @GET("/metrics")
    suspend fun getMetrics(): MetricsSnapshot

    @GET("/health")
    suspend fun getHealth(): HealthResponse

    @GET("/metrics/dashboard")
    suspend fun getDashboard(): MetricsSnapshot

    @GET("/metrics/trading")
    suspend fun getTrading(): MetricsSnapshot

    @GET("/metrics/firebase")
    suspend fun getFirebase(): MetricsSnapshot

    @GET("/metrics/signals")
    suspend fun getSignals(): MetricsSnapshot

    @GET("/metrics/learning-history")
    suspend fun getLearningHistory(): LearningHistory
}
