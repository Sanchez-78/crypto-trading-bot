package com.cryptomaster.v5bot.data.firebase

import android.util.Log
import com.cryptomaster.v5bot.data.models.LearningHistory
import com.google.firebase.database.DataSnapshot
import com.google.firebase.database.DatabaseError
import com.google.firebase.database.FirebaseDatabase
import com.google.firebase.database.ValueEventListener
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import javax.inject.Inject

class FirebaseMetricsRepository @Inject constructor() {
    private val database = FirebaseDatabase.getInstance()
    private val metricsRef = database.getReference("metrics")
    private val learningRef = database.getReference("learning")

    companion object {
        private const val TAG = "FirebaseMetricsRepository"
    }

    // Save learning history to Firebase
    suspend fun saveLearningHistory(learning: LearningHistory): Result<Unit> = try {
        learningRef.child("latest").setValue(
            mapOf(
                "total_trades_closed" to learning.totalTradesClosed,
                "total_wins" to learning.totalWins,
                "total_losses" to learning.totalLosses,
                "total_flats" to learning.totalFlats,
                "win_rate" to learning.winRate,
                "total_net_pnl_usd" to learning.totalNetPnlUsd,
                "total_fees_usd" to learning.totalFeesUsd,
                "avg_pnl_per_trade" to learning.avgPnlPerTrade,
                "timestamp" to learning.timestamp,
                "trades_count" to learning.closedTrades.size
            )
        ).let { Result.success(Unit) }
    } catch (e: Exception) {
        Log.e(TAG, "Error saving learning history to Firebase", e)
        Result.failure(e)
    }

    // Stream learning history updates from Firebase
    fun getLearningHistoryStream(): Flow<Map<String, Any>?> = callbackFlow {
        val listener = object : ValueEventListener {
            override fun onDataChange(snapshot: DataSnapshot) {
                try {
                    val data = snapshot.value as? Map<String, Any>
                    trySend(data)
                } catch (e: Exception) {
                    Log.e(TAG, "Error reading learning history from Firebase", e)
                    trySend(null)
                }
            }

            override fun onCancelled(error: DatabaseError) {
                Log.e(TAG, "Firebase query cancelled: ${error.message}")
                trySend(null)
            }
        }

        learningRef.child("latest").addValueEventListener(listener)

        awaitClose {
            learningRef.child("latest").removeEventListener(listener)
        }
    }

    // Save metrics snapshot to Firebase
    suspend fun saveMetricsSnapshot(timestamp: String, metrics: Map<String, Any>): Result<Unit> =
        try {
            metricsRef.child("snapshots").child(timestamp).setValue(metrics)
                .let { Result.success(Unit) }
        } catch (e: Exception) {
            Log.e(TAG, "Error saving metrics snapshot to Firebase", e)
            Result.failure(e)
        }

    // Save trade to Firebase
    suspend fun saveTrade(tradeId: String, tradeData: Map<String, Any>): Result<Unit> = try {
        learningRef.child("trades").child(tradeId).setValue(tradeData)
            .let { Result.success(Unit) }
    } catch (e: Exception) {
        Log.e(TAG, "Error saving trade to Firebase", e)
        Result.failure(e)
    }

    // Stream per-symbol metrics
    fun getSymbolMetricsStream(symbol: String): Flow<Map<String, Any>?> = callbackFlow {
        val listener = object : ValueEventListener {
            override fun onDataChange(snapshot: DataSnapshot) {
                try {
                    val data = snapshot.value as? Map<String, Any>
                    trySend(data)
                } catch (e: Exception) {
                    Log.e(TAG, "Error reading symbol metrics", e)
                    trySend(null)
                }
            }

            override fun onCancelled(error: DatabaseError) {
                Log.e(TAG, "Firebase query cancelled: ${error.message}")
                trySend(null)
            }
        }

        learningRef.child("symbols").child(symbol).addValueEventListener(listener)

        awaitClose {
            learningRef.child("symbols").child(symbol).removeEventListener(listener)
        }
    }

    // Clear local cache
    suspend fun clearLocalCache(): Result<Unit> = try {
        database.reference.goOffline()
        database.reference.goOnline()
        Result.success(Unit)
    } catch (e: Exception) {
        Log.e(TAG, "Error clearing cache", e)
        Result.failure(e)
    }
}
