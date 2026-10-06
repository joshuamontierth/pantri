package app.shoppinglist.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shoppinglist.data.LocalView
import app.shoppinglist.data.StoreDto
import kotlinx.coroutines.launch
import sh.calvin.reorderable.ReorderableItem
import sh.calvin.reorderable.rememberReorderableLazyListState

/** The website's stores page: add, rename, drag to reorder, delete. Changes need a connection. */
@Composable
fun StoresScreen(vm: AppViewModel, view: LocalView, snackbar: SnackbarHostState) {
    val scope = rememberCoroutineScope()
    var newName by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var deleting by remember { mutableStateOf<StoreDto?>(null) }
    var order by remember { mutableStateOf(view.stores) }
    var dragging by remember { mutableStateOf(false) }
    LaunchedEffect(view.stores) { if (!dragging) order = view.stores }
    val listState = rememberLazyListState()
    val reorder = rememberReorderableLazyListState(listState) { from, to ->
        val a = order.indexOfFirst { it.id == from.key }
        val b = order.indexOfFirst { it.id == to.key }
        if (a >= 0 && b >= 0) order = order.toMutableList().apply { add(b, removeAt(a)) }
    }
    fun run(block: suspend () -> String?) = scope.launch { error = block() }

    Scaffold(
        containerColor = colors.paper,
        topBar = { BackBar("Settings", onBack = { vm.back() }) },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize(), state = listState, contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp)) {
            item {
                PageTitle("Stores", Modifier.padding(top = 4.dp, bottom = 10.dp))
                if (view.stores.isEmpty()) {
                    Text("Add the stores you shop at. Each store gets its own list.", color = colors.ink2, fontSize = 16.sp, modifier = Modifier.padding(bottom = 14.dp))
                }
                error?.let { Alert(it, modifier = Modifier.padding(bottom = 12.dp)) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Field(
                        newName, { newName = it }, Modifier.weight(1f), placeholder = "Store name",
                        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { if (newName.isNotBlank()) run { vm.addStore(newName).also { if (it == null) newName = "" } } }),
                    )
                    Spacer(Modifier.width(8.dp))
                    PrimaryButton("Add", enabled = newName.isNotBlank(), onClick = { run { vm.addStore(newName).also { if (it == null) newName = "" } } })
                }
                if (view.stores.isNotEmpty()) {
                    Text("Drag to change the order of the tabs.", color = colors.ink2, fontSize = 14.sp, modifier = Modifier.padding(top = 16.dp, bottom = 8.dp))
                    HorizontalDivider(color = colors.rule)
                }
            }
            items(order, key = { it.id }) { store ->
                ReorderableItem(reorder, key = store.id) { lifted ->
                    var name by remember(store.id, store.name) { mutableStateOf(store.name) }
                    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            AppIcons.Grip, "Drag to reorder",
                            Modifier.size(40.dp).padding(8.dp).draggableHandle(
                                onDragStarted = { dragging = true },
                                onDragStopped = {
                                    dragging = false
                                    if (order.map { it.id } != view.stores.map { it.id }) run { vm.reorderStores(order.map { it.id }) }
                                },
                            ),
                            tint = if (lifted) colors.ink else colors.ink3,
                        )
                        Field(name, { name = it }, Modifier.weight(1f), keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words))
                        Spacer(Modifier.width(6.dp))
                        OutlineButton("Rename", small = true, onClick = { run { vm.renameStore(store.id, name) } })
                        Spacer(Modifier.width(6.dp))
                        Box(
                            Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).border(1.dp, colors.danger.copy(alpha = 0.4f), RoundedCornerShape(10.dp))
                                .clickable { deleting = store },
                            contentAlignment = Alignment.Center,
                        ) { Icon(AppIcons.Trash, "Delete ${store.name}", Modifier.size(18.dp), tint = colors.danger) }
                    }
                    HorizontalDivider(color = colors.rule)
                }
            }
        }
    }
    deleting?.let { s ->
        val n = view.count(s.id)
        val moves = if (n > 0) " Its $n unchecked item${if (n != 1) "s" else ""} will move to ${view.otherLabel}." else ""
        Confirm("Delete ${s.name}?$moves It will also be removed from every item's store ranking.", "Delete",
            onDismiss = { deleting = null }, onConfirm = { run { vm.deleteStore(s.id) } })
    }
}
