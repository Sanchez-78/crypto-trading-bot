package com.cryptomaster.v5bot.di

import com.cryptomaster.v5bot.data.api.RetrofitClient
import com.cryptomaster.v5bot.data.api.V5BotApi
import com.cryptomaster.v5bot.data.firebase.FirebaseMetricsRepository
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object RepositoryModule {

    @Singleton
    @Provides
    fun provideV5BotApi(): V5BotApi {
        return RetrofitClient.getV5BotApi()
    }

    @Singleton
    @Provides
    fun provideFirebaseMetricsRepository(): FirebaseMetricsRepository {
        return FirebaseMetricsRepository()
    }
}
