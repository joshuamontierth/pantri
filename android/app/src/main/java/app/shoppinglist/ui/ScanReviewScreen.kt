package app.shoppinglist.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shoppinglist.data.LocalView

/**
 * "Add from your list" (the website's page after scanning a list): check the items, fix what was
 * misread, pick stores. Items in the catalog start at their usual store; a renamed item is matched
 * to the catalog again. Adding needs a connection, as on the website.
 */
@Composable
fun ScanReviewScreen(vm: AppViewModel, view: LocalView, review: ScanReview, snackbar: SnackbarHostState) {
    val focus = LocalFocusManager.current
    val picked = review.rows.filter { it.include }
    val fresh = picked.count { it.isNew(view) }

    Scaffold(
        containerColor = colors.paper,
        topBar = { BackBar("Lists", onBack = { vm.closeScanReview() }) },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            Box(Modifier.background(colors.paper).navigationBarsPadding().imePadding().padding(16.dp)) {
                val perStore = picked.groupingBy { view.storeName(it.store(view)) }.eachCount()
                PrimaryButton(
                    if (picked.isEmpty()) "Check the items you need" else "Add ${picked.size} item${if (picked.size == 1) "" else "s"} to lists",
                    sub = perStore.entries.joinToString(" · ") { "${it.key} ${it.value}" }.ifEmpty { null },
                    enabled = picked.isNotEmpty() && !review.adding,
                    busy = review.adding,
                    modifier = Modifier.fillMaxWidth(),
                    onClick = {
                        focus.clearFocus()
                        vm.addScanned()
                    },
                )
            }
        },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp)) {
            item {
                PageTitle("Add from your list", Modifier.padding(top = 4.dp, bottom = 12.dp))
                review.error?.let { Alert(it, modifier = Modifier.padding(bottom = 10.dp)) }
                if (review.notice.isNotEmpty()) Alert(review.notice, kind = "info", modifier = Modifier.padding(bottom = 6.dp))
                Row(Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    SectionLabel("Check what you need", Modifier.weight(1f))
                    val all = review.rows.all { it.include }
                    Text(
                        if (all) "Select none" else "Select all",
                        Modifier.clip(RoundedCornerShape(8.dp)).clickable { review.rows.forEach { it.include = !all } }.padding(8.dp),
                        color = colors.accent, fontWeight = FontWeight.SemiBold, fontSize = 15.sp,
                    )
                }
                HorizontalDivider(color = colors.rule)
            }
            items(review.rows, key = { it.key }) { row ->
                ScanRowItem(view, row)
                HorizontalDivider(color = colors.rule)
            }
            if (fresh > 0) {
                item {
                    Row(
                        Modifier.fillMaxWidth().padding(top = 10.dp).clickable { review.saveNew = !review.saveNew },
                        verticalAlignment = Alignment.Top,
                    ) {
                        CheckBox(review.saveNew, { review.saveNew = !review.saveNew })
                        Column(Modifier.padding(top = 12.dp)) {
                            Text(
                                "Save ${if (fresh == 1) "the new item" else "$fresh new items"} to the catalog",
                                fontSize = 16.sp, fontWeight = FontWeight.Bold, color = colors.ink,
                            )
                            Text("At the store you picked, so they go there next time", fontSize = 14.sp, color = colors.ink2)
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ScanRowItem(view: LocalView, row: ScanRow) {
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            CheckBox(row.include, { row.include = !row.include }, Modifier.padding(top = 4.dp)) // level with the name box
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    SmallField(row.name, { row.name = it }, "Item", Modifier.weight(1f), bold = true, capitalize = true)
                    Spacer(Modifier.width(8.dp))
                    SmallField(row.qty, { row.qty = it }, "Qty", Modifier.width(96.dp))
                }
                val isNew = row.isNew(view)
                if (isNew || row.readAs.isNotEmpty() || row.showOnList()) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        if (isNew) Badge("New")
                        if (row.readAs.isNotEmpty()) Text("Written “${row.readAs}”", fontSize = 14.sp, color = colors.ink2)
                        if (row.showOnList()) {
                            Text("Already on " + row.onList.joinToString(", "), fontSize = 14.sp, color = colors.warn, fontWeight = FontWeight.Medium)
                        }
                    }
                }
            }
        }
        StorePicker(view, row.ranks(view), row.store(view), enabled = row.include) {
            row.pickedByHand = true
            row.pickedStore = it
            row.include = true // picking a store means you want it, as on the website
        }
    }
}
