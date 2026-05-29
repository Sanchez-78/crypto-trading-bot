package com.cryptomaster.v5bot.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.cryptomaster.v5bot.data.models.LearningHistory
import com.cryptomaster.v5bot.data.models.PerSymbolLearning
import com.cryptomaster.v5bot.data.models.TradeRecord
import com.cryptomaster.v5bot.ui.viewmodel.MetricsViewModel
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
fun LearningMetricsScreen(viewModel: MetricsViewModel = hiltViewModel()) {
    val learningHistory by viewModel.learningHistory.collectAsState()
    val isLoading by viewModel.isLoading.collectAsState()
    val error by viewModel.error.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(16.dp)
    ) {
        // Header with refresh button
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                "Learning Metrics",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold
            )
            IconButton(onClick = { viewModel.fetchLearningHistory() }) {
                Icon(Icons.Default.Refresh, contentDescription = "Refresh")
            }
        }

        // Error message
        error?.let {
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 16.dp),
                colors = CardDefaults.cardColors(containerColor = Color(0xFFFFEBEE))
            ) {
                Text(
                    it,
                    modifier = Modifier.padding(16.dp),
                    color = Color(0xFFB71C1C)
                )
            }
        }

        // Loading indicator
        if (isLoading && learningHistory == null) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                CircularProgressIndicator()
                Spacer(modifier = Modifier.height(16.dp))
                Text("Loading metrics...")
            }
        } else if (learningHistory != null) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                // Overall metrics
                item {
                    OverallMetricsCard(learningHistory!!)
                }

                // Per-symbol summary
                item {
                    Text(
                        "Performance by Symbol",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(top = 16.dp, bottom = 8.dp)
                    )
                }

                items(learningHistory!!.perSymbolSummary.values.toList()) { symbolMetrics ->
                    SymbolMetricsCard(symbolMetrics)
                }

                // Trade history header
                item {
                    Text(
                        "Trade History (${learningHistory!!.closedTrades.size} trades)",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(top = 16.dp, bottom = 8.dp)
                    )
                }

                items(learningHistory!!.closedTrades) { trade ->
                    TradeHistoryCard(trade)
                }
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Text("No data available")
                Spacer(modifier = Modifier.height(16.dp))
                Button(onClick = { viewModel.fetchLearningHistory() }) {
                    Text("Load Metrics")
                }
            }
        }
    }
}

@Composable
private fun OverallMetricsCard(learning: LearningHistory) {
    Card(
        modifier = Modifier
            .fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                "Overall Statistics",
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(bottom = 12.dp)
            )

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                MetricItem("Total Trades", learning.totalTradesClosed.toString())
                MetricItem("Wins", learning.totalWins.toString())
                MetricItem("Losses", learning.totalLosses.toString())
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                MetricItem(
                    "Win Rate",
                    "${(learning.winRate?.times(100) ?: 0f).toInt()}%"
                )
                MetricItem(
                    "Total PnL",
                    "$${String.format("%.2f", learning.totalNetPnlUsd)}",
                    color = if (learning.totalNetPnlUsd >= 0) Color(0xFF4CAF50) else Color(0xFFF44336)
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                MetricItem(
                    "Avg PnL/Trade",
                    "$${String.format("%.2f", learning.avgPnlPerTrade ?: 0f)}"
                )
                MetricItem(
                    "Total Fees",
                    "$${String.format("%.2f", learning.totalFeesUsd)}"
                )
            }

            Spacer(modifier = Modifier.height(8.dp))
            Text(
                "Updated: ${learning.timestamp}",
                fontSize = 12.sp,
                color = Color.Gray
            )
        }
    }
}

@Composable
private fun SymbolMetricsCard(symbol: PerSymbolLearning) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                symbol.symbol,
                fontSize = 14.sp,
                fontWeight = FontWeight.Bold
            )

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                MetricItem("Trades", symbol.tradesClosed.toString(), fontSize = 12.sp)
                MetricItem("Win Rate", "${(symbol.winRate?.times(100) ?: 0f).toInt()}%", fontSize = 12.sp)
                MetricItem(
                    "PnL",
                    "$${String.format("%.2f", symbol.totalPnlUsd)}",
                    fontSize = 12.sp,
                    color = if (symbol.totalPnlUsd >= 0) Color(0xFF4CAF50) else Color(0xFFF44336)
                )
            }
        }
    }
}

@Composable
private fun TradeHistoryCard(trade: TradeRecord) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = when (trade.outcome) {
                "WIN" -> Color(0xFFE8F5E9)
                "LOSS" -> Color(0xFFFFEBEE)
                else -> MaterialTheme.colorScheme.surface
            }
        )
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        trade.symbol,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        "${trade.entrySide} @ ${String.format("%.2f", trade.entryPrice)}",
                        fontSize = 12.sp,
                        color = Color.Gray
                    )
                }
                Text(
                    "${if (trade.netPnlUsd >= 0) "+" else ""}${String.format("%.2f", trade.netPnlUsd)}",
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Bold,
                    color = if (trade.netPnlUsd >= 0) Color(0xFF4CAF50) else Color(0xFFF44336)
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            Row(
                modifier = Modifier
                    .fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                fontSize = 11.sp
            ) {
                Text("Hold: ${trade.holdSeconds}s")
                Text("Fees: $${String.format("%.2f", trade.totalCostsUsd)}")
                Text("PnL%: ${String.format("%.2f", trade.netPnlPct)}%")
            }

            Spacer(modifier = Modifier.height(4.dp))

            Text(
                "${formatTimestamp(trade.entryTimestamp)} → ${formatTimestamp(trade.exitTimestamp)}",
                fontSize = 10.sp,
                color = Color.Gray
            )
        }
    }
}

@Composable
private fun MetricItem(
    label: String,
    value: String,
    fontSize: androidx.compose.ui.unit.TextUnit = 14.sp,
    color: Color = MaterialTheme.colorScheme.onSurface
) {
    Column {
        Text(label, fontSize = 12.sp, color = Color.Gray)
        Text(value, fontSize = fontSize, fontWeight = FontWeight.Bold, color = color)
    }
}

private fun formatTimestamp(iso8601: String): String {
    return try {
        val instant = Instant.parse(iso8601)
        val zonedDateTime = instant.atZone(ZoneId.systemDefault())
        val formatter = DateTimeFormatter.ofPattern("HH:mm:ss")
        zonedDateTime.format(formatter)
    } catch (e: Exception) {
        iso8601.takeLast(8)
    }
}
