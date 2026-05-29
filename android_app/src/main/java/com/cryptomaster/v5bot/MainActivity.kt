package com.cryptomaster.v5bot

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.cryptomaster.v5bot.ui.screens.LearningMetricsScreen
import com.cryptomaster.v5bot.ui.screens.MetricsScreen
import com.cryptomaster.v5bot.ui.theme.V5BotTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            V5BotTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    val navController = rememberNavController()

                    NavHost(navController = navController, startDestination = "metrics") {
                        composable("metrics") {
                            MetricsScreen()
                        }
                        composable("learning") {
                            LearningMetricsScreen()
                        }
                    }
                }
            }
        }
    }
}
