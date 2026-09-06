package com.shuvopay.presentation.screens.logs

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shuvopay.data.local.entity.AppDatabase
import com.shuvopay.data.local.entity.SmsQueueEntity
import com.shuvopay.data.local.entity.SmsUploadStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.stateIn
import java.text.SimpleDateFormat
import java.util.*
import javax.inject.Inject

@HiltViewModel
class SmsLogsViewModel @Inject constructor(db: AppDatabase) : ViewModel() {
    val logs = db.smsQueueDao().observeRecent(50)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SmsLogsScreen(
    onBack: () -> Unit,
    viewModel: SmsLogsViewModel = hiltViewModel(),
) {
    val logs by viewModel.logs.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("SMS Logs") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        if (logs.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize().padding(padding),
                contentAlignment = Alignment.Center,
            ) {
                Text("No SMS logs yet", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(logs, key = { it.id }) { sms ->
                    SmsLogItem(sms)
                }
            }
        }
    }
}

@Composable
private fun SmsLogItem(sms: SmsQueueEntity) {
    val statusColor = when (sms.status) {
        SmsUploadStatus.UPLOADED -> MaterialTheme.colorScheme.primary
        SmsUploadStatus.FAILED -> MaterialTheme.colorScheme.error
        SmsUploadStatus.PENDING, SmsUploadStatus.UPLOADING -> MaterialTheme.colorScheme.tertiary
    }
    val fmt = remember { SimpleDateFormat("MM-dd HH:mm:ss", Locale.getDefault()) }

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(sms.senderName ?: sms.senderNumber ?: "Unknown", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                Text(
                    sms.status.name,
                    color = statusColor,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                "Provider: ${sms.provider ?: "-"}  Amount: ${sms.amount ?: "-"} ${sms.currency}",
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                fmt.format(Date(sms.smsTimestampMs)),
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}
