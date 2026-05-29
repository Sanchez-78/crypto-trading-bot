package com.cryptomaster.v5bot.ui.viewmodel

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cryptomaster.v5bot.data.api.RetrofitClient
import com.cryptomaster.v5bot.data.firebase.FirebaseMetricsRepository
import com.cryptomaster.v5bot.data.models.LearningHistory
import com.cryptomaster.v5bot.data.models.MetricsSnapshot
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class MetricsViewModel @Inject constructor(
    private val firebaseRepository: FirebaseMetricsRepository
) : ViewModel() {
    private val api = RetrofitClient.getV5BotApi()

    private val _learningHistory = MutableStateFlow<LearningHistory?>(null)
    val learningHistory: StateFlow<LearningHistory?> = _learningHistory.asStateFlow()

    private val _metrics = MutableStateFlow<MetricsSnapshot?>(null)
    val metrics: StateFlow<MetricsSnapshot?> = _metrics.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _isConnected = MutableStateFlow(false)
    val isConnected: StateFlow<Boolean> = _isConnected.asStateFlow()

    companion object {
        private const val TAG = "MetricsViewModel"
        private const val REFRESH_INTERVAL_MS = 2000L // 2 seconds
        private const val LEARNING_REFRESH_INTERVAL_MS = 10000L // 10 seconds
    }

    init {
        startAutoRefresh()
        checkHealth()
    }

    fun fetchLearningHistory() {
        viewModelScope.launch {
            try {
                _isLoading.value = true
                _error.value = null

                val learning = api.getLearningHistory()
                _learningHistory.value = learning

                // Save to Firebase for offline access
                firebaseRepository.saveLearningHistory(learning)

                Log.d(TAG, "Learning history fetched: ${learning.totalTradesClosed} trades")
            } catch (e: Exception) {
                val errorMsg = "Failed to fetch learning history: ${e.message}"
                _error.value = errorMsg
                Log.e(TAG, errorMsg, e)
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun fetchMetrics() {
        viewModelScope.launch {
            try {
                _isLoading.value = true
                _error.value = null

                val metrics = api.getMetrics()
                _metrics.value = metrics

                Log.d(TAG, "Metrics fetched: open_positions=${metrics.openPositions}")
            } catch (e: Exception) {
                val errorMsg = "Failed to fetch metrics: ${e.message}"
                _error.value = errorMsg
                Log.e(TAG, errorMsg, e)
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun checkHealth() {
        viewModelScope.launch {
            try {
                val health = api.getHealth()
                _isConnected.value = health.status == "healthy"
                Log.d(TAG, "Health check: ${health.status}")
            } catch (e: Exception) {
                _isConnected.value = false
                Log.e(TAG, "Health check failed", e)
            }
        }
    }

    private fun startAutoRefresh() {
        // Auto-refresh metrics every 2 seconds
        viewModelScope.launch {
            while (true) {
                try {
                    fetchMetrics()
                    delay(REFRESH_INTERVAL_MS)
                } catch (e: Exception) {
                    Log.e(TAG, "Auto-refresh error", e)
                    delay(REFRESH_INTERVAL_MS)
                }
            }
        }

        // Auto-refresh learning history every 10 seconds
        viewModelScope.launch {
            while (true) {
                try {
                    fetchLearningHistory()
                    delay(LEARNING_REFRESH_INTERVAL_MS)
                } catch (e: Exception) {
                    Log.e(TAG, "Learning auto-refresh error", e)
                    delay(LEARNING_REFRESH_INTERVAL_MS)
                }
            }
        }
    }

    fun setServerUrl(url: String) {
        // Implementation to change server URL dynamically
        Log.d(TAG, "Server URL set to: $url")
    }

    override fun onCleared() {
        super.onCleared()
        Log.d(TAG, "ViewModel cleared")
    }
}
