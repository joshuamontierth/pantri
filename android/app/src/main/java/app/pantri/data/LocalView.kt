package app.pantri.data

/** A list item as the phone shows it: from the server, possibly changed by queued ops (pending). */
data class LocalItem(
    val key: ItemKey,
    /** Stays the same when an item added offline gets its server id, so the list doesn't flicker. */
    val uiKey: String,
    val storeId: Long?,
    val name: String,
    val catalogId: Long?,
    /** Null when the quantity is text the server hasn't read yet. */
    val parts: List<Part>?,
    val qty: String,
    val qtyText: String,
    val note: String,
    val tags: List<String>,
    val checked: Boolean,
    val checkedAt: String?,
    val position: Int,
    val pending: Boolean = false,
)

data class LocalView(
    val householdId: Long,
    val householdName: String,
    val otherLabel: String,
    val stores: List<StoreDto>,
    val items: List<LocalItem>,
    val catalog: List<CatalogDto>,
    val recipes: List<RecipeDto>,
    val meals: List<MealDto> = emptyList(),
) {
    private val storeNames = stores.associate { it.id to it.name }
    private val catalogByLower = catalog.associateBy { it.name.lowercase() }
    val catalogById = catalog.associateBy { it.id }

    /** Store ids in tab order, then null for "Other". */
    val listIds: List<Long?> get() = stores.map { it.id } + listOf(null)

    fun storeName(id: Long?): String = if (id == null) otherLabel else storeNames[id] ?: otherLabel
    fun hasStore(id: Long?) = id == null || id in storeNames

    fun unchecked(storeId: Long?) = items.filter { !it.checked && it.storeId == storeId }
        .sortedWith(compareBy<LocalItem> { it.position }.thenBy { it.uiKey })

    fun checked(storeId: Long?) = items.filter { it.checked && it.storeId == storeId }
        .sortedWith(compareBy<LocalItem> { it.checkedAt ?: "" }.thenBy { it.uiKey })

    fun count(storeId: Long?) = items.count { !it.checked && it.storeId == storeId }

    fun catalogItem(name: String) = catalogByLower[name.trim().lowercase()]

    private val catalogByKey = catalog.reversed().associateBy { nameKey(it.name) }

    /** The catalog item a name means: the same name, or the same but for a plural (services.catalog_matcher). */
    fun matchCatalog(name: String) = catalogItem(name) ?: catalogByKey[nameKey(name)]

    private val recipeNames = recipes.associate { it.id to it.name }

    /** A meal's name: its recipe's name now, or what it was called (a deleted recipe, or no recipe). */
    fun mealName(meal: MealDto) = meal.recipeId?.let(recipeNames::get) ?: meal.title
    fun hasRecipe(meal: MealDto) = meal.recipeId != null && meal.recipeId in recipeNames

    /** Where an item usually comes from: its first-ranked store that still exists, else Other. */
    fun usualStore(name: String): Long? = catalogItem(name)?.ranks?.firstOrNull { it in storeNames }

    companion object {
        /** "Avocados" and "avocado" are the same item (services.name_key). */
        fun nameKey(name: String): String {
            val words = name.lowercase().split(Regex("\\s+")).filter { it.isNotEmpty() }
            if (words.isEmpty()) return ""
            return (words.dropLast(1) + singular(words.last())).joinToString(" ")
        }

        private fun singular(word: String): String {
            if (word.length > 4 && word.endsWith("ies")) return word.dropLast(3) + "y"
            for (suffix in listOf("sses", "ches", "shes", "xes", "zes")) if (word.endsWith(suffix)) return word.dropLast(2)
            if (word.length > 2 && word.endsWith("s") && !word.endsWith("ss")) return word.dropLast(1)
            return word
        }
    }
}

/**
 * The phone's view = the server's last snapshot with the queued ops replayed on top. This
 * mirrors what the server will do with them (app/routes/api.py), closely enough that the list
 * looks right offline; the server's answer replaces it as soon as they sync.
 */
object LocalApply {

