package app.shoppinglist.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalApplyTest {
    private val costco = StoreDto(1, "Costco")
    private val smiths = StoreDto(2, "Smith's")

    private fun item(id: Long, name: String, store: Long?, qty: List<Part> = emptyList(), pos: Int = id.toInt(), checked: Boolean = false, catalog: Long? = null) =
        ItemDto(
            id = id, storeId = store, name = name, catalogId = catalog, quantities = qty.toJson(),
            qty = Quantities.format(qty), qtyText = Quantities.format(qty), checked = checked,
            checkedAt = if (checked) "2026-10-05T10:00:00" else null, position = pos,
        )

    private fun state(vararg items: ItemDto) = HouseholdState(
        household = Household(7, "Home"),
        stores = listOf(costco, smiths),
        items = items.toList(),
        catalog = listOf(CatalogDto(10, "Milk", listOf(1)), CatalogDto(11, "Eggs", listOf(2, 1))),
    )

    @Test
    fun offlineAddsMergeLikeTheServer() {
        val s = state(item(1, "Milk", 1, listOf(Part(1.0, "cup")), catalog = 10))
        val ops = listOf(
            AddOp(opId = "a", ref = "r1", name = "milk", parts = listOf(Part(4.0, "tbsp")).toJson(), store = 1),
            AddOp(opId = "b", ref = "r2", name = "Batteries", qty = "a few", store = null),
            AddOp(opId = "c", ref = "r3", name = "Bread", qty = "2", store = 2),
        )
        val v = LocalApply.view(s, ops, emptyMap())
        val milk = v.unchecked(1).single()
        assertEquals("1¼ cups", milk.qty)
        assertTrue(milk.pending)
        assertEquals(listOf("Batteries"), v.unchecked(null).map { it.name })
        assertEquals("a few", v.unchecked(null).single().qty) // the server will read it; shown as typed
        assertEquals("2", v.unchecked(2).single().qty)
    }

    @Test
    fun laterOpsFollowAnItemAddedOffline() {
        val s = state()
        val ops = listOf(
            AddOp(opId = "a", ref = "r1", name = "Eggs", qty = "12", store = 2),
            CheckOp(opId = "b", item = ItemKey.Local("r1"), checked = true, at = "2026-10-05T11:00:00"),
        )
        val v = LocalApply.view(s, ops, emptyMap())
        assertTrue(v.unchecked(2).isEmpty())
        assertEquals("Eggs", v.checked(2).single().name)
        assertEquals(11L, v.checked(2).single().catalogId)
    }

    @Test
    fun refsLearnedFromTheServerKeepItemsSteady() {
        // r1 synced as item 5; a queued edit still names it by ref.
        val s = state(item(5, "Eggs", 2, catalog = 11))
        val ops = listOf(UpdateOp(opId = "u", item = ItemKey.Local("r1"), name = "Eggs", qty = "6", note = "brown", store = 1))
        val v = LocalApply.view(s, ops, mapOf("r1" to 5L))
        val eggs = v.unchecked(1).single()
        assertEquals("6", eggs.qty)
        assertEquals("brown", eggs.note)
        assertEquals("lr1", eggs.uiKey) // same key as before it synced, so the row doesn't flicker
        assertTrue(v.unchecked(2).isEmpty())
    }

    @Test
    fun deleteReorderAndUncheckMerge() {
        val s = state(
            item(1, "A", 1, pos = 0), item(2, "B", 1, pos = 1), item(3, "C", 1, pos = 2),
            item(4, "Milk", 1, listOf(Part(1.0, "cup")), checked = true, catalog = 10),
        )
        var v = LocalApply.view(s, listOf(ReorderOp(opId = "r", store = 1, items = listOf(ItemKey.Server(3), ItemKey.Server(1)))), emptyMap())
        assertEquals(listOf("C", "A", "B"), v.unchecked(1).map { it.name })

        v = LocalApply.view(s, listOf(DeleteOp(opId = "d", item = ItemKey.Server(2))), emptyMap())
        assertEquals(listOf("A", "C"), v.unchecked(1).map { it.name })

        // Milk re-added while the old line was checked; unchecking folds them together.
        val ops = listOf(
            AddOp(opId = "a", ref = "m", name = "Milk", qty = null, parts = listOf(Part(1.0, "cup")).toJson(), store = 1),
            CheckOp(opId = "c", item = ItemKey.Server(4), checked = false),
        )
        v = LocalApply.view(s, ops, emptyMap())
        assertEquals("2 cups", v.unchecked(1).single { it.name == "Milk" }.qty)
        assertTrue(v.checked(1).isEmpty())
    }

    @Test
    fun opsOnItemsSomeoneElseRemovedAreIgnored() {
        val v = LocalApply.view(state(), listOf(CheckOp(opId = "c", item = ItemKey.Server(99), checked = true)), emptyMap())
        assertTrue(v.items.isEmpty())
    }

    @Test
    fun usualStoreSkipsDeletedStores() {
        val s = state().copy(catalog = listOf(CatalogDto(1, "Rice", listOf(42, 2))))
        val v = LocalApply.view(s, emptyList(), emptyMap())
        assertEquals(2L, v.usualStore("rice"))
        assertEquals(null, v.usualStore("Unknown"))
    }

    @Test
    fun opsSurviveAJsonRoundTrip() {
        val ops = listOf<Op>(
            AddOp(opId = "a", ref = "r", name = "Milk", qty = "1 gal", store = null),
            CheckOp(opId = "c", item = ItemKey.Server(3), checked = true),
            UpdateOp(opId = "u", item = ItemKey.Local("r"), name = "Milk", qty = "", note = "", store = 2),
        )
        val text = AppJson.encodeToString(Outbox.serializer(), Outbox(ops, mapOf("r" to 4L)))
        assertTrue(text.contains("\"type\":\"add\"") && text.contains("\"item\":3") && text.contains("\"item\":\"r\""))
        assertTrue(text.contains("\"store\":null")) // null = the Other list, so it must be sent
        assertEquals(ops, AppJson.decodeFromString(Outbox.serializer(), text).ops)
    }
}

