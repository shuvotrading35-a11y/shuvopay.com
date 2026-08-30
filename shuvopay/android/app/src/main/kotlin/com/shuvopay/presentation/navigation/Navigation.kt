package com.shuvopay.presentation.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.shuvopay.presentation.screens.auth.LoginScreen
import com.shuvopay.presentation.screens.auth.PermissionExplanationScreen
import com.shuvopay.presentation.screens.dashboard.DashboardScreen

sealed class Screen(val route: String) {
    data object Splash : Screen("splash")
    data object Login : Screen("login")
    data object Permissions : Screen("permissions")
    data object Dashboard : Screen("dashboard")
    data object SmsLogs : Screen("sms_logs")
    data object Settings : Screen("settings")
    data object DeviceStatus : Screen("device_status")
}

@Composable
fun AppNavHost(
    navController: NavHostController = rememberNavController(),
    startDestination: String = Screen.Login.route,
) {
    NavHost(navController = navController, startDestination = startDestination) {

        composable(Screen.Login.route) {
            LoginScreen(
                onLoginSuccess = {
                    navController.navigate(Screen.Permissions.route) {
                        popUpTo(Screen.Login.route) { inclusive = true }
                    }
                }
            )
        }

        composable(Screen.Permissions.route) {
            PermissionExplanationScreen(
                onGranted = {
                    navController.navigate(Screen.Dashboard.route) {
                        popUpTo(Screen.Permissions.route) { inclusive = true }
                    }
                },
                onDenied = {
                    // Navigate to dashboard anyway — limited functionality
                    navController.navigate(Screen.Dashboard.route) {
                        popUpTo(Screen.Permissions.route) { inclusive = true }
                    }
                }
            )
        }

        composable(Screen.Dashboard.route) {
            DashboardScreen(
                onViewLogs = { navController.navigate(Screen.SmsLogs.route) },
            )
        }
    }
}
