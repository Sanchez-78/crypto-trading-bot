package com.cryptomaster.v5bot.data.models

import com.google.gson.annotations.SerializedName

data class LearningHistory(
    @SerializedName("total_trades_closed")
    val totalTradesClosed: Int,
    @SerializedName("total_wins")
    val totalWins: Int,
    @SerializedName("total_losses")
    val totalLosses: Int,
    @SerializedName("total_flats")
    val totalFlats: Int,
    @SerializedName("win_rate")
    val winRate: Float?,
    @SerializedName("total_net_pnl_usd")
    val totalNetPnlUsd: Float,
    @SerializedName("total_fees_usd")
    val totalFeesUsd: Float,
    @SerializedName("avg_pnl_per_trade")
    val avgPnlPerTrade: Float?,
    @SerializedName("per_symbol_summary")
    val perSymbolSummary: Map<String, PerSymbolLearning>,
    @SerializedName("closed_trades")
    val closedTrades: List<TradeRecord>,
    @SerializedName("timestamp")
    val timestamp: String
)

data class PerSymbolLearning(
    @SerializedName("symbol")
    val symbol: String,
    @SerializedName("trades_closed")
    val tradesClosed: Int,
    @SerializedName("wins")
    val wins: Int,
    @SerializedName("losses")
    val losses: Int,
    @SerializedName("flats")
    val flats: Int,
    @SerializedName("win_rate")
    val winRate: Float?,
    @SerializedName("total_pnl_usd")
    val totalPnlUsd: Float,
    @SerializedName("avg_pnl_per_trade")
    val avgPnlPerTrade: Float?,
    @SerializedName("total_fees_usd")
    val totalFeesUsd: Float,
    @SerializedName("best_trade_pnl_usd")
    val bestTradePnlUsd: Float?,
    @SerializedName("worst_trade_pnl_usd")
    val worstTradePnlUsd: Float?
)

data class TradeRecord(
    @SerializedName("trade_id")
    val tradeId: String,
    @SerializedName("symbol")
    val symbol: String,
    @SerializedName("entry_side")
    val entrySide: String,
    @SerializedName("entry_price")
    val entryPrice: Float,
    @SerializedName("exit_price")
    val exitPrice: Float,
    @SerializedName("qty")
    val qty: Float,
    @SerializedName("entry_timestamp")
    val entryTimestamp: String,
    @SerializedName("exit_timestamp")
    val exitTimestamp: String,
    @SerializedName("hold_seconds")
    val holdSeconds: Int,
    @SerializedName("gross_pnl_usd")
    val grossPnlUsd: Float,
    @SerializedName("gross_pnl_pct")
    val grossPnlPct: Float,
    @SerializedName("net_pnl_usd")
    val netPnlUsd: Float,
    @SerializedName("net_pnl_pct")
    val netPnlPct: Float,
    @SerializedName("total_costs_usd")
    val totalCostsUsd: Float,
    @SerializedName("entry_fee_usd")
    val entryFeeUsd: Float,
    @SerializedName("exit_fee_usd")
    val exitFeeUsd: Float,
    @SerializedName("funding_cost_usd")
    val fundingCostUsd: Float,
    @SerializedName("entry_notional_usd")
    val entryNotionalUsd: Float,
    @SerializedName("outcome")
    val outcome: String
)

data class MetricsSnapshot(
    @SerializedName("running")
    val running: Boolean,
    @SerializedName("epoch_id")
    val epochId: String?,
    @SerializedName("timestamp")
    val timestamp: String,
    @SerializedName("feed_connected")
    val feedConnected: Boolean,
    @SerializedName("symbols_with_data")
    val symbolsWithData: Int,
    @SerializedName("open_positions")
    val openPositions: Int,
    @SerializedName("open_notional_usd")
    val openNotionalUsd: Float,
    @SerializedName("max_open_global")
    val maxOpenGlobal: Int,
    @SerializedName("entries_attempted")
    val entriesAttempted: Int,
    @SerializedName("entries_successful")
    val entriesSuccessful: Int,
    @SerializedName("entries_rejected_by_gate")
    val entriesRejectedByGate: Int,
    @SerializedName("trades_closed")
    val tradesClosed: Int,
    @SerializedName("total_net_pnl_usd")
    val totalNetPnlUsd: Float,
    @SerializedName("net_pnl_pct")
    val netPnlPct: Float,
    @SerializedName("win_rate")
    val winRate: Float?,
    @SerializedName("profit_factor")
    val profitFactor: Float?,
    @SerializedName("average_cost_bps")
    val averageCostBps: Float,
    @SerializedName("signals")
    val signals: Map<String, String>,
    @SerializedName("current_regime")
    val currentRegime: String?,
    @SerializedName("firebase_writes")
    val firebaseWrites: Int,
    @SerializedName("firebase_failures")
    val firebaseFailures: Int,
    @SerializedName("quota_reads_used")
    val quotaReadsUsed: Int,
    @SerializedName("quota_reads_limit")
    val quotaReadsLimit: Int,
    @SerializedName("quota_writes_used")
    val quotaWritesUsed: Int,
    @SerializedName("quota_writes_limit")
    val quotaWritesLimit: Int,
    @SerializedName("quota_state")
    val quotaState: String,
    @SerializedName("reconnect_count")
    val reconnectCount: Int,
    @SerializedName("stale_events_rejected")
    val staleEventsRejected: Int,
    @SerializedName("book_spreads")
    val bookSpreads: Map<String, Float>,
    @SerializedName("mid_prices")
    val midPrices: Map<String, Float>,
    @SerializedName("learning_updates")
    val learningUpdates: Int,
    @SerializedName("strategies_being_evaluated")
    val strategiesBeingEvaluated: Int,
    @SerializedName("uptime_seconds")
    val uptimeSeconds: Int,
    @SerializedName("logs_per_second")
    val logsPerSecond: Float,
    @SerializedName("cpu_percent")
    val cpuPercent: Float,
    @SerializedName("memory_mb")
    val memoryMb: Int
)

data class HealthResponse(
    @SerializedName("status")
    val status: String,
    @SerializedName("running")
    val running: Boolean,
    @SerializedName("feed_connected")
    val feedConnected: Boolean,
    @SerializedName("firebase_quota_ok")
    val firebaseQuotaOk: Boolean
)
