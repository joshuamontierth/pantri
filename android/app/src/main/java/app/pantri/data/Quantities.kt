package app.pantri.data

import java.util.Locale
import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.roundToLong

/**
 * Display and merging of quantities, matching the server's app/quantities.py, so what the
 * phone shows offline is what the website will show once the change syncs.
 */
object Quantities {
    private val VOLUME = mapOf(
        "tsp" to 4.92892159375, "tbsp" to 14.78676478125, "fl oz" to 29.5735295625,
        "cup" to 236.5882365, "pt" to 473.176473, "qt" to 946.352946, "gal" to 3785.411784,
        "ml" to 1.0, "l" to 1000.0,
    )
    private val WEIGHT = mapOf("oz" to 28.349523125, "lb" to 453.59237, "g" to 1.0, "kg" to 1000.0)
    private val DISPLAY = mapOf("l" to "L")
    private val PLURAL_STANDARD = mapOf("cup" to "cups")
    /** Counts that read the same for many: "3 dozen", not "3 dozens". */
    private val SAME_PLURAL = setOf("dozen", "each")
    private val FRACTIONS = listOf(
        0.0 to "", 1 / 8.0 to "⅛", 1 / 4.0 to "¼", 1 / 3.0 to "⅓", 3 / 8.0 to "⅜", 1 / 2.0 to "½",
        5 / 8.0 to "⅝", 2 / 3.0 to "⅔", 3 / 4.0 to "¾", 7 / 8.0 to "⅞", 1.0 to "",
    )

    private fun family(unit: String) = when (unit) {
        in VOLUME -> VOLUME
        in WEIGHT -> WEIGHT
        else -> null
    }

    fun compatible(a: String, b: String) = a == b || (family(a) != null && family(a) === family(b))

    private fun convert(amount: Double, from: String, to: String): Double {
        if (from == to) return amount
        val fam = family(from)!!
        return amount * fam.getValue(from) / fam.getValue(to)
    }

    /** Merge b into a; compatible units are converted to a's unit. */
    fun combine(a: List<Part>, b: List<Part>): List<Part> {
        val result = a.toMutableList()
        for (part in b) {
            val i = result.indexOfFirst { compatible(it.unit, part.unit) }
            if (i >= 0) {
                val r = result[i]
                result[i] = r.copy(amount = r.amount + convert(part.amount, part.unit, r.unit))
            } else {
                result += part
            }
        }
        return result
    }

    fun scale(parts: List<Part>, multiplier: Double) = parts.map { it.copy(amount = it.amount * multiplier) }

    private fun roundFraction(x: Double): Pair<Long, String> {
        var whole = floor(x).toLong()
        val frac = x - whole
        val (value, symbol) = FRACTIONS.minBy { abs(it.first - frac) }
        if (value == 1.0) whole += 1
        return whole to symbol
    }

    fun formatAmount(amount: Double, unit: String = ""): String {
        if (unit == "g" || unit == "ml") {
            if (amount >= 10) return amount.roundToLong().toString()
            return String.format(Locale.US, "%.1f", amount).trimEnd('0').trimEnd('.').ifEmpty { "0" }
        }
        val (whole, symbol) = roundFraction(amount)
        if (whole == 0L && symbol.isEmpty()) return if (amount > 0) "⅛" else "0"
        if (whole == 0L) return symbol
        return "$whole$symbol"
    }

    private fun rounded(amount: Double, unit: String): Double {
        if (unit == "g" || unit == "ml") return amount
        val (whole, symbol) = roundFraction(amount)
        val frac = if (symbol.isEmpty()) 0.0 else FRACTIONS.first { it.second == symbol }.first
        return whole + frac
    }

    private fun pluralize(word: String): String = when {
        word.endsWith("s") || word.endsWith("x") || word.endsWith("z") || word.endsWith("ch") || word.endsWith("sh") -> word + "es"
        word.length > 1 && word.endsWith("y") && word[word.length - 2] !in "aeiou" -> word.dropLast(1) + "ies"
        else -> word + "s"
    }

    fun displayUnit(unit: String, amount: Double): String {
        if (unit.isEmpty()) return ""
        val plural = rounded(amount, unit) > 1.0 + 1e-9
        if (unit in VOLUME || unit in WEIGHT) {
            if (plural && unit in PLURAL_STANDARD) return PLURAL_STANDARD.getValue(unit)
            return DISPLAY[unit] ?: unit
        }
        return if (plural && unit !in SAME_PLURAL) pluralize(unit) else unit
    }

    fun formatPart(amount: Double, unit: String): String {
        val unitText = displayUnit(unit, amount)
        val num = formatAmount(amount, unit)
        return if (unitText.isEmpty()) num else "$num $unitText"
    }

    fun format(parts: List<Part>): String = parts.joinToString(" + ") { formatPart(it.amount, it.unit) }

    private val UNICODE = mapOf("½" to "1/2", "⅓" to "1/3", "⅔" to "2/3", "¼" to "1/4", "¾" to "3/4", "⅛" to "1/8", "⅜" to "3/8", "⅝" to "5/8", "⅞" to "7/8")
    private val NUMBER = Regex("""^(\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+\.\d*|\.\d+|\d+)$""")

    /** "2", "1/2", "1 1/2", "0.75", "1½" (app/quantities.py parse_amount). Null if blank or not a number. */
    fun parseAmount(text: String): Double? {
        var t = text.replace("⁄", "/")
        for ((ch, frac) in UNICODE) t = t.replace(ch, " $frac")
        t = t.trim()
        val m = NUMBER.matchEntire(t) ?: return null
        var total = 0.0
        for (part in m.groupValues[1].replace(Regex("""\s*/\s*"""), "/").split(Regex("""\s+"""))) {
            if ("/" in part) {
                val (n, d) = part.split("/").map { it.toDouble() }
                if (d == 0.0) return null
                total += n / d
            } else total += part.toDouble()
        }
        return total
    }
}
