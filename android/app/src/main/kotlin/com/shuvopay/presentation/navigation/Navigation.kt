package com.shuvopay.presentation.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.shuvopay.presentation.screens.auth.LoginScreen
import com.shuvopay.presentation.screens.auth.PermissionExplanationScreen
import com.shuvopay.presentation.screens.auth.TwoFAScreen
import com.shuvopay.presentation.screens.dashboard.DashboardScreen
import com.shuvopay.presentation.screens.logs.SmsLogsScreen
import com.shuvopay.presentation.screens.settings.SettingsScreen
import com.shuvopay.presentation.viewmodel.AuthUiState
import com.shuvopay.presentation.viewmodel.AuthViewModel
import com.shuvopay.presentation.viewmodel.DeviceState
import com.shuvopay.presentation.viewmodel.DeviceViewModel

sealed class Screen(val route: String) {
    data object Login : Screen("login")
    data object TwoFA : Screen("two_fa/{email}/{password}") {
        fun createRoute(email: String, password: String) = "two_fa/$email/$password"
    }
    data object Permissions : Screen("permissions")
    data object Dashboard : Screen("dashboard")
    data object SmsLogs : Screen("sms_logs")
    data object Settings : Screen("settings")
}

@Composable
fun AppNavHost(
    navController: NavHostController = rememberNavController(),
    startDestination: String = Screen.Login.route,
) {
    NavHost(navController = navController, startDestination = startDestination) {

        composable(Screen.Login.route) {
            val authViewModel: AuthViewModel = hiltViewModel()
            val uiState by authViewModel.uiState.collectAsState()

            LaunchedEffect(uiState) {
                when (uiState) {
                    is AuthUiState.LoggedIn -> navController.navigate(Screen.Permissions.route) {
                        popUpTo(Screen.Login.route) { inclusive = true }
                    }
                    else -> {}
                }
            }

            LoginScreen(
                onLoginSuccess = {},
                onRequires2FA = { email, password ->
                    navController.navigate(Screen.TwoFA.createRoute(email, password))
                }
            )
        }

        composable(Screen.TwoFA.route) { backstack ->
            val email = backstack.arguments?.getString("email") ?: ""
            val password = backstack.arguments?.getString("password") ?: ""
            val authViewModel: AuthViewModel = hiltViewModel()
            val uiState by authViewModel.uiState.collectAsState()

            LaunchedEffect(uiState) {
                if (uiState is AuthUiState.LoggedIn) {
                    navController.navigate(Screen.Permissions.route) {
                        popUpTo(Screen.Login.route) { inclusive = true }
                    }
                }
            }

            TwoFAScreen(
                email = email,
                password = password,
                onVerify = { code -> authViewModel.login(email, password, code) },
                onBack = { navController.popBackStack() },
                isLoading = uiState is AuthUiState.Loading,
                errorMessage = (uiState as? AuthUiState.Error)?.message,
            )
        }

        composable(Screen.Permissions.route) {
            val deviceViewModel: DeviceViewModel = hiltViewModel()
            val deviceState by deviceViewModel.state.collectAsState()

            LaunchedEffect(deviceState) {
                if (deviceState is DeviceState.Registered) {
                    deviceViewModel.syncParserRules()
                }
            }

            PermissionExplanationScreen(
                onGranted = {
                    deviceViewModel.registerIfNeeded()
                    navController.navigate(Screen.Dashboard.route) {
                        popUpTo(Screen.Permissions.route) { inclusive = true }
                    }
                },
                onDenied = {
                    deviceViewModel.registerIfNeeded()
                    navController.navigate(Screen.Dashboard.route) {
                        popUpTo(Screen.Permissions.route) { inclusive = true }
                    }
                }
            )
        }

        composable(Screen.Dashboard.route) {
            DashboardScreen(
                onViewLogs = { navController.navigate(Screen.SmsLogs.route) },
                onSettings = { navController.navigate(Screen.Settings.route) },
            )
        }

        composable(Screen.SmsLogs.route) {
            SmsLogsScreen(onBack = { navController.popBackStack() })
        }

        composable(Screen.Settings.route) {
            SettingsScreen(
                onBack = { navController.popBackStack() },
                onLogout = {
                    navController.navigate(Screen.Login.route) {
                        popUpTo(0) { inclusive = true }
                    }
                }
            )
        }
    }
}
