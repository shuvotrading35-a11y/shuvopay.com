package com.shuvopay.presentation.screens.auth

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.*
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.shuvopay.presentation.viewmodel.AuthViewModel
import com.shuvopay.presentation.viewmodel.AuthUiState

@Composable
fun LoginScreen(
    onLoginSuccess: () -> Unit,
    viewModel: AuthViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()

    LaunchedEffect(uiState) {
        if (uiState is AuthUiState.LoggedIn) onLoginSuccess()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("ShuvoPay", style = MaterialTheme.typography.headlineLarge)
        Spacer(Modifier.height(8.dp))
        Text("Payment Gateway", style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(40.dp))

        var email by remember { mutableStateOf("") }
        var password by remember { mutableStateOf("") }
        var totpCode by remember { mutableStateOf("") }
        val requires2fa = uiState is AuthUiState.Requires2FA

        OutlinedTextField(
            value = email,
            onValueChange = { email = it },
            label = { Text("Email") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            label = { Text("Password") },
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )

        if (requires2fa) {
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = totpCode,
                onValueChange = { totpCode = it },
                label = { Text("Authenticator Code") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
        }

        Spacer(Modifier.height(24.dp))

        val isLoading = uiState is AuthUiState.Loading
        Button(
            onClick = { viewModel.login(email, password, totpCode.ifBlank { null }) },
            modifier = Modifier.fillMaxWidth().height(50.dp),
            enabled = !isLoading && email.isNotBlank() && password.isNotBlank(),
        ) {
            if (isLoading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            } else {
                Text("Sign In")
            }
        }

        if (uiState is AuthUiState.Error) {
            Spacer(Modifier.height(12.dp))
            Text(
                text = (uiState as AuthUiState.Error).message,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}


/**
 * PermissionExplanationScreen
 *
 * Shown before requesting SMS permissions.
 * Explains WHY the permissions are needed in plain user-facing language.
 * If user denies, the app never requests again until explicitly triggered.
 */
@Composable
fun PermissionExplanationScreen(
    onGranted: () -> Unit,
    onDenied: () -> Unit,
) {
    val permissionsNeeded = buildList {
        add(Manifest.permission.RECEIVE_SMS)
        add(Manifest.permission.READ_SMS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            add(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        val smsGranted = results[Manifest.permission.RECEIVE_SMS] == true
        if (smsGranted) onGranted() else onDenied()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("One-time Permission Setup", style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(20.dp))

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                PermissionItem(
                    title = "Receive SMS",
                    description = "ShuvoPay reads incoming SMS messages on this device to detect payment notifications from bKash, Nagad, Rocket, and other providers. Only incoming messages are read — never your personal conversations."
                )
                HorizontalDivider()
                PermissionItem(
                    title = "Read SMS",
                    description = "Required alongside Receive SMS so we can process each message through our secure parser. Your raw SMS content is encrypted immediately and never stored in plain text."
                )
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    HorizontalDivider()
                    PermissionItem(
                        title = "Notifications",
                        description = "A persistent notification is shown while monitoring is active, so you always know when ShuvoPay is running. You can stop monitoring at any time from the notification."
                    )
                }
            }
        }

        Spacer(Modifier.height(12.dp))

        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
        ) {
            Text(
                "Your privacy: SMS data is encrypted on-device before being uploaded. " +
                "You can delete all your data at any time from Settings → Data & Privacy.",
                modifier = Modifier.padding(12.dp),
                style = MaterialTheme.typography.bodySmall,
            )
        }

        Spacer(Modifier.height(28.dp))

        Button(
            onClick = { launcher.launch(permissionsNeeded.toTypedArray()) },
            modifier = Modifier.fillMaxWidth().height(50.dp),
        ) { Text("Grant Permissions") }

        Spacer(Modifier.height(8.dp))

        TextButton(
            onClick = onDenied,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Not now — limited functionality") }
    }
}

@Composable
private fun PermissionItem(title: String, description: String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall)
        Text(description, style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
