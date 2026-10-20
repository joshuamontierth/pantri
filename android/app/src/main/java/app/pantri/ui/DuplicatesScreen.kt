package app.pantri.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.pantri.data.LocalView

/** A round choice, to match the check boxes. */
@Composable
fun RadioDot(selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val ring by animateColorAsState(if (selected) colors.accent else colors.ink, label = "ring")
    Box(modifier.size(48.dp).clip(CircleShape).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        Box(Modifier.size(24.dp).clip(CircleShape).background(colors.sheet).border(2.dp, ring, CircleShape), contentAlignment = Alignment.Center) {
            if (selected) Box(Modifier.size(12.dp).clip(CircleShape).background(colors.accent))
        }
    }
}

/** Possible duplicates in the catalog (the website's page): pick the name to keep, then merge or not. */
@Composable
fun DuplicatesScreen(vm: AppViewModel, view: LocalView, review: DuplicatesReview, snackbar: SnackbarHostState) {
    val group = review.groups.getOrNull(review.index)
    // Items merged or deleted since the search are left out; a group with fewer than two is passed over.
    val items = group?.items?.filter { it.id in view.catalogById }.orEmpty()
    LaunchedEffect(review.index, items.size) {
        if (group != null && items.size < 2) review.next()
    }
    val keep = review.keep?.takeIf { k -> items.any { it.id == k } } ?: group?.keep?.takeIf { k -> items.any { it.id == k } } ?: items.firstOrNull()?.id
    val included = items.filter { it.id !in review.leftOut || it.id == keep }

    Scaffold(
        containerColor = colors.paper,
        topBar = { BackBar("Catalog", onBack = { vm.closeDuplicates() }) },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            PageTitle("Possible duplicates", Modifier.padding(top = 4.dp))
            review.error?.let { Alert(it) }
            if (group == null || items.size < 2) {
                Column(Modifier.fillMaxWidth().padding(top = 32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    val any = review.groups.isNotEmpty()
                    Text(if (any) "All done" else "No duplicates found", fontSize = 20.sp, fontWeight = FontWeight.ExtraBold, color = colors.ink)
                    Text(
                        when {
                            any -> "Merged ${review.merged}" + (if (review.skipped > 0) ", kept ${review.skipped} apart." else ".")
                            review.usesModel -> "Nothing in the catalog looks like the same product twice."
                            else -> "No two items differ only by a plural. With a model set up (OLLAMA_URL), other names and misspellings are found too."
                        },
                        color = colors.ink2, fontSize = 15.sp,
                    )
                    OutlineButton("Back to the catalog", onClick = { vm.closeDuplicates() }, modifier = Modifier.padding(top = 10.dp))
                }
                return@Column
            }
            val total = review.groups.size
            val position = review.index + 1
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("$position of $total", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = colors.ink2)
                Spacer(Modifier.size(12.dp))
                Box(Modifier.weight(1f).heightIn(min = 4.dp).clip(RoundedCornerShape(4.dp)).background(colors.rule)) {
                    Box(Modifier.fillMaxWidth(position / total.toFloat()).heightIn(min = 4.dp).clip(RoundedCornerShape(4.dp)).background(colors.accent))
                }
            }
            Column {
                SectionLabel("Keep which name?")
                if (group.reason.isNotBlank()) {
                    Text("Looks like the same thing: ${group.reason.lowercase()}", color = colors.ink2, fontSize = 15.sp, modifier = Modifier.padding(top = 2.dp))
                }
            }
            Column {
                HorizontalDivider(color = colors.rule)
                for (it in items) {
                    val isKeep = it.id == keep
                    Row(Modifier.fillMaxWidth().clickable { review.keep = it.id }.heightIn(min = 64.dp), verticalAlignment = Alignment.CenterVertically) {
                        RadioDot(isKeep, { review.keep = it.id })
                        Column(Modifier.weight(1f).padding(vertical = 8.dp)) {
                            Text(it.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                            val details = listOfNotNull(
                                it.stores.ifBlank { "No stores yet" },
                                if (it.recipes > 0) "in ${it.recipes} recipe${if (it.recipes == 1) "" else "s"}" else null,
                                if (it.onList) "on a list" else null,
                            )
                            Text(details.joinToString(" · "), fontSize = 14.sp, color = colors.ink2)
                        }
                        if (items.size > 2) {
                            val on = it.id !in review.leftOut || isKeep
                            CheckBox(on, { if (!isKeep) { if (on) review.leftOut.add(it.id) else review.leftOut.remove(it.id) } })
                        }
                    }
                    HorizontalDivider(color = colors.rule)
                }
            }
            Text(
                (if (items.size > 2) "Uncheck any that aren't the same. " else "") +
                    "Recipes and lists that use the others will use the one you keep, with its stores first.",
                color = colors.ink2, fontSize = 14.sp,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryButton(
                    "Merge", busy = review.busy, enabled = !review.busy && keep != null,
                    modifier = Modifier.weight(1f),
                    onClick = { keep?.let { k -> vm.decideDuplicates(true, k, included.map { it.id }.filter { it != k }) } },
                )
                OutlineButton("Not the same", onClick = { vm.decideDuplicates(false, keep ?: 0, emptyList()) }, modifier = Modifier.weight(1f).heightIn(min = 54.dp))
            }
        }
    }
}
