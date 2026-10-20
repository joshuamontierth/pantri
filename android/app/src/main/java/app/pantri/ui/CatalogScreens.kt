package app.pantri.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.foundation.layout.imePadding
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.pantri.data.CatalogDto
import app.pantri.data.LocalView
import app.pantri.data.SyncStatus
import kotlinx.coroutines.launch

private fun matches(c: CatalogDto, filter: String, storeIds: Set<Long>): Boolean {
    val ranks = c.ranks.filter { it in storeIds }
    return when (filter) {
        "all" -> true
        "none" -> ranks.isEmpty()
        else -> filter.toLongOrNull() in ranks
    }
}

/** The website's catalog page: every item and the stores you buy it at, filterable by store. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CatalogScreen(vm: AppViewModel, view: LocalView, status: SyncStatus, snackbar: SnackbarHostState) {
    val storeIds = view.stores.map { it.id }.toSet()
    var filter by remember { mutableStateOf(vm.catalogFilter.takeIf { it == "all" || it == "none" || it.toLongOrNull() in storeIds } ?: "all") }
    var query by rememberSaveable { mutableStateOf("") }
    val filters = listOf("all" to "All") + view.stores.map { it.id.toString() to it.name } + listOf("none" to view.otherLabel)
    val inFilter = view.catalog.filter { matches(it, filter, storeIds) }
    val shown = inFilter.filter { query.isBlank() || it.name.contains(query.trim(), ignoreCase = true) }

    Scaffold(
        containerColor = colors.paper,
        topBar = { TopNav(Screen.Catalog, status, onTab = vm::tab, onSettings = { vm.go(Screen.Settings) }) },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp)) {
            item {
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    PageTitle("Catalog", Modifier.weight(1f))
                    PrimaryButton("New item", onClick = { vm.go(Screen.CatalogEdit(null)) })
                }
                Text("Every item and the stores you buy it at, in order of preference.", Modifier.padding(top = 10.dp, bottom = 14.dp), color = colors.ink2, fontSize = 16.sp)
                if (view.catalog.size > 1) {
                    OutlineButton("Find duplicates", small = true, icon = AppIcons.Search, onClick = {
                        if (status.connection == app.pantri.data.Connection.Offline) vm.message("That needs a connection.") else vm.findDuplicates()
                    }, modifier = Modifier.padding(bottom = 14.dp))
                }
                if (view.catalog.isNotEmpty()) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        for ((key, label) in filters) {
                            val on = key == filter
                            val count = view.catalog.count { matches(it, key, storeIds) }
                            Row(
                                Modifier.clip(RadiusShape)
                                    .background(if (on) colors.primary else colors.paper)
                                    .border(1.dp, if (on) colors.primary else colors.rule2, RadiusShape)
                                    .clickable { filter = key; vm.catalogFilter = key }
                                    .heightIn(min = 40.dp).padding(horizontal = 12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(label, color = if (on) colors.primaryInk else colors.ink, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                                Spacer(Modifier.width(6.dp))
                                Text("$count", color = if (on) colors.primaryInk.copy(alpha = 0.7f) else colors.ink3, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                    Spacer(Modifier.size(14.dp))
                }
                when {
                    inFilter.isNotEmpty() -> {
                        Field(query, { query = it }, placeholder = "Search ${inFilter.size} item${if (inFilter.size != 1) "s" else ""}", keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search))
                        Spacer(Modifier.size(12.dp))
                        HorizontalDivider(color = colors.rule)
                    }
                    view.catalog.isNotEmpty() && filter == "none" -> EmptyState("Every item has a store", "Nothing left without a store.")
                    view.catalog.isNotEmpty() -> Text("No items are ranked at ${filters.first { it.first == filter }.second} yet.", color = colors.ink2)
                    else -> Text("No items yet. Items land here when you write recipes or save something you typed on a list.", color = colors.ink2)
                }
            }
            items(shown, key = { it.id }) { c ->
                Row(Modifier.fillMaxWidth().clickable { vm.go(Screen.CatalogEdit(c.id)) }.heightIn(min = 62.dp).padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(c.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                        val ranks = c.ranks.filter { it in storeIds }
                        Text(if (ranks.isEmpty()) "No stores yet" else ranks.joinToString(" › ") { view.storeName(it) }, fontSize = 14.sp, color = colors.ink2)
                    }
                    Icon(AppIcons.ChevronRight, null, Modifier.size(18.dp), tint = colors.ink3)
                }
                HorizontalDivider(color = colors.rule)
            }
        }
    }
}

/** New or edit a catalog item: its name and store ranking (the website's catalog form). */
@Composable
fun CatalogEditScreen(vm: AppViewModel, view: LocalView, itemId: Long?, startName: String, snackbar: SnackbarHostState) {
    val item = itemId?.let { view.catalogById[it] }
    var name by rememberSaveable(itemId, item?.name) { mutableStateOf(item?.name ?: startName) }
    var ranks by remember(itemId, item?.ranks) { mutableStateOf(item?.ranks?.filter { r -> view.stores.any { it.id == r } }.orEmpty()) }
    var merging by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val usedBy = if (item == null) emptyList() else view.recipes.filter { r -> r.ingredients.any { it.catalogId == item.id } }

    Scaffold(
        containerColor = colors.paper,
        topBar = { BackBar("Back", onBack = { vm.back() }) },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            PageTitle(item?.name ?: "New item", Modifier.padding(top = 4.dp))
            if (itemId != null && item == null) {
                Alert("That item is gone. Someone may have deleted it.")
                return@Column
            }
            error?.let { Alert(it) }
            Column {
                SectionLabel("Stores", Modifier.padding(bottom = 4.dp))
                Text("Tap in order of preference. Tap again to remove.", color = colors.ink2, fontSize = 14.sp, modifier = Modifier.padding(bottom = 10.dp))
                RankPicker(view.stores, ranks) { ranks = it }
            }
            Field(name, { name = it }, label = "Name", keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryButton("Save", busy = busy, enabled = name.isNotBlank(), onClick = {
                    busy = true
                    scope.launch {
                        error = vm.saveCatalogItem(itemId, name, ranks)
                        busy = false
                        if (error == null) vm.back()
                    }
                })
                OutlineButton("Cancel", onClick = { vm.back() })
            }
            if (item != null) {
                if (usedBy.isNotEmpty()) {
                    Column(Modifier.padding(top = 12.dp)) {
                        Text("Used in", color = colors.ink2, fontSize = 14.sp)
                        for (r in usedBy) {
                            Text(
                                r.name, Modifier.clickable { vm.go(Screen.Recipe(r.id)) }.padding(vertical = 6.dp),
                                color = colors.accent, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                } else {
                    OutlineButton("Delete item", danger = true, small = true, onClick = { confirmDelete = true }, modifier = Modifier.padding(top = 12.dp))
                }
                if (view.catalog.size > 1) {
                    OutlineButton("Merge with another item…", small = true, onClick = { merging = true })
                }
            }
        }
    }
    if (merging && item != null) {
        MergeSheet(vm, view, item, onDismiss = { merging = false }) { kept ->
            merging = false
            if (kept != item.id) vm.replace(Screen.CatalogEdit(kept))
            vm.message("Merged. Recipes and lists that used the other item use this one now.")
        }
    }
    if (confirmDelete && item != null) {
        Confirm("Delete ${item.name} from the catalog?", "Delete", onDismiss = { confirmDelete = false }, onConfirm = {
            scope.launch {
                error = vm.deleteCatalogItem(item.id)
                if (error == null) vm.back()
            }
        })
    }
}


/** Merge this item with another (the website's "Merge with another item"): pick it, and whose name stays. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MergeSheet(vm: AppViewModel, view: LocalView, item: CatalogDto, onDismiss: () -> Unit, onMerged: (Long) -> Unit) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var other by remember { mutableStateOf<CatalogDto?>(null) }
    var keepThis by remember { mutableStateOf(true) }
    var confirm by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val others = view.catalog.filter { it.id != item.id && (query.isBlank() || it.name.contains(query.trim(), ignoreCase = true)) }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = colors.sheet) {
        Column(Modifier.fillMaxWidth().imePadding().padding(horizontal = 16.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Merge ${item.name}", fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, color = colors.ink)
            Text(
                "For the same thing saved twice, like Avocado and Avocados. Recipes and lists that use either one will use the one you keep, with its stores first.",
                color = colors.ink2, fontSize = 14.sp,
            )
            error?.let { Alert(it) }
            Field(query, { query = it }, placeholder = "Search ${view.catalog.size - 1} items", keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search))
            Column(Modifier.fillMaxWidth().heightIn(max = 260.dp).verticalScroll(rememberScrollState())) {
                HorizontalDivider(color = colors.rule)
                for (c in others) {
                    Row(Modifier.fillMaxWidth().clickable { other = c }.heightIn(min = 52.dp), verticalAlignment = Alignment.CenterVertically) {
                        RadioDot(other?.id == c.id, { other = c })
                        Text(c.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                    }
                    HorizontalDivider(color = colors.rule)
                }
            }
            other?.let { o ->
                SectionLabel("Keep the name")
                for ((label, value) in listOf(item.name to true, o.name to false)) {
                    Row(Modifier.fillMaxWidth().clickable { keepThis = value }, verticalAlignment = Alignment.CenterVertically) {
                        RadioDot(keepThis == value, { keepThis = value })
                        Text(label, fontSize = 16.sp, color = colors.ink)
                    }
                }
            }
            PrimaryButton(
                other?.let { "Merge into “${if (keepThis) item.name else it.name}”" } ?: "Pick an item to merge with",
                enabled = other != null && !busy, busy = busy, modifier = Modifier.fillMaxWidth(),
                onClick = { confirm = true },
            )
            OutlineButton("Cancel", onClick = onDismiss, modifier = Modifier.fillMaxWidth())
        }
    }
    val o = other
    if (confirm && o != null) {
        val (keep, gone) = if (keepThis) item to o else o to item
        Confirm("Merge ${gone.name} into ${keep.name}? Recipes and lists will use ${keep.name}, and ${gone.name} is removed.", "Merge", danger = false,
            onDismiss = { confirm = false },
            onConfirm = {
                busy = true
                scope.launch {
                    error = vm.mergeCatalog(keep.id, listOf(gone.id))
                    busy = false
                    if (error == null) onMerged(keep.id)
                }
            })
    }
}
