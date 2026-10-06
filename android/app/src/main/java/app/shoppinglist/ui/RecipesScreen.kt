package app.shoppinglist.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shoppinglist.data.Directions
import app.shoppinglist.data.LocalView as Household
import app.shoppinglist.data.Part
import app.shoppinglist.data.Quantities
import app.shoppinglist.data.RecipeDto
import app.shoppinglist.data.SyncStatus
import java.net.URI

@Composable
fun RecipesScreen(vm: AppViewModel, view: Household, status: SyncStatus, snackbar: SnackbarHostState) {
    var query by rememberSaveable { mutableStateOf("") }
    var choosing by rememberSaveable { mutableStateOf(false) }
    val chosen = remember { mutableStateMapOf<Long, Boolean>() }
    val shown = view.recipes.filter { query.isBlank() || it.name.contains(query.trim(), ignoreCase = true) }
    val picked = view.recipes.filter { chosen[it.id] == true }
    val uri = LocalUriHandler.current

    Scaffold(
        containerColor = colors.paper,
        topBar = { TopNav(Screen.Recipes, status, onTab = vm::tab, onSettings = { vm.go(Screen.Settings) }) },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (choosing) {
                Box(Modifier.background(colors.paper).navigationBarsPadding().padding(16.dp)) {
                    PrimaryButton(
                        if (picked.isEmpty()) "Pick recipes" else "Add ${picked.size} recipe${if (picked.size == 1) "" else "s"} to lists",
                        onClick = { vm.go(Screen.Plan(picked.map { it.id })) },
                        enabled = picked.isNotEmpty(),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp)) {
            item {
                Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    PageTitle("Recipes", Modifier.weight(1f))
                    if (view.recipes.isNotEmpty()) {
                        OutlineButton(if (choosing) "Done" else "Choose", onClick = { choosing = !choosing; if (!choosing) chosen.clear() }, small = true)
                    }
                }
                if (view.recipes.isEmpty()) {
                    Text(
                        "No recipes yet. Add them on the website, where you can also import them from photos or links.",
                        color = colors.ink2, fontSize = 16.sp,
                    )
                    Spacer(Modifier.size(16.dp))
                    OutlineButton("Open the website", onClick = { runCatching { uri.openUri(vm.webUrl("/h/${view.householdId}/recipes")) } }, icon = AppIcons.External)
                } else {
                    Field(
                        query, { query = it }, placeholder = "Search ${view.recipes.size} recipes",
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    )
                    Spacer(Modifier.size(12.dp))
                    HorizontalDivider(color = colors.rule)
                }
            }
            items(shown, key = { it.id }) { r ->
                Row(
                    Modifier.fillMaxWidth().clickable {
                        if (choosing) chosen[r.id] = chosen[r.id] != true else vm.go(Screen.Recipe(r.id))
                    }.heightIn(min = 64.dp).padding(vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (choosing) {
                        CheckBox(chosen[r.id] == true, { chosen[r.id] = chosen[r.id] != true }, Modifier.padding(end = 4.dp))
                    }
                    Column(Modifier.weight(1f)) {
                        Text(r.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                        val n = r.ingredients.size
                        Text("$n ingredient${if (n == 1) "" else "s"}", fontSize = 14.sp, color = colors.ink2)
                    }
                    if (!choosing) Icon(AppIcons.ChevronRight, null, Modifier.size(18.dp), tint = colors.ink3)
                }
                HorizontalDivider(color = colors.rule)
            }
        }
    }
}

@Composable
fun RecipeScreen(vm: AppViewModel, view: Household, recipeId: Long, snackbar: SnackbarHostState) {
    val recipe = view.recipes.firstOrNull { it.id == recipeId }
    val uri = LocalUriHandler.current
    Scaffold(
        containerColor = colors.paper,
        topBar = { BackBar("Recipes", onBack = { vm.back() }) },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        if (recipe == null) {
            Box(Modifier.padding(padding)) { EmptyState("Recipe not found", "It may have been deleted.") }
            return@Scaffold
        }
        val steps = remember(recipe.directions) { Directions.steps(recipe.directions) }
        val done = remember(recipe.id) { mutableStateMapOf<Int, Boolean>() }
        var keepOn by rememberSaveable { mutableStateOf(false) }
        KeepScreenOn(keepOn)

        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 40.dp)) {
            item {
                PageTitle(recipe.name, Modifier.padding(top = 4.dp, bottom = 8.dp))
                if (recipe.sourceUrl.isNotBlank()) {
                    val host = runCatching { URI(recipe.sourceUrl).host?.removePrefix("www.") }.getOrNull() ?: recipe.sourceUrl
                    Row(
                        Modifier.clip(RoundedCornerShape(6.dp)).clickable { runCatching { uri.openUri(recipe.sourceUrl) } }.padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(host, color = colors.accent, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                        Spacer(Modifier.width(4.dp))
                        Icon(AppIcons.External, null, Modifier.size(15.dp), tint = colors.accent)
                    }
                }
                Spacer(Modifier.size(12.dp))
                PrimaryButton("Add to lists", onClick = { vm.go(Screen.Plan(listOf(recipe.id))) }, modifier = Modifier.fillMaxWidth())
                SectionLabel("Ingredients", Modifier.padding(top = 28.dp, bottom = 10.dp))
                HorizontalDivider(color = colors.rule)
            }
            items(recipe.ingredients) { ing ->
                val ranks = ing.catalogId?.let { view.catalogById[it]?.ranks }.orEmpty().filter { view.hasStore(it) }
                Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(ing.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                        Text(
                            if (ranks.isEmpty()) view.otherLabel else ranks.joinToString(" › ") { view.storeName(it) },
                            fontSize = 14.sp, color = colors.ink2,
                        )
                    }
                    if (ing.qty.isNotBlank()) Text(ing.qty, fontWeight = FontWeight.SemiBold, color = colors.accent, fontSize = 16.sp)
                }
                HorizontalDivider(color = colors.rule)
            }
            item {
                Row(Modifier.fillMaxWidth().padding(top = 28.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    SectionLabel("Directions", Modifier.weight(1f))
                    if (steps.isNotEmpty()) {
                        Row(
                            Modifier.clip(RadiusShape)
                                .background(if (keepOn) colors.accentWash else colors.paper)
                                .border(1.dp, if (keepOn) colors.accent else colors.rule2, RadiusShape)
                                .clickable { keepOn = !keepOn }
                                .padding(horizontal = 12.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(AppIcons.Sun, null, Modifier.size(17.dp), tint = if (keepOn) colors.ink else colors.ink2)
                            Spacer(Modifier.width(6.dp))
                            Text(if (keepOn) "Screen stays on" else "Keep screen on", fontSize = 14.sp, color = if (keepOn) colors.ink else colors.ink2, fontWeight = FontWeight.SemiBold)
                        }
                    }
                }
                if (steps.isEmpty()) {
                    Text("No directions yet. Add them on the website with Add details.", color = colors.ink2, fontSize = 15.sp)
                } else if (steps.size == 1 && steps[0] is Directions.Step) {
                    Text((steps[0] as Directions.Step).text, fontSize = 17.sp, lineHeight = 27.sp, color = colors.ink)
                } else {
                    HorizontalDivider(color = colors.rule)
                }
            }
            if (steps.size > 1 || (steps.size == 1 && steps[0] is Directions.Heading)) {
                items(steps.size) { i ->
                    when (val b = steps[i]) {
                        is Directions.Heading -> Text(b.text, Modifier.padding(top = 20.dp, bottom = 8.dp), fontSize = 18.sp, fontWeight = FontWeight.Bold, color = colors.ink)
                        is Directions.Step -> {
                            val isDone = done[b.n] == true
                            Row(Modifier.fillMaxWidth().clickable { done[b.n] = !isDone }.padding(vertical = 14.dp)) {
                                Box(
                                    Modifier.size(30.dp).clip(CircleShape)
                                        .background(if (isDone) colors.accent else colors.paper)
                                        .border(2.dp, if (isDone) colors.accent else colors.ink, CircleShape),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    if (isDone) Icon(AppIcons.Check, null, Modifier.size(18.dp), tint = colors.accentInk)
                                    else Text("${b.n}", fontSize = 14.sp, fontWeight = FontWeight.ExtraBold, color = colors.ink)
                                }
                                Spacer(Modifier.width(14.dp))
                                Text(b.text, Modifier.weight(1f), fontSize = 17.sp, lineHeight = 26.sp, color = if (isDone) colors.ink3 else colors.ink)
                            }
                            HorizontalDivider(color = colors.rule)
                        }
                    }
                }
            }
            item {
                Spacer(Modifier.size(28.dp))
                OutlineButton(
                    "Edit on the website",
                    onClick = { runCatching { uri.openUri(vm.webUrl("/h/${view.householdId}/recipes/${recipe.id}")) } },
                    icon = AppIcons.External,
                )
            }
        }
    }
}

@Composable
private fun KeepScreenOn(on: Boolean) {
    val view = LocalView.current
    DisposableEffect(on) {
        view.keepScreenOn = on
        onDispose { view.keepScreenOn = false }
    }
}

/** One ingredient across the chosen recipes. */
private data class PlanRow(val key: String, val name: String, val catalogId: Long?, val parts: List<Part>, val tags: List<String>, val ranks: List<Long>)

private val MULTIPLIERS = listOf(0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)

private fun multText(m: Double) = "×" + Quantities.formatAmount(m)

private fun planRows(view: Household, recipes: List<RecipeDto>, mult: Map<Long, Double>): List<PlanRow> {
    val rows = LinkedHashMap<String, PlanRow>()
    for (r in recipes) {
        val m = mult[r.id] ?: 1.0
        for (ing in r.ingredients) {
            val key = ing.catalogId?.let { "c$it" } ?: "n${ing.name.lowercase()}"
            val parts = if (ing.amount != null) listOf(Part(ing.amount * m, ing.unit)) else emptyList()
            val existing = rows[key]
            rows[key] = if (existing == null) {
                val ranks = ing.catalogId?.let { view.catalogById[it]?.ranks }.orEmpty().filter { view.hasStore(it) && it in view.stores.map { s -> s.id } }
                PlanRow(key, ing.name, ing.catalogId, parts, listOf(r.name), ranks)
            } else {
                existing.copy(parts = Quantities.combine(existing.parts, parts), tags = (existing.tags + r.name).distinct())
            }
        }
    }
    return rows.values.toList()
}

private fun ordinal(n: Int) = when {
    n % 100 in 11..13 -> "${n}th"
    n % 10 == 1 -> "${n}st"
    n % 10 == 2 -> "${n}nd"
    n % 10 == 3 -> "${n}rd"
    else -> "${n}th"
}

@Composable
fun PlanScreen(vm: AppViewModel, view: Household, recipeIds: List<Long>, snackbar: SnackbarHostState) {
    val recipes = view.recipes.filter { it.id in recipeIds }
    val mult = remember { mutableStateMapOf<Long, Double>() }
    val include = remember { mutableStateMapOf<String, Boolean>() }
    val storeChoice = remember { mutableStateMapOf<String, Long?>() }
    val rows = planRows(view, recipes, mult)
    fun storeFor(row: PlanRow): Long? = if (storeChoice.containsKey(row.key)) storeChoice[row.key] else row.ranks.firstOrNull()
    val picked = rows.filter { include[it.key] == true }

    Scaffold(
        containerColor = colors.paper,
        topBar = { BackBar(if (recipes.size == 1) recipes[0].name else "Recipes", onBack = { vm.back() }) },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            Box(Modifier.background(colors.paper).navigationBarsPadding().padding(16.dp)) {
                val stores = picked.map { view.storeName(storeFor(it)) }.distinct()
                PrimaryButton(
                    if (picked.isEmpty()) "Check what you need" else "Add ${picked.size} item${if (picked.size == 1) "" else "s"}",
                    sub = stores.takeIf { it.isNotEmpty() }?.let { "to " + it.joinToString(", ") },
                    enabled = picked.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth(),
                    onClick = {
                        vm.addFromRecipes(picked.map { PlanAdd(it.name, it.parts, storeFor(it), it.tags) }, view::storeName)
                        vm.back()
                    },
                )
            }
        },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp)) {
            item {
                PageTitle("Add to lists", Modifier.padding(top = 4.dp, bottom = 12.dp))
                HorizontalDivider(color = colors.ink, thickness = 2.dp)
                for (r in recipes) {
                    val m = mult[r.id] ?: 1.0
                    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(r.name, Modifier.weight(1f), fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = colors.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Stepper(multText(m),
                            onMinus = { MULTIPLIERS.lastOrNull { it < m - 1e-9 }?.let { mult[r.id] = it } },
                            onPlus = { MULTIPLIERS.firstOrNull { it > m + 1e-9 }?.let { mult[r.id] = it } })
                    }
                    HorizontalDivider(color = colors.rule)
                }
                Row(Modifier.fillMaxWidth().padding(top = 18.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    SectionLabel("Ingredients", Modifier.weight(1f))
                    val all = rows.isNotEmpty() && rows.all { include[it.key] == true }
                    Text(
                        if (all) "Select none" else "Select all",
                        Modifier.clip(RoundedCornerShape(8.dp)).clickable { rows.forEach { include[it.key] = !all } }.padding(8.dp),
                        color = colors.accent, fontWeight = FontWeight.SemiBold, fontSize = 15.sp,
                    )
                }
                HorizontalDivider(color = colors.rule)
            }
            items(rows, key = { it.key }) { row ->
                val on = include[row.key] == true
                val already = view.items.filter {
                    !it.checked && ((row.catalogId != null && it.catalogId == row.catalogId) || it.name.equals(row.name, ignoreCase = true))
                }
                Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                    Row(Modifier.fillMaxWidth().clickable { include[row.key] = !on }, verticalAlignment = Alignment.CenterVertically) {
                        CheckBox(on, { include[row.key] = !on })
                        Column(Modifier.weight(1f)) {
                            Text(row.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                            for (a in already) {
                                Text("On ${view.storeName(a.storeId)}${if (a.qty.isNotBlank()) ": ${a.qty}" else ""}", fontSize = 14.sp, color = colors.warn, fontWeight = FontWeight.Medium)
                            }
                        }
                        if (row.parts.isNotEmpty()) {
                            Text(Quantities.format(row.parts), fontWeight = FontWeight.SemiBold, color = if (on) colors.accent else colors.ink2, fontSize = 16.sp)
                        }
                    }
                    StorePicker(view, row.ranks, storeFor(row), enabled = on) { storeChoice[row.key] = it }
                }
                HorizontalDivider(color = colors.rule)
            }
        }
    }
}

