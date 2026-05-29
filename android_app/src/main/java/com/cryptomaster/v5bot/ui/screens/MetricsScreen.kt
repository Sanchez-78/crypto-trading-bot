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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Circle
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import com.cryptomaster.v5bot.data.models.MetricsSnapshot
import com.cryptomaster.v5bot.ui.viewmodel.MetricsViewModel

@Composable
fun MetricsScreen(viewModel: MetricsViewModel = hiltViewModel()) {
    val metrics by viewModel.metrics.collectAsState()
    val isConnected by viewModel.isConnected.collectAsState()
    val error by viewModel.error.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(16.dp)
    ) {
        // Header with status and refresh button
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Default.Circle,
                    contentDescription = "Status",
                    tint = if (isConnected) Color(0xFF4CAF50) else Color(0xFFF44336),
                    modifier = Modifier
                        .padding(end = 8.dp)
                )
                Text(
                    "V5 Bot Metrics",
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold
                )
            }
            IconButton(onClick = { viewModel.checkHealth() }) {
                Icon(Icons.Default.Refresh, contentDescription = "Refresh")
            }
        }

        // Status card
        if (metrics != null) {
            StatusCard(metrics!!, isConnected)
        }

        Spacer(modifier = Modifier.height(16.dp))

        error?.let {
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 16.dp),
                colors = CardDefaults.cardColors(containerColor = Color(0xFFFFEBEE))
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        Icons.Default.Info,
                        contentDescription = "Error",
                        tint = Color(0xFFB71C1C),
                        modifier = Modifier.padding(end = 12.dp)
                    )
                    Text(
                        it,
                        color = Color(0xFFB71C1C),
                        fontSize = 12.sp
                    )
                }
            }
        }

        // Content
        if (metrics != null) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    MetricsOverview(metrics!!)
                }
                item {
                    TradingMetrics(metrics!!)
                }
                item {
                    SignalsMetrics(metrics!!)
                }
                item {
                    FirebaseQuotaMetrics(metrics!!)
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
                Text("Loading metrics...", fontSize = 16.sp)
                Spacer(modifier = Modifier.height(16.dp))
                Button(onClick = { viewModel.fetchMetrics() }) {
                    Text("Retry")
                }
            }
        }
    }
}

@Composable
private fun StatusCard(metrics: MetricsSnapshot, isConnected: Boolean) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (isConnected) Color(0xFFE8F5E9) else Color(0xFFFFEBEE)
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        if (metrics.running) "Bot Running" else "Bot Stopped",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        "Epoch: ${metrics.epochId}",
                        fontSize = 12.sp,
                        color = Color.Gray
                    )
                }
                Text(
                    if (isConnected) "Connected" else "Disconnected",
                    fontSize = 14.sp,
                    color = if (isConnected) Color(0xFF4CAF50) else Color(0xFFF44336),
                    fontWeight = FontWeight.Bold
                )
            }

            Spacer(modifier = Modifier.height(12.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                StatusItem("Feed", if (metrics.feedConnected) "Connected" else "Offline")
                StatusItem("Symbols", "${metrics.symbolsWithData} active")
                StatusItem("Positions", "${metrics.openPositions} open")
            }
        }
    }
}

@Composable
private fun MetricsOverview(metrics: MetricsSnapshot) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Performance", fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 12.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                MetricItem("PnL", "$${String.format("%.2f", metrics.totalNetPnlUsd)}",
                    color = if (metrics.totalNetPnlUsd >= 0) Color(0xFF4CAF50) else Color(0xFFF44336))
                MetricItem("Win Rate", "${metrics.winRate?.times(100)?.toInt() ?: 0}%")
                MetricItem("Profit Factor", "${String.format("%.2f", metrics.profitFactor ?: 0f)}")
            }

            Spacer(modifier = Modifier.height(8.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                MetricItem("Notional", "$${String.format("%.2f", metrics.openNotionalUsd)}")
                MetricItem("Cost Avg", "${String.format("%.1f", metrics.averageCostBps)} bps")
                MetricItem("Regime", metrics.currentRegime ?: "N/A")
            }
        }
    }
}

@Composable
private fun TradingMetrics(metrics: MetricsSnapshot) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Trading Activity", fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 12.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                MetricItem("Entries", "${metrics.entriesAttempted}")
                MetricItem("Success", "${metrics.entriesSuccessful}")
                MetricItem("Rejected", "${metrics.entriesRejectedByGate}")
            }

            Spacer(modifier = Modifier.height(8.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                MetricItem("Closed", "${metrics.tradesClosed}")
                MetricItem("Uptime", "${metrics.uptimeSeconds}s")
                MetricItem("Updates", "${metrics.learningUpdates}")
            }
        }
    }
}

@Composable
private fun SignalsMetrics(metrics: MetricsSnapshot) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Current Signals", fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 8.dp))

            metrics.signals.forEach { (symbol, signal) ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(symbol, fontWeight = FontWeight.Bold)
                    Text(
                        signal,
                        fontSize = 12.sp,
                        color = if (signal.contains("ACCEPTED")) Color(0xFF4CAF50) else Color(0xFFF44336)
                    )
                }
            }
        }
    }
}

@Composable
private fun FirebaseQuotaMetrics(metrics: MetricsSnapshot) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Firebase Quota", fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 12.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text("Reads", fontSize = 12.sp, color = Color.Gray)
                    Text("${metrics.quotaReadsUsed}/${metrics.quotaReadsLimit}", fontWeight = FontWeight.Bold)
                }
                Column {
                    Text("Writes", fontSize = 12.sp, color = Color.Gray)
                    Text("${metrics.quotaWritesUsed}/${metrics.quotaWritesLimit}", fontWeight = FontWeight.Bold)
                }
                Column {
                    Text("State", fontSize = 12.sp, color = Color.Gray)
                    Text(
                        metrics.quotaState,
                        fontWeight = FontWeight.Bold,
                        color = when (metrics.quotaState) {
                            "NORMAL" -> Color(0xFF4CAF50)
                            "WARNING" -> Color(0xFFFFC107)
                            else -> Color(0xFFF44336)
                        }
                    )
                }
            }
        }
    }
}

@Composable
private fun StatusItem(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(label, fontSize = 11.sp, color = Color.Gray)
        Text(value, fontSize = 12.sp, fontWeight = FontWeight.Bold)
    }
}
