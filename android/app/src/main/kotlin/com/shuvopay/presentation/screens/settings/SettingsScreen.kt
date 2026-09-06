package com.shuvopay.presentation.screens.settings

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shuvopay.util.SecurePrefs
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val securePrefs: SecurePrefs,
) : ViewModel() {
    val serverUrl = MutableStateFlow(securePrefs.getServerUrl())
    val deviceId = MutableStateFlow(securePrefs.getDeviceId() ?: "Not registered")
    private val _loggedOut = MutableStateFlow(false)
    val loggedOut = _loggedOut.asStateFlow()

    fun saveServerUrl(url: String) {
        securePrefs.saveServerUrl(url.trimEnd('/'))
        serverUrl.value = url.trimEnd('/')
    }

    fun logout() {
        viewModelScope.launch {
            securePrefs.clearAll()
            _loggedOut.value = true
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBack: () -> Unit,
    onLogout: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val serverUrl by viewModel.serverUrl.collectAsState()
    val deviceId by viewModel.deviceId.collectAsState()
    val loggedOut by viewModel.loggedOut.collectAsState()
    var urlInput by remember(serverUrl) { mutableStateOf(serverUrl) }
    var showLogoutDialog by remember { mutableStateOf(false) }

    LaunchedEffect(loggedOut) { if (loggedOut) onLogout() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // Server URL
            Text("Server", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            OutlinedTextField(
                value = urlInput,
                onValueChange = { urlInput = it },
                label = { Text("API URL") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Button(
                onClick = { viewModel.saveServerUrl(urlInput) },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Save URL") }

            HorizontalDivider()

            // Device info
            Text("Device", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            ListItem(
                headlineContent = { Text("Device ID") },
                supportingContent = { Text(deviceId, style = MaterialTheme.typography.bodySmall) },
            )

            HorizontalDivider()

            // Logout
            Button(
                onClick = { showLogoutDialog = true },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
            ) { Text("Logout") }
        }
    }

    if (showLogoutDialog) {
        AlertDialog(
            onDismissRequest = { showLogoutDialog = false },
            title = { Text("Logout") },
            text = { Text("Are you sure you want to logout?") },
            confirmButton = {
                TextButton(onClick = { viewModel.logout() }) { Text("Logout") }
            },
            dismissButton = {
                TextButton(onClick = { showLogoutDialog = false }) { Text("Cancel") }
            }
        )
    }
}
