package app.shoppinglist.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shoppinglist.data.LocalItem
import app.shoppinglist.data.LocalView
import app.shoppinglist.data.SyncStatus
import kotlinx.coroutines.launch
import sh.calvin.reorderable.ReorderableItem
import sh.calvin.reorderable.rememberReorderableLazyListState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ListsScreen(vm: AppViewModel, view: LocalView, status: SyncStatus, snackbar: SnackbarHostState) {
    val listIds = view.listIds
    val pager = rememberPagerState(initialPage = vm.listPage().coerceIn(0, listIds.lastIndex)) { listIds.size }
    LaunchedEffect(pager.currentPage) { vm.setListPage(pager.currentPage) }
    val currentStore = listIds.getOrNull(pager.currentPage)
    var editing by remember { mutableStateOf<LocalItem?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Scaffold(
        containerColor = colors.paper,
        topBar = {
            Column(Modifier.background(colors.paper)) {
                TopNav(Screen.Lists, status, onTab = vm::tab, onSettings = { vm.go(Screen.Settings) })
                StoreTabs(view, pager)
            }
        },
        bottomBar = { QuickAdd(vm, view, currentStore) },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = refreshing,
            onRefresh = {
                scope.launch {
                    refreshing = true
                    vm.refresh()
                    refreshing = false
                }
            },
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) {
            HorizontalPager(state = pager, modifier = Modifier.fillMaxSize(), key = { listIds.getOrNull(it) ?: -1L }) { page ->
                StoreList(vm, view, listIds.getOrNull(page), onEdit = { editing = it })
            }
        }
    }

    editing?.let { started ->
        // Follow the item as syncs come in; it may have merged or gone.
        val item = view.items.firstOrNull { it.uiKey == started.uiKey } ?: started
        EditSheet(vm, view, item, onDismiss = { editing = null })
    }
}

