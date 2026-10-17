package app.pantri.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusManager
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.pantri.data.Directions
import app.pantri.data.Part
import app.pantri.data.Quantities
import app.pantri.data.RecipeDto
import app.pantri.data.SyncStatus
import kotlinx.coroutines.launch
import java.net.URI
import app.pantri.data.LocalView as Household

/** The website's recipes page. */
@Composable
fun RecipesScreen(vm: AppViewModel, view: Household, status: SyncStatus, snackbar: SnackbarHostState) {
    var query by rememberSaveable { mutableStateOf("") }
    var importing by remember { mutableStateOf(false) }
    val shown = view.recipes.filter { query.isBlank() || it.name.contains(query.trim(), ignoreCase = true) }

    Scaffold(
        containerColor = colors.paper,
        topBar = { TopNav(Screen.Recipes, status, onTab = vm::tab, onSettings = { vm.go(Screen.Settings) }) },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp)) {
            item {
                Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    PageTitle("Recipes", Modifier.weight(1f))
                    OutlineButton("Import", small = true, icon = AppIcons.Import, onClick = { importing = true })
                    Spacer(Modifier.width(8.dp))
                    OutlineButton("New", small = true, icon = AppIcons.Plus, onClick = { vm.newRecipe() })
                }
                if (view.recipes.isEmpty()) {
                    Text(
                        "No recipes yet. Write one down, or import one from a photo or a recipe website, then pick the stores you buy each ingredient at.",
                        color = colors.ink2, fontSize = 16.sp, lineHeight = 23.sp,
                    )
                    Spacer(Modifier.size(16.dp))
                    PrimaryButton("New recipe", onClick = { vm.newRecipe() })
                } else {
                    PrimaryButton("Add recipes to lists", onClick = { vm.go(Screen.PlanChoose()) }, modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.size(14.dp))
                    Field(query, { query = it }, placeholder = "Search ${view.recipes.size} recipes", keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search))
                    Spacer(Modifier.size(12.dp))
                    HorizontalDivider(color = colors.rule)
                }
            }
            items(shown, key = { it.id }) { r ->
                Row(Modifier.fillMaxWidth().clickable { vm.go(Screen.Recipe(r.id)) }.heightIn(min = 64.dp).padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(r.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                        val n = r.ingredients.size
                        Text("$n ingredient${if (n == 1) "" else "s"}", fontSize = 14.sp, color = colors.ink2)
                    }
                    Icon(AppIcons.ChevronRight, null, Modifier.size(18.dp), tint = colors.ink3)
                }
                HorizontalDivider(color = colors.rule)
            }
        }
    }
    if (importing) ImportSheet(vm, recipeId = null, onDismiss = { importing = false })
}