class QuantitiesTest {
    @Test
    fun formatsLikeTheWebsite() {
        assertEquals("1½ cups", Quantities.formatPart(1.5, "cup"))
        assertEquals("1 cup", Quantities.formatPart(1.0, "cup"))
        assertEquals("¾ tsp", Quantities.formatPart(0.75, "tsp"))
        assertEquals("250 g", Quantities.formatPart(250.0, "g"))
        assertEquals("2 cloves", Quantities.formatPart(2.0, "clove"))
        assertEquals("1 L", Quantities.formatPart(1.0, "l"))
        assertEquals("⅛", Quantities.formatAmount(0.01))
        assertEquals("1⅛ cups + 1 lb", Quantities.format(Quantities.combine(listOf(Part(1.0, "cup")), listOf(Part(2.0, "tbsp"), Part(1.0, "lb")))))
        assertEquals("1¼ gal", Quantities.format(Quantities.combine(listOf(Part(1.0, "gal")), listOf(Part(4.0, "cup")))))
        assertEquals("2 gal", Quantities.formatPart(2.0, "gal"))
        assertEquals("3 dozen", Quantities.formatPart(3.0, "dozen"))
    }
}

class DirectionsTest {
    @Test
    fun splitsStepsLikeTheWebsite() {
        val steps = Directions.steps("1. Preheat oven.\n2) Mix 1.5 cups flour\nwith sugar\n\nFor the glaze:\n\nWhisk.\n\nStep 3: Drizzle.")
        assertEquals(
            listOf(
                Directions.Step(1, "Preheat oven."),
                Directions.Step(2, "Mix 1.5 cups flour\nwith sugar"),
                Directions.Heading("For the glaze"),
                Directions.Step(3, "Whisk."),
                Directions.Step(4, "Drizzle."),
            ),
            steps,
        )
        assertEquals(listOf("Boil water.", "Add pasta.", "Drain!"), Directions.steps("Boil water.\nAdd pasta.\nDrain!").map { (it as Directions.Step).text })
        val single = Directions.steps("In a bowl, use a mixer on low\nspeed to combine the milk")
        assertEquals(1, single.size)
        assertFalse(single[0] is Directions.Heading)
    }
}
