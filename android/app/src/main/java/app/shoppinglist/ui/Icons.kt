package app.shoppinglist.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/** The website's stroke icons (app/templating.py), on the same 24px grid. Tinted by Icon(). */
object AppIcons {
    val Check = icon("M5 12.5l4.5 4.5L19 7.5")
    val Plus = icon("M12 5v14M5 12h14")
    val Minus = icon("M5 12h14")
    val Close = icon("M6 6l12 12M18 6L6 18")
    val Back = icon("M15 6l-6 6 6 6")
    val ChevronRight = icon("M9 6l6 6-6 6")
    val ChevronDown = icon("M6 9l6 6 6-6")
    val Trash = icon("M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3")
    val Search = icon(circle(11f, 11f, 6.5f), "M16 16l4 4")
    val Gear = icon(
        circle(12f, 12f, 3f),
        "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
    )
    val Grip = icon(
        circle(9f, 6f, 0.9f), circle(15f, 6f, 0.9f), circle(9f, 12f, 0.9f),
        circle(15f, 12f, 0.9f), circle(9f, 18f, 0.9f), circle(15f, 18f, 0.9f),
        width = 2.2f,
    )
    val External = icon("M14 5h5v5M19 5l-8 8", "M17 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h4")
    val Sun = icon(circle(12f, 12f, 4f), "M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4")
    val CloudOff = icon("M3 3l18 18", "M8.5 8.6A5 5 0 0 0 6.5 18H17m3.2-1.6A4 4 0 0 0 17 10h-1A6 6 0 0 0 10.4 6.2")
    val Refresh = icon("M20 12a8 8 0 1 1-2.34-5.66L20 8.5", "M20 4v4.5h-4.5")
    val Import = icon("M12 4v11M7.5 10.5 12 15l4.5-4.5", "M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3")
    val Camera = icon(
        "M3 8.5A2.5 2.5 0 0 1 5.5 6H7l1.6-2h6.8L17 6h1.5A2.5 2.5 0 0 1 21 8.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z",
        circle(12f, 12.5f, 3.6f),
    )
    val Image = icon("M5.5 4h13A2.5 2.5 0 0 1 21 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5v-11A2.5 2.5 0 0 1 5.5 4z", circle(9f, 10f, 1.8f), "M21 16l-5-5-9 9")
    val Scan = icon(
        "M4 8V6.5A2.5 2.5 0 0 1 6.5 4H8M16 4h1.5A2.5 2.5 0 0 1 20 6.5V8M20 16v1.5a2.5 2.5 0 0 1-2.5 2.5H16M8 20H6.5A2.5 2.5 0 0 1 4 17.5V16",
        "M8.5 9h7M8.5 12h7M8.5 15h4.5",
    )
    val Paste = icon(
        "M7.5 4.5h9A2.5 2.5 0 0 1 19 7v11a2.5 2.5 0 0 1-2.5 2.5h-9A2.5 2.5 0 0 1 5 18V7a2.5 2.5 0 0 1 2.5-2.5z",
        "M9 4.5V4a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 4v.5", "M9 10h6M9 13.5h6M9 17h3.5",
    )
    val Link = icon("M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1.2 1.2", "M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1.2-1.2")
    val Book = icon("M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z", "M5 17a3 3 0 0 1 3-3h11")

    private fun circle(cx: Float, cy: Float, r: Float) =
        "M${cx - r} $cy a$r $r 0 1 0 ${2 * r} 0 a$r $r 0 1 0 ${-2 * r} 0"

    private fun icon(vararg paths: String, width: Float = 1.9f): ImageVector =
        ImageVector.Builder(defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f).apply {
            for (d in paths) {
                addPath(
                    pathData = addPathNodes(d),
                    stroke = SolidColor(Color.Black),
                    strokeLineWidth = width,
                    strokeLineCap = StrokeCap.Round,
                    strokeLineJoin = StrokeJoin.Round,
                )
            }
        }.build()
}
