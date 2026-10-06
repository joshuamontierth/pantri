package app.shoppinglist.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shoppinglist.data.StoreDto

/** Tap stores in order of preference; tap again to remove (the website's rank picker). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun RankPicker(stores: List<StoreDto>, ranks: List<Long>, onChange: (List<Long>) -> Unit) {
    if (stores.isEmpty()) {
        Text("No stores yet. Add them under Settings → Stores.", color = colors.ink2, fontSize = 14.sp)
        return
    }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        for (s in stores) {
            val rank = ranks.indexOf(s.id) + 1
            val on = rank > 0
            Row(
                Modifier.clip(RadiusShape)
                    .background(if (on) colors.accentWash else colors.paper)
                    .border(1.dp, if (on) colors.accent else colors.rule2, RadiusShape)
                    .clickable { onChange(if (on) ranks - s.id else ranks + s.id) }
                    .heightIn(min = 42.dp)
                    .padding(start = if (on) 8.dp else 14.dp, end = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (on) {
                    Box(Modifier.size(24.dp).clip(RoundedCornerShape(6.dp)).background(colors.accent), contentAlignment = Alignment.Center) {
                        Text("$rank", color = colors.accentInk, fontSize = 13.sp, fontWeight = FontWeight.ExtraBold)
                    }
                    Spacer(Modifier.width(8.dp))
                }
                Text(s.name, fontSize = 15.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Medium, color = if (on) colors.ink else colors.ink2)
            }
        }
    }
}

/** The website's alert boxes. */
@Composable
fun Alert(text: String, kind: String = "error", modifier: Modifier = Modifier) {
    val (bg, fg) = when (kind) {
        "error" -> colors.dangerWash to colors.danger
        "success" -> colors.accentWash to colors.successInk
        else -> colors.accentWash to colors.ink
    }
    Text(text, modifier.fillMaxWidth().clip(RadiusShape).background(bg).padding(horizontal = 14.dp, vertical = 12.dp), color = fg, fontSize = 15.sp)
}

/** "Are you sure?" for deletes, like the website's confirm prompts. */
@Composable
fun Confirm(text: String, action: String, onConfirm: () -> Unit, onDismiss: () -> Unit, danger: Boolean = true) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = colors.sheet,
        text = { Text(text, color = colors.ink, fontSize = 16.sp) },
        confirmButton = { TextButton(onClick = { onDismiss(); onConfirm() }) { Text(action, color = if (danger) colors.danger else colors.ink, fontWeight = FontWeight.SemiBold) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = colors.ink) } },
    )
}

/** A small "Admin" / "Added" tag. */
@Composable
fun Badge(text: String) {
    Text(
        text,
        Modifier.clip(RoundedCornerShape(6.dp)).background(colors.accentWash).padding(horizontal = 7.dp, vertical = 2.dp),
        color = colors.accent, fontSize = 12.sp, fontWeight = FontWeight.Bold,
    )
}
