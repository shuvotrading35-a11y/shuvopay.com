package com.shuvopay.presentation.screens.dashboard

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.shuvopay.data.local.entity.SmsQueueEntity
import com.shuvopay.data.local.entity.SmsUploadStatus
import com.shuvopay.domain.model.DashboardStats
import com.shuvopay.presentation.viewmodel.DashboardIntent
import com.shuvopay.presentation.viewmodel.DashboardUiState
import com.shuvopay.presentation.viewmodel.DashboardViewModel
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    onViewLogs: () -> Unit,
    viewModel: DashboardViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val queueDepth by viewModel.queueDepth.collectAsState(initial = 0)
    val recentSms by viewModel.recentSms.collectAsState(initial = emptyList())
    val pingLatency by viewModel.pingLatencyMs.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("ShuvoPay", fontWeight = FontWeight.Bold) },
                actions = {
                    IconButton(onClick = { viewModel.onIntent(DashboardIntent.Refresh) }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                }
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier.padding(padding).fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // Device Status Banner
            item {
                DeviceStatusCard(queueDepth = queueDepth, pingLatency = pingLatency)
            }

            // Stats
            when (val state = uiState) {
                is DashboardUiState.Loading -> item {
                    Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator()
                    }
                }
                is DashboardUiState.Success -> {
                    item { StatsGrid(stats = state.stats) }
                }
                is DashboardUiState.Error -> item {
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                        Text(state.message, modifier = Modifier.padding(16.dp),
                            color = MaterialTheme.colorScheme.onErrorContainer)
                    }
                }
            }

            // Quick Actions
            item {
                QuickActions(
                    onForceSync = { viewModel.onIntent(DashboardIntent.ForceSync) },
                    onTestConnection = { viewModel.onIntent(DashboardIntent.TestConnection) },
                    onViewLogs = onViewLogs,
                )
            }

            // Recent Activity
            item {
                Text("Recent Activity", style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold)
            }

            if (recentSms.isEmpty()) {
                item {
                    Text("No SMS processed yet",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(vertical = 8.dp))
                }
            } else {
                items(recentSms) { sms -> SmsActivityRow(sms = sms) }
            }
        }
    }
}

@Composable
private fun DeviceStatusCard(queueDepth: Int, pingLatency: Long?) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.padding(16.dp).fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(
                    Icons.Default.CheckCircle,
                    contentDescription = null,
                    tint = if (pingLatency != null) Color(0xFF4CAF50) else Color(0xFFFFC107),
                    modifier = Modifier.size(12.dp),
                )
                Text(
                    text = if (pingLatency != null) "Online · ${pingLatency}ms" else "Checking...",
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            if (queueDepth > 0) {
                Badge { Text("$queueDepth pending") }
            }
        }
    }
}

@Composable
private fun StatsGrid(stats: DashboardStats) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        StatCard("Received", stats.todayReceived.toString(), Modifier.weight(1f))
        StatCard("Matched", stats.todayMatched.toString(), Modifier.weight(1f), color = Color(0xFF4CAF50))
        StatCard("Pending", stats.todayPending.toString(), Modifier.weight(1f), color = Color(0xFFFFC107))
        StatCard("Failed", stats.todayFailed.toString(), Modifier.weight(1f), color = Color(0xFFF44336))
    }
}

@Composable
private fun StatCard(label: String, value: String, modifier: Modifier = Modifier, color: Color = Color.Unspecified) {
    Card(modifier = modifier) {
        Column(
            modifier = Modifier.padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(value, style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold, color = color)
            Text(label, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun QuickActions(onForceSync: () -> Unit, onTestConnection: () -> Unit, onViewLogs: () -> Unit) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = onForceSync, modifier = Modifier.weight(1f)) {
            Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(4.dp))
            Text("Sync")
        }
        OutlinedButton(onClick = onTestConnection, modifier = Modifier.weight(1f)) {
            Icon(Icons.Default.Notifications, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(4.dp))
            Text("Ping")
        }
        OutlinedButton(onClick = onViewLogs, modifier = Modifier.weight(1f)) {
            Icon(Icons.Default.List, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(4.dp))
            Text("Logs")
        }
    }
}

@Composable
private fun SmsActivityRow(sms: SmsQueueEntity) {
    val formatter = DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault())
    val timeStr = formatter.format(Instant.ofEpochMilli(sms.createdAtMs))

    val (statusColor, statusLabel) = when (sms.status) {
        SmsUploadStatus.UPLOADED -> Color(0xFF4CAF50) to "Uploaded"
        SmsUploadStatus.PENDING -> Color(0xFFFFC107) to "Pending"
        SmsUploadStatus.UPLOADING -> Color(0xFF2196F3) to "Uploading"
        SmsUploadStatus.FAILED -> Color(0xFFF44336) to "Failed"
    }

    ListItem(
        headlineContent = {
            Text(sms.provider ?: "Unknown provider", style = MaterialTheme.typography.bodyMedium)
        },
        supportingContent = {
            Text(
                buildString {
                    sms.amount?.let { append("BDT $it · ") }
                    sms.transactionId?.let { append(it) }
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        },
        leadingContent = {
            Icon(Icons.Default.Info, contentDescription = null,
                tint = MaterialTheme.colorScheme.primary)
        },
        trailingContent = {
            Column(horizontalAlignment = Alignment.End) {
                Text(timeStr, style = MaterialTheme.typography.labelSmall)
                Text(statusLabel, style = MaterialTheme.typography.labelSmall, color = statusColor)
            }
        },
    )
    HorizontalDivider(thickness = 0.5.dp)
}