/** The website's recipe page. */
@Composable
fun RecipeScreen(vm: AppViewModel, view: Household, recipeId: Long, snackbar: SnackbarHostState) {
    val recipe = view.recipes.firstOrNull { it.id == recipeId }
    val uri = LocalUriHandler.current
    val scope = rememberCoroutineScope()
    var addingDetails by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var copyMenu by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
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
        val others = vm.households.filter { it.id != view.householdId }

        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 40.dp)) {
            item {
                error?.let { Alert(it, modifier = Modifier.padding(bottom = 10.dp)) }
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
                val ranks = ing.catalogId?.let { view.catalogById[it]?.ranks }.orEmpty().filter { r -> view.stores.any { it.id == r } }
                Row(
                    Modifier.fillMaxWidth().clickable(enabled = ing.catalogId != null) { vm.go(Screen.CatalogEdit(ing.catalogId)) }
                        .heightIn(min = 56.dp).padding(vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(ing.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                        Text(if (ranks.isEmpty()) view.otherLabel else ranks.joinToString(" › ") { view.storeName(it) }, fontSize = 14.sp, color = colors.ink2)
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
                    Text(
                        "No directions yet. Use Add details to read them from ${if (vm.scanEnabled) "a photo of the recipe or " else ""}a link to it.",
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).border(1.dp, colors.rule2, RoundedCornerShape(14.dp)).padding(16.dp),
                        color = colors.ink2, fontSize = 15.sp,
                    )
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
                item { Text("Tap a step to mark it done.", color = colors.ink2, fontSize = 14.sp, modifier = Modifier.padding(top = 10.dp)) }
            }
            item {
                Row(Modifier.fillMaxWidth().padding(top = 28.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlineButton("Edit", onClick = { vm.editRecipe(recipe.id) })
                    OutlineButton("Add details", icon = AppIcons.Import, onClick = { addingDetails = true })
                    Spacer(Modifier.weight(1f))
                    Box(
                        Modifier.size(48.dp).clip(RadiusShape).border(1.dp, colors.danger.copy(alpha = 0.4f), RadiusShape).clickable { confirmDelete = true },
                        contentAlignment = Alignment.Center,
                    ) { Icon(AppIcons.Trash, "Delete recipe", tint = colors.danger) }
                }
                if (others.isNotEmpty()) {
                    Box(Modifier.padding(top = 10.dp)) {
                        OutlineButton("Copy to…", small = true, onClick = { copyMenu = true })
                        DropdownMenu(expanded = copyMenu, onDismissRequest = { copyMenu = false }, containerColor = colors.sheet) {
                            for (h in others) {
                                DropdownMenuItem(text = { Text(h.name, color = colors.ink) }, onClick = {
                                    copyMenu = false
                                    scope.launch { error = vm.copyRecipe(recipe.id, h) }
                                })
                            }
                        }
                    }
                }
            }
        }
        if (addingDetails) ImportSheet(vm, recipeId = recipe.id, onDismiss = { addingDetails = false })
        if (confirmDelete) {
            Confirm("Delete the recipe ${recipe.name}?", "Delete", onDismiss = { confirmDelete = false }, onConfirm = {
                scope.launch {
                    error = vm.deleteRecipe(recipe.id)
                    if (error == null) vm.back()
                }
            })
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

/** Step 1 of adding recipes to the lists (the website's "Choose recipes"). */
@Composable
fun PlanChooseScreen(vm: AppViewModel, view: Household, preselected: List<Long>, snackbar: SnackbarHostState) {
    var query by rememberSaveable { mutableStateOf("") }
    val chosen = remember { mutableStateMapOf<Long, Boolean>().apply { preselected.forEach { put(it, true) } } }
    val picked = view.recipes.filter { chosen[it.id] == true }
    val shown = view.recipes.filter { query.isBlank() || it.name.contains(query.trim(), ignoreCase = true) }
    Scaffold(
        containerColor = colors.paper,
        topBar = { BackBar("Recipes", onBack = { vm.back() }) },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            Box(Modifier.background(colors.paper).navigationBarsPadding().padding(16.dp)) {
                PrimaryButton(
                    if (picked.isEmpty()) "Choose at least one recipe" else "Next: ${picked.size} recipe${if (picked.size == 1) "" else "s"}",
                    enabled = picked.isNotEmpty(), modifier = Modifier.fillMaxWidth(),
                    onClick = { vm.go(Screen.Plan(picked.map { it.id })) },
                )
            }
        },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp)) {
            item {
                PageTitle("Choose recipes", Modifier.padding(top = 4.dp, bottom = 12.dp))
                if (view.recipes.isEmpty()) {
                    Text("No recipes yet.", color = colors.ink2)
                } else {
                    Field(query, { query = it }, placeholder = "Search recipes", keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search))
                    Spacer(Modifier.size(12.dp))
                    HorizontalDivider(color = colors.rule)
                }
            }
            items(shown, key = { it.id }) { r ->
                Row(Modifier.fillMaxWidth().clickable { chosen[r.id] = chosen[r.id] != true }.heightIn(min = 64.dp).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    CheckBox(chosen[r.id] == true, { chosen[r.id] = chosen[r.id] != true })
                    Column(Modifier.weight(1f)) {
                        Text(r.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                        val n = r.ingredients.size
                        Text("$n ingredient${if (n == 1) "" else "s"}", fontSize = 14.sp, color = colors.ink2)
                    }
                }
                HorizontalDivider(color = colors.rule)
            }
        }
    }
}

/** One ingredient across the chosen recipes. */
private data class PlanRow(val key: String, val name: String, val catalogId: Long?, val parts: List<Part>, val tags: List<String>, val ranks: List<Long>)

private fun planRows(view: Household, recipes: List<Pair<RecipeDto, Double>>): List<PlanRow> {
    val storeIds = view.stores.map { it.id }.toSet()
    val rows = LinkedHashMap<String, PlanRow>()
    for ((r, m) in recipes) {
        for (ing in r.ingredients) {
            val key = ing.catalogId?.let { "c$it" } ?: "n${ing.name.lowercase()}"
            val parts = if (ing.amount != null) listOf(Part(ing.amount * m, ing.unit)) else emptyList()
            val existing = rows[key]
            rows[key] = if (existing == null) {
                PlanRow(key, ing.name, ing.catalogId, parts, listOf(r.name), ing.catalogId?.let { view.catalogById[it]?.ranks }.orEmpty().filter { it in storeIds })
            } else {
                existing.copy(parts = Quantities.combine(existing.parts, parts), tags = (existing.tags + r.name).distinct())
            }
        }
    }
    return rows.values.toList()
}

private fun ordinal(i: Int) = listOf("1st", "2nd", "3rd").getOrElse(i) { "${i + 1}th" }

/** Step 2: check the ingredients you need and pick a store for each (the website's "Choose ingredients"). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PlanScreen(vm: AppViewModel, view: Household, recipeIds: List<Long>, snackbar: SnackbarHostState) {
    val recipes = recipeIds.mapNotNull { id -> view.recipes.firstOrNull { it.id == id } }
    val multText = remember { mutableStateMapOf<Long, String>() }
    val include = remember { mutableStateMapOf<String, Boolean>() }
    val storeChoice = remember { mutableStateMapOf<String, Long?>() }
    val focus = LocalFocusManager.current
    val errors = mutableListOf<String>()
    val scaled = recipes.map { r ->
        val text = multText[r.id] ?: "1"
        val m = Quantities.parseAmount(text)
        if (m == null || m <= 0 || m > 100) {
            errors += "Couldn't read the multiplier for ${r.name}: “$text”."
            r to 1.0
        } else r to m
    }
    val rows = planRows(view, scaled)
    fun storeFor(row: PlanRow): Long? = if (storeChoice.containsKey(row.key)) storeChoice[row.key] else row.ranks.firstOrNull()
    val picked = rows.filter { include[it.key] == true }

    Scaffold(
        containerColor = colors.paper,
        // Opened from the meal calendar, back goes there.
        topBar = { BackBar(if (vm.stack.getOrNull(vm.stack.lastIndex - 1) == Screen.Meals) "Meals" else "Recipes", onBack = { vm.back() }) },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            Box(Modifier.background(colors.paper).navigationBarsPadding().padding(16.dp)) {
                val perStore = picked.groupingBy { view.storeName(storeFor(it)) }.eachCount()
                PrimaryButton(
                    if (picked.isEmpty()) "Check the items you need" else "Add ${picked.size} item${if (picked.size == 1) "" else "s"} to lists",
                    sub = perStore.entries.joinToString(" · ") { "${it.key} ${it.value}" }.ifEmpty { null },
                    enabled = picked.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth(),
                    onClick = {
                        vm.addFromRecipes(picked.map { PlanAdd(it.name, it.parts, storeFor(it), it.tags) })
                        // Like the website: on to the lists, open at the first store something went to.
                        vm.setListPage(view.listIds.indexOf(storeFor(picked.first())).coerceAtLeast(0))
                        vm.tab(Screen.Lists)
                    },
                )
            }
        },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp)) {
            item {
                PageTitle("Choose ingredients", Modifier.padding(top = 4.dp, bottom = 12.dp))
                HorizontalDivider(color = colors.ink, thickness = 2.dp)
                for (r in recipes) {
                    Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(r.name, Modifier.weight(1f), fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = colors.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text("×", color = colors.ink2, fontSize = 15.sp, modifier = Modifier.padding(end = 8.dp))
                        MultiplierField(multText[r.id] ?: "1", { multText[r.id] = it }, focus)
                    }
                    HorizontalDivider(color = colors.rule)
                }
                Text("Add or remove recipes", Modifier.clickable {
                    if (vm.stack.getOrNull(vm.stack.lastIndex - 1) is Screen.PlanChoose) vm.back() else vm.replace(Screen.PlanChoose(recipeIds))
                }.padding(vertical = 12.dp), color = colors.accent, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                Row(Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    SectionLabel("Check what you need", Modifier.weight(1f))
                    val all = rows.isNotEmpty() && rows.all { include[it.key] == true }
                    Text(
                        if (all) "Select none" else "Select all",
                        Modifier.clip(RoundedCornerShape(8.dp)).clickable { rows.forEach { include[it.key] = !all } }.padding(8.dp),
                        color = colors.accent, fontWeight = FontWeight.SemiBold, fontSize = 15.sp,
                    )
                }
                for (e in errors) Alert(e, modifier = Modifier.padding(bottom = 8.dp))
                HorizontalDivider(color = colors.rule)
                if (rows.isEmpty()) Text("These recipes have no ingredients.", color = colors.ink2, modifier = Modifier.padding(top = 12.dp))
            }
            items(rows, key = { it.key }) { row ->
                val on = include[row.key] == true
                val already = view.items.filter { !it.checked && ((row.catalogId != null && it.catalogId == row.catalogId) || it.name.equals(row.name, ignoreCase = true)) }
                Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                    Row(Modifier.fillMaxWidth().clickable { include[row.key] = !on }, verticalAlignment = Alignment.CenterVertically) {
                        CheckBox(on, { include[row.key] = !on })
                        Column(Modifier.weight(1f)) {
                            Text(row.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                            if (row.tags.size > 1) Text("for " + row.tags.joinToString(", "), fontSize = 13.sp, color = colors.ink2)
                            if (already.isNotEmpty()) {
                                Text("Already on " + already.joinToString(", ") { a -> view.storeName(a.storeId) + if (a.qty.isNotBlank()) ": ${a.qty}" else "" },
                                    fontSize = 14.sp, color = colors.warn, fontWeight = FontWeight.Medium)
                            }
                        }
                        if (row.parts.isNotEmpty()) {
                            Text(Quantities.format(row.parts), fontWeight = FontWeight.SemiBold, color = if (on) colors.accent else colors.ink2, fontSize = 16.sp)
                        }
                    }
                    StorePicker(view, row.ranks, storeFor(row), enabled = on) {
                        storeChoice[row.key] = it
                        include[row.key] = true // picking a store means you want it, as on the website
                    }
                }
                HorizontalDivider(color = colors.rule)
            }
        }
    }
}

@Composable
private fun MultiplierField(value: String, onChange: (String) -> Unit, focus: FocusManager) {
    OutlinedTextField(
        value, onChange, Modifier.width(76.dp).heightIn(min = 46.dp), singleLine = true,
        textStyle = TextStyle(fontSize = 16.sp, color = colors.ink, fontFamily = Grotesk, textAlign = TextAlign.Center),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text, imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { focus.clearFocus() }),
        shape = RadiusShape,
        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = colors.ink, unfocusedBorderColor = colors.rule2,
            focusedContainerColor = colors.field, unfocusedContainerColor = colors.field, cursorColor = colors.accent),
    )
}

@Composable
internal fun StorePicker(view: Household, ranks: List<Long>, selected: Long?, enabled: Boolean, onPick: (Long?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    fun label(id: Long?): String {
        val i = ranks.indexOf(id)
        return if (id != null && i >= 0) "${view.storeName(id)} · ${ordinal(i)}" else view.storeName(id)
    }
    val options: List<Long?> = ranks + view.stores.map { it.id }.filter { it !in ranks } + listOf(null)
    Box(Modifier.padding(start = 48.dp, top = 2.dp)) {
        Row(
            Modifier.clip(RadiusShape).border(1.dp, colors.rule2, RadiusShape).clickable { open = true }.padding(horizontal = 12.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(label(selected), fontSize = 15.sp, color = if (enabled) colors.ink else colors.ink2, fontWeight = FontWeight.Medium)
            Spacer(Modifier.width(6.dp))
            Icon(AppIcons.ChevronDown, null, Modifier.size(16.dp), tint = colors.ink2)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }, containerColor = colors.sheet) {
            if (ranks.isNotEmpty()) {
                Text("Your stores for this", color = colors.ink2, fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
            }
            for ((i, id) in options.withIndex()) {
                if (i == ranks.size && i < options.size - 1) {
                    Text("Other stores", color = colors.ink2, fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
                }
                DropdownMenuItem(text = { Text(label(id), color = colors.ink) }, onClick = { onPick(id); open = false })
            }
        }
    }
}
