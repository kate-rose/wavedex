package com.wavedex.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val WaveDexDarkColors = darkColorScheme(
    primary = CandleGold,
    onPrimary = ForestNight,
    primaryContainer = Color(0xFF4A3B10),
    onPrimaryContainer = MoonlitFog,
    secondary = IndigoMist,
    onSecondary = ForestNight,
    tertiary = MossWhisper,
    onTertiary = MoonlitFog,
    background = ForestNight,
    onBackground = MoonlitFog,
    surface = PineShadow,
    onSurface = MoonlitFog,
    surfaceVariant = Color(0xFF243240),
    onSurfaceVariant = Color(0xFFB8C5CE),
    outline = Color(0xFF5C6B78),
)

@Composable
fun WaveDexTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = WaveDexDarkColors,
        typography = WaveDexTypography,
        content = content,
    )
}
