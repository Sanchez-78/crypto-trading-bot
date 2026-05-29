package com.cryptomaster.v5bot.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val DarkColorScheme = darkColorScheme(
    primary = androidx.compose.material3.Color(0xFF4CAF50),
    secondary = androidx.compose.material3.Color(0xFF2196F3),
    tertiary = androidx.compose.material3.Color(0xFFFF9800),
    background = androidx.compose.material3.Color(0xFF121212),
    surface = androidx.compose.material3.Color(0xFF1E1E1E),
    error = androidx.compose.material3.Color(0xFFF44336)
)

private val LightColorScheme = lightColorScheme(
    primary = androidx.compose.material3.Color(0xFF4CAF50),
    secondary = androidx.compose.material3.Color(0xFF2196F3),
    tertiary = androidx.compose.material3.Color(0xFFFF9800),
    background = androidx.compose.material3.Color(0xFFFAFAFA),
    surface = androidx.compose.material3.Color(0xFFFFFFFF),
    error = androidx.compose.material3.Color(0xFFF44336)
)

@Composable
fun V5BotTheme(
    darkTheme: Boolean = true,
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    MaterialTheme(
        colorScheme = colorScheme,
        content = content
    )
}