    fun view(state: HouseholdState, ops: List<Op>, refs: Map<String, Long>): LocalView {
        val refForId = refs.entries.associate { (ref, id) -> id to ref }
        val items = state.items.map { it.toLocal(refForId[it.id]) }.toMutableList()
        val catalogByLower = state.catalog.associateBy { it.name.lowercase() }
        val alias = HashMap<String, ItemKey>() // our ref -> the item it was merged into

        fun resolve(key: ItemKey): ItemKey = when (key) {
            is ItemKey.Server -> key
            is ItemKey.Local -> alias[key.ref] ?: refs[key.ref]?.let { ItemKey.Server(it) } ?: key
        }

        fun indexOf(key: ItemKey): Int {
            val k = resolve(key)
            return items.indexOfFirst { it.key == k }
        }

        fun nextPosition(storeId: Long?) = (items.filter { it.storeId == storeId }.maxOfOrNull { it.position } ?: -1) + 1

        fun twinOf(storeId: Long?, name: String, catalogId: Long?, except: ItemKey?) = items.indexOfFirst {
            !it.checked && it.storeId == storeId && it.key != except &&
                ((catalogId != null && it.catalogId == catalogId) || it.name.equals(name, ignoreCase = true))
        }

        for (op in ops) {
            when (op) {
                is AddOp -> {
                    val cat = catalogByLower[op.name.trim().lowercase()]
                    val name = cat?.name ?: op.name.trim()
                    val parts = op.parts?.toParts() ?: if (op.qty.isNullOrBlank()) emptyList() else null
                    val incoming = LocalItem(
                        key = ItemKey.Local(op.ref), uiKey = "l${op.ref}", storeId = op.store, name = name,
                        catalogId = cat?.id, parts = parts, qty = parts?.let(Quantities::format) ?: op.qty!!.trim(),
                        qtyText = op.qty?.trim() ?: parts?.let(Quantities::format).orEmpty(), note = op.note.trim(),
                        tags = op.tags, checked = false, checkedAt = null, position = nextPosition(op.store), pending = true,
                    )
                    val t = twinOf(op.store, name, cat?.id, null)
                    if (t >= 0) {
                        items[t] = merge(items[t], incoming)
                        alias[op.ref] = items[t].key
                    } else {
                        items += incoming
                    }
                }

                is CheckOp -> {
                    val i = indexOf(op.item)
                    if (i < 0) continue
                    val item = items[i]
                    if (op.checked) {
                        items[i] = item.copy(checked = true, checkedAt = item.checkedAt.takeIf { item.checked } ?: op.at, pending = true)
                    } else {
                        val unchecked = item.copy(checked = false, checkedAt = null, pending = true)
                        val t = twinOf(item.storeId, item.name, item.catalogId, item.key)
                        if (t >= 0) {
                            items[t] = merge(items[t], unchecked)
                            items.removeAt(i)
                        } else {
                            items[i] = unchecked
                        }
                    }
                }

                is UpdateOp -> {
                    val i = indexOf(op.item)
                    if (i < 0) continue
                    val before = items[i]
                    val name = op.name.trim().ifEmpty { before.name }
                    val qtyText = op.qty.trim()
                    val sameQty = qtyText == before.qtyText
                    var item = before.copy(
                        name = name,
                        catalogId = if (name.equals(before.name, ignoreCase = true)) before.catalogId else catalogByLower[name.lowercase()]?.id,
                        parts = if (sameQty) before.parts else if (qtyText.isEmpty()) emptyList() else null,
                        qty = if (sameQty) before.qty else qtyText,
                        qtyText = qtyText,
                        note = op.note.trim(),
                        pending = true,
                    )
                    items.removeAt(i)
                    if (op.store != item.storeId) item = item.copy(storeId = op.store, position = nextPosition(op.store))
                    val t = if (item.checked) -1 else twinOf(item.storeId, item.name, item.catalogId, item.key)
                    if (t >= 0) items[t] = merge(items[t], item) else items.add(i.coerceAtMost(items.size), item)
                }

                is DeleteOp -> {
                    val i = indexOf(op.item)
                    if (i >= 0) items.removeAt(i)
                }

                is ReorderOp -> {
                    val wanted = op.items.map(::resolve)
                    val onList = items.filter { !it.checked && it.storeId == op.store }.sortedBy { it.position }
                    val ordered = wanted.mapNotNull { k -> onList.firstOrNull { it.key == k } }.distinct()
                    val all = ordered + onList.filter { it !in ordered }
                    all.forEachIndexed { pos, item ->
                        val i = items.indexOfFirst { it.key == item.key }
                        if (i >= 0) items[i] = items[i].copy(position = pos)
                    }
                }
            }
        }

        return LocalView(
            householdId = state.household.id,
            householdName = state.household.name,
            otherLabel = state.otherLabel,
            stores = state.stores,
            items = items,
            catalog = state.catalog,
            recipes = state.recipes,
            meals = state.meals,
        )
    }

    private fun merge(target: LocalItem, src: LocalItem): LocalItem {
        val parts = if (target.parts != null && src.parts != null) Quantities.combine(target.parts, src.parts) else null
        val qty = parts?.let(Quantities::format) ?: listOf(target.qty, src.qty).filter { it.isNotBlank() }.joinToString(" + ")
        val note = when {
            src.note.isBlank() || target.note.contains(src.note, ignoreCase = true) -> target.note
            target.note.isBlank() -> src.note
            else -> "${target.note}; ${src.note}"
        }
        return target.copy(
            parts = parts, qty = qty, qtyText = parts?.let(Quantities::format) ?: qty, note = note,
            tags = (target.tags + src.tags).distinct(), pending = true,
        )
    }

    private fun ItemDto.toLocal(ref: String?) = LocalItem(
        key = ItemKey.Server(id),
        uiKey = ref?.let { "l$it" } ?: "s$id",
        storeId = storeId,
        name = name,
        catalogId = catalogId,
        parts = quantities.toParts(),
        qty = qty,
        qtyText = qtyText,
        note = note,
        tags = tags,
        checked = checked,
        checkedAt = checkedAt,
        position = position,
    )
}