@Composable
private fun Stepper(label: String, onMinus: () -> Unit, onPlus: () -> Unit) {
    Row(Modifier.clip(RadiusShape).border(1.dp, colors.rule2, RadiusShape), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(42.dp).clickable(onClick = onMinus), contentAlignment = Alignment.Center) { Icon(AppIcons.Minus, "Less", Modifier.size(18.dp), tint = colors.ink) }
        Text(label, Modifier.width(52.dp), fontWeight = FontWeight.Bold, color = colors.ink, fontSize = 15.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        Box(Modifier.size(42.dp).clickable(onClick = onPlus), contentAlignment = Alignment.Center) { Icon(AppIcons.Plus, "More", Modifier.size(18.dp), tint = colors.ink) }
    }
}

@Composable
private fun StorePicker(view: Household, ranks: List<Long>, selected: Long?, enabled: Boolean, onPick: (Long?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    fun label(id: Long?): String {
        val i = ranks.indexOf(id)
        return if (id != null && i >= 0) "${view.storeName(id)} · ${ordinal(i + 1)}" else view.storeName(id)
    }
    val options: List<Long?> = ranks + view.stores.map { it.id }.filter { it !in ranks } + listOf(null)
    Box(Modifier.padding(start = 48.dp, top = 2.dp)) {
        Row(
            Modifier.clip(RadiusShape).border(1.dp, colors.rule2, RadiusShape).clickable { open = true }
                .padding(horizontal = 12.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(label(selected), fontSize = 15.sp, color = if (enabled) colors.ink else colors.ink2, fontWeight = FontWeight.Medium)
            Spacer(Modifier.width(6.dp))
            Icon(AppIcons.ChevronDown, null, Modifier.size(16.dp), tint = colors.ink2)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }, containerColor = colors.sheet) {
            for (id in options) {
                DropdownMenuItem(text = { Text(label(id), color = colors.ink) }, onClick = { onPick(id); open = false })
            }
        }
    }
}
