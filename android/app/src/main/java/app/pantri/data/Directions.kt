package app.pantri.data

/** Splits recipe directions into steps, the same way the website does (app/directions.py). */
object Directions {
    sealed interface Block
    data class Heading(val text: String) : Block
    data class Step(val n: Int, val text: String) : Block

    // "1." / "2)" / "3:" only when followed by a space, so "1.5 cups" isn't a step marker.
    private val MARKER = Regex("""^(?:step\s*\d{1,2}\b\s*[.):-]?|\d{1,2}[.):](?=\s)|[-*•·](?=\s))\s*""", RegexOption.IGNORE_CASE)
    private val ENDS_SENTENCE = Regex("""[.!?:)]['"”’]?$""")

    private fun normalize(text: String): String {
        val lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n").map { it.trimEnd() }
        return lines.joinToString("\n").replace(Regex("\n{3,}"), "\n\n").trim()
    }

    private fun chunks(text: String): List<List<String>> {
        val out = mutableListOf<List<String>>()
        for (para in normalize(text).split(Regex("\n\\s*\n"))) {
            val lines = para.split("\n").map { it.trim() }.filter { it.isNotEmpty() }
            val groups = mutableListOf<MutableList<String>>()
            for (line in lines) {
                if (groups.isNotEmpty() && MARKER.containsMatchIn(line) && MARKER.find(line)?.range?.first == 0) groups += mutableListOf(line)
                else if (groups.isEmpty()) groups += mutableListOf(line)
                else groups.last() += line
            }
            for (group in groups) {
                if (group.size > 1 && group.all { ENDS_SENTENCE.containsMatchIn(it) }) group.forEach { out += listOf(it) }
                else out += group
            }
        }
        return out
    }

    fun steps(text: String): List<Block> {
        val out = mutableListOf<Block>()
        var n = 0
        for (lines in chunks(text)) {
            val marked = MARKER.find(lines[0])?.range?.first == 0
            val first = if (marked) MARKER.replaceFirst(lines[0], "") else lines[0]
            val body = (listOf(first) + lines.drop(1)).joinToString("\n").trim()
            if (body.isEmpty()) continue
            if (!marked && "\n" !in body && body.length <= 60 && body.endsWith(":")) {
                out += Heading(body.dropLast(1).trim())
            } else {
                n += 1
                out += Step(n, body)
            }
        }
        return out
    }
}
