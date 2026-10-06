package app.shoppinglist.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import app.shoppinglist.R

/** The website's "notepad & ballpoint" tokens (app/static/css/app.css). */
@Immutable
data class AppColors(
    val paper: Color,
    val sheet: Color,
    val field: Color,
    val ink: Color,
    val ink2: Color,
    val ink3: Color,
    val rule: Color,
    val rule2: Color,
    val accent: Color,
    val accentInk: Color,
    val accentWash: Color,
    val primary: Color,
    val primaryInk: Color,
    val danger: Color,
    val dangerWash: Color,
    val successInk: Color,
    val warn: Color,
    val dark: Boolean,
)

val LightColors = AppColors(
    paper = Color(0xFFF5F3EE), sheet = Color(0xFFFCFBF8), field = Color(0xFFFFFFFF),
    ink = Color(0xFF1C1B18), ink2 = Color(0xFF6F6B62), ink3 = Color(0xFF8C887E),
    rule = Color(0xFFDDD9CF), rule2 = Color(0xFFC9C4B7),
    accent = Color(0xFF3350D4), accentInk = Color(0xFFFFFFFF), accentWash = Color(0xFFE9ECFB),
    primary = Color(0xFF1C1B18), primaryInk = Color(0xFFF5F3EE),
    danger = Color(0xFFB3261E), dangerWash = Color(0xFFFBEDEB), successInk = Color(0xFF1F6B3A), warn = Color(0xFF8A5A00),
    dark = false,
)

val DarkColors = AppColors(
    paper = Color(0xFF141412), sheet = Color(0xFF1E1D1A), field = Color(0xFF1C1B19),
    ink = Color(0xFFECEAE4), ink2 = Color(0xFFA29F96), ink3 = Color(0xFF8A877F),
    rule = Color(0xFF2E2C28), rule2 = Color(0xFF3D3A35),
    accent = Color(0xFF93A8FF), accentInk = Color(0xFF0F1320), accentWash = Color(0xFF1E2440),
    primary = Color(0xFFECEAE4), primaryInk = Color(0xFF141412),
    danger = Color(0xFFFF8A80), dangerWash = Color(0xFF2A1917), successInk = Color(0xFF8FD6A6), warn = Color(0xFFE0B263),
    dark = true,
)

val LocalAppColors = staticCompositionLocalOf { LightColors }

val colors: AppColors
    @Composable get() = LocalAppColors.current

@OptIn(ExperimentalTextApi::class)
private fun grotesk(weight: Int) = Font(
    R.font.schibsted_grotesk,
    weight = FontWeight(weight),
    variationSettings = FontVariation.Settings(FontVariation.weight(weight)),
)

val Grotesk = FontFamily(grotesk(400), grotesk(500), grotesk(600), grotesk(700), grotesk(800), grotesk(900))

private fun Typography.withFont(family: FontFamily): Typography {
    fun TextStyle.f() = copy(fontFamily = family)
    return copy(
        displayLarge = displayLarge.f(), displayMedium = displayMedium.f(), displaySmall = displaySmall.f(),
        headlineLarge = headlineLarge.f(), headlineMedium = headlineMedium.f(), headlineSmall = headlineSmall.f(),
        titleLarge = titleLarge.f(), titleMedium = titleMedium.f(), titleSmall = titleSmall.f(),
        bodyLarge = bodyLarge.f(), bodyMedium = bodyMedium.f(), bodySmall = bodySmall.f(),
        labelLarge = labelLarge.f(), labelMedium = labelMedium.f(), labelSmall = labelSmall.f(),
    )
}

@Composable
fun ShoppingTheme(content: @Composable () -> Unit) {
    val c = if (isSystemInDarkTheme()) DarkColors else LightColors
    val scheme = if (c.dark) {
        darkColorScheme(
            primary = c.primary, onPrimary = c.primaryInk, secondary = c.accent, onSecondary = c.accentInk,
            background = c.paper, onBackground = c.ink, surface = c.paper, onSurface = c.ink,
            surfaceVariant = c.sheet, onSurfaceVariant = c.ink2, surfaceContainerLow = c.sheet,
            surfaceContainer = c.sheet, surfaceContainerHigh = c.sheet, surfaceContainerHighest = c.field,
            outline = c.rule2, outlineVariant = c.rule, error = c.danger, inverseSurface = c.ink, inverseOnSurface = c.paper,
            inversePrimary = c.accent,
        )
    } else {
        lightColorScheme(
            primary = c.primary, onPrimary = c.primaryInk, secondary = c.accent, onSecondary = c.accentInk,
            background = c.paper, onBackground = c.ink, surface = c.paper, onSurface = c.ink,
            surfaceVariant = c.sheet, onSurfaceVariant = c.ink2, surfaceContainerLow = c.sheet,
            surfaceContainer = c.sheet, surfaceContainerHigh = c.sheet, surfaceContainerHighest = c.field,
            outline = c.rule2, outlineVariant = c.rule, error = c.danger, inverseSurface = c.ink, inverseOnSurface = c.paper,
            inversePrimary = Color(0xFFB9C6FF),
        )
    }
    CompositionLocalProvider(LocalAppColors provides c) {
        MaterialTheme(colorScheme = scheme, typography = Typography().withFont(Grotesk), content = content)
    }
}