@Composable
private fun StoreTabs(view: LocalView, pager: PagerState) {
    val scope = rememberCoroutineScope()
    val selected = pager.currentPage.coerceIn(0, view.listIds.lastIndex)
    Column {
    ScrollableTabRow(
        selectedTabIndex = selected,
        containerColor = colors.paper,
        contentColor = colors.ink,
        edgePadding = 8.dp,
        indicator = { positions ->
            if (selected < positions.size) {
                TabRowDefaults.SecondaryIndicator(Modifier.tabIndicatorOffset(positions[selected]), height = 3.dp, color = colors.accent)
            }
        },
        divider = {},
    ) {
        view.listIds.forEachIndexed { i, id ->
            val count = view.count(id)
            Tab(
                selected = i == selected,
                onClick = { scope.launch { pager.animateScrollToPage(i) } },
                selectedContentColor = colors.ink,
                unselectedContentColor = colors.ink2,
            ) {
                Row(Modifier.padding(horizontal = 6.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(view.storeName(id), fontSize = 16.sp, fontWeight = if (i == selected) FontWeight.Bold else FontWeight.Medium)
                    if (count > 0) {
                        Spacer(Modifier.width(6.dp))
                        Text("$count", fontSize = 14.sp, color = colors.ink3, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    }
    HorizontalDivider(color = colors.rule)
    }
}

@Composable
private fun StoreList(vm: AppViewModel, view: LocalView, storeId: Long?, onEdit: (LocalItem) -> Unit) {
    val unchecked = view.unchecked(storeId)
    val checked = view.checked(storeId)
    val haptics = LocalHapticFeedback.current
    // While dragging (and until the new order comes back from the data), rows follow dragOrder.
    // It holds keys, not items, so an item checked off meanwhile can't show up twice.
    var dragOrder by remember(storeId) { mutableStateOf<List<String>?>(null) }
    var dragging by remember { mutableStateOf(false) }
    val latest by rememberUpdatedState(unchecked)
    fun ordered(): List<LocalItem> {
        val keys = dragOrder ?: return latest
        val byKey = latest.associateBy { it.uiKey }
        return keys.mapNotNull { byKey[it] } + latest.filter { it.uiKey !in keys }
    }
    LaunchedEffect(unchecked) { if (!dragging) dragOrder = null }
    val order = ordered()
    val listState = rememberLazyListState()
    val reorderState = rememberReorderableLazyListState(listState) { from, to ->
        val keys = ordered().map { it.uiKey }.toMutableList()
        val a = keys.indexOf(from.key)
        val b = keys.indexOf(to.key)
        if (a >= 0 && b >= 0) {
            keys.add(b, keys.removeAt(a))
            dragOrder = keys
            haptics.performHapticFeedback(HapticFeedbackType.TextHandleMove)
        }
    }

    LazyColumn(state = listState, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        if (unchecked.isEmpty() && checked.isEmpty()) {
            item(key = "empty") { EmptyState("Nothing on ${view.storeName(storeId)}", "Add something below.") }
        } else if (unchecked.isEmpty()) {
            item(key = "done") { EmptyState("All done here", "Clear the checked items when you're finished.") }
        }
        items(order, key = { it.uiKey }) { item ->
            ReorderableItem(reorderState, key = item.uiKey) { isDragging ->
                ItemRow(
                    item = item,
                    lifted = isDragging,
                    onToggle = { vm.setChecked(item, true) },
                    onClick = { onEdit(item) },
                    handle = {
                        Icon(
                            AppIcons.Grip, "Drag to reorder",
                            Modifier.size(48.dp).padding(12.dp).draggableHandle(
                                onDragStarted = {
                                    dragging = true
                                    dragOrder = ordered().map { it.uiKey }
                                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                                },
                                onDragStopped = {
                                    dragging = false
                                    val now = ordered()
                                    if (now.map { it.uiKey } != latest.map { it.uiKey }) vm.reorder(storeId, now.map { it.key })
                                    else dragOrder = null
                                },
                            ),
                            tint = colors.ink3,
                        )
                    },
                )
            }
        }
        if (checked.isNotEmpty()) {
            item(key = "checked-head") {
                Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 20.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    SectionLabel("Checked · ${checked.size}", Modifier.weight(1f))
                    Text(
                        "Clear checked",
                        Modifier.clip(RoundedCornerShape(8.dp)).clickable { vm.clearChecked(checked) }.padding(horizontal = 10.dp, vertical = 8.dp),
                        color = colors.accent, fontWeight = FontWeight.SemiBold, fontSize = 15.sp,
                    )
                }
                HorizontalDivider(color = colors.rule)
            }
            items(checked, key = { it.uiKey }) { item ->
                ItemRow(item = item, lifted = false, onToggle = { vm.setChecked(item, false) }, onClick = { onEdit(item) }, handle = null)
            }
        }
    }
}

@Composable
private fun ItemRow(item: LocalItem, lifted: Boolean, onToggle: () -> Unit, onClick: () -> Unit, handle: (@Composable () -> Unit)?) {
    Column(Modifier.background(if (lifted) colors.sheet else colors.paper)) {
        Row(
            Modifier.fillMaxWidth().clickable(onClick = onClick).heightIn(min = 60.dp).padding(start = 4.dp, end = if (handle == null) 16.dp else 0.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CheckBox(item.checked, onToggle)
            Column(Modifier.weight(1f).padding(vertical = 10.dp, horizontal = 4.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        item.name,
                        fontSize = 17.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = if (item.checked) colors.ink3 else colors.ink,
                        textDecoration = if (item.checked) TextDecoration.LineThrough else null,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    if (item.pending) {
                        Spacer(Modifier.width(8.dp))
                        Dot(colors.rule2, 7) // not on the server yet
                    }
                }
                val sub = listOfNotNull(item.note.ifBlank { null }, item.tags.takeIf { it.isNotEmpty() }?.let { "for " + it.joinToString(", ") })
                if (sub.isNotEmpty()) {
                    Text(sub.joinToString(" · "), fontSize = 14.sp, color = colors.ink2, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
            if (item.qty.isNotBlank()) {
                Text(
                    item.qty,
                    Modifier.padding(start = 8.dp),
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = if (item.checked) colors.ink3 else colors.accent,
                    maxLines = 1,
                )
            }
            handle?.invoke()
        }
        HorizontalDivider(Modifier.padding(start = 56.dp), color = colors.rule)
    }
}

@Composable
fun EmptyState(title: String, text: String) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(title, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = colors.ink)
        Spacer(Modifier.size(6.dp))
        Text(text, fontSize = 15.sp, color = colors.ink2)
    }
}

@Composable
private fun QuickAdd(vm: AppViewModel, view: LocalView, storeId: Long?) {
    var name by rememberSaveable { mutableStateOf("") }
    var qty by rememberSaveable { mutableStateOf("") }
    val typed = name.trim()
    val suggestions = remember(typed, view.catalog) {
        if (typed.isEmpty()) emptyList()
        else view.catalog.filter { it.name.contains(typed, ignoreCase = true) && !it.name.equals(typed, ignoreCase = true) }
            .sortedBy { !it.name.startsWith(typed, ignoreCase = true) }
            .take(5)
    }
    fun add(n: String, store: Long?) {
        vm.addItem(n, qty, store)
        name = ""
        qty = ""
    }

    Column(Modifier.background(colors.sheet).navigationBarsPadding().imePadding()) {
        HorizontalDivider(color = colors.rule)
        for (s in suggestions) {
            val usual = view.usualStore(s.name)
            Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).padding(start = 8.dp, end = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    s.name,
                    Modifier.weight(1f).clip(RoundedCornerShape(8.dp)).clickable { add(s.name, storeId) }.padding(horizontal = 8.dp, vertical = 12.dp),
                    fontSize = 16.sp, fontWeight = FontWeight.Medium, color = colors.ink,
                )
                if (usual != storeId) {
                    Text(
                        "+ ${view.storeName(usual)}",
                        Modifier.clip(RoundedCornerShape(8.dp)).border(1.dp, colors.rule2, RoundedCornerShape(8.dp))
                            .clickable { add(s.name, usual) }.padding(horizontal = 10.dp, vertical = 7.dp),
                        fontSize = 14.sp, color = colors.ink2, fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            InlineField(
                value = name, onValueChange = { name = it }, placeholder = "Add to ${view.storeName(storeId)}",
                modifier = Modifier.weight(1f),
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { if (typed.isNotEmpty()) add(typed, storeId) }),
            )
            Spacer(Modifier.width(8.dp))
            InlineField(
                value = qty, onValueChange = { qty = it }, placeholder = "Qty", modifier = Modifier.width(72.dp),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { if (typed.isNotEmpty()) add(typed, storeId) }),
            )
            Spacer(Modifier.width(8.dp))
            Box(
                Modifier.size(48.dp).clip(RoundedCornerShape(12.dp)).background(if (typed.isEmpty()) colors.rule else colors.primary)
                    .clickable(enabled = typed.isNotEmpty()) { add(typed, storeId) },
                contentAlignment = Alignment.Center,
            ) {
                Icon(AppIcons.Plus, "Add", tint = if (typed.isEmpty()) colors.ink3 else colors.primaryInk)
            }
        }
    }
}

@Composable
private fun InlineField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    keyboardActions: KeyboardActions = KeyboardActions.Default,
) {
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier,
        singleLine = true,
        textStyle = TextStyle(fontSize = 16.sp, color = colors.ink, fontFamily = Grotesk),
        cursorBrush = SolidColor(colors.accent),
        keyboardOptions = keyboardOptions,
        keyboardActions = keyboardActions,
        decorationBox = { inner ->
            Box(
                Modifier.heightIn(min = 48.dp).clip(RadiusShape).background(colors.field).border(1.dp, colors.rule2, RadiusShape).padding(horizontal = 12.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                if (value.isEmpty()) Text(placeholder, fontSize = 16.sp, color = colors.ink3, maxLines = 1, overflow = TextOverflow.Ellipsis)
                inner()
            }
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun EditSheet(vm: AppViewModel, view: LocalView, item: LocalItem, onDismiss: () -> Unit) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var name by remember(item.uiKey) { mutableStateOf(item.name) }
    var qty by remember(item.uiKey) { mutableStateOf(item.qtyText) }
    var note by remember(item.uiKey) { mutableStateOf(item.note) }
    var store by remember(item.uiKey) { mutableStateOf(item.storeId) }
    val scope = rememberCoroutineScope()
    fun close(then: () -> Unit) {
        then()
        scope.launch { sheetState.hide() }.invokeOnCompletion { onDismiss() }
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState, containerColor = colors.sheet) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).imePadding().padding(horizontal = 16.dp).padding(bottom = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(item.name, fontSize = 24.sp, fontWeight = FontWeight.ExtraBold, color = colors.ink)
            Field(name, { name = it }, label = "Name", keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences))
            Field(qty, { qty = it }, label = "Quantity", placeholder = "e.g. 2 lb or 1 1/2 cups")
            Field(note, { note = it }, label = "Note", placeholder = "Brand, size…", keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences))
            Column {
                SectionLabel("Store", Modifier.padding(bottom = 8.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (id in view.listIds) {
                        val on = id == store
                        Text(
                            view.storeName(id),
                            Modifier.clip(RadiusShape)
                                .background(if (on) colors.accentWash else colors.sheet)
                                .border(1.dp, if (on) colors.accent else colors.rule2, RadiusShape)
                                .clickable { store = id }
                                .padding(horizontal = 14.dp, vertical = 11.dp),
                            fontSize = 15.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Medium,
                            color = if (on) colors.ink else colors.ink2,
                        )
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                PrimaryButton("Save", onClick = { close { vm.saveItem(item, name, qty, note, store) } }, modifier = Modifier.weight(1f), enabled = name.isNotBlank())
                Box(
                    Modifier.size(54.dp).clip(RoundedCornerShape(12.dp)).border(1.dp, colors.danger.copy(alpha = 0.4f), RoundedCornerShape(12.dp))
                        .clickable { close { vm.deleteItem(item) } },
                    contentAlignment = Alignment.Center,
                ) { Icon(AppIcons.Trash, "Delete", tint = colors.danger) }
            }
        }
    }
}
