package app.shoppinglist.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shoppinglist.data.Connection
import app.shoppinglist.data.SyncStatus

val RadiusShape = RoundedCornerShape(10.dp)

@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        modifier = modifier,
        color = colors.ink2,
        fontSize = 12.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = 1.2.sp,
    )
}

@Composable
fun PageTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, modifier = modifier, fontSize = 32.sp, fontWeight = FontWeight.ExtraBold, letterSpacing = (-0.9).sp, lineHeight = 36.sp, color = colors.ink)
}

@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, busy: Boolean = false, sub: String? = null) {
    Button(
        onClick = onClick,
        enabled = enabled && !busy,
        modifier = modifier.heightIn(min = 54.dp),
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = colors.primary, contentColor = colors.primaryInk,
            disabledContainerColor = colors.primary.copy(alpha = 0.4f), disabledContentColor = colors.primaryInk,
        ),
        contentPadding = PaddingValues(horizontal = 18.dp, vertical = 8.dp),
    ) {
        if (busy) {
            CircularProgressIndicator(Modifier.size(20.dp), color = colors.primaryInk, strokeWidth = 2.dp)
        } else {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(text, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                if (sub != null) Text(sub, fontSize = 13.sp, color = colors.primaryInk.copy(alpha = 0.72f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
fun OutlineButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    danger: Boolean = false,
    small: Boolean = false,
) {
    val tint = if (danger) colors.danger else colors.ink
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.heightIn(min = if (small) 40.dp else 48.dp),
        shape = RadiusShape,
        border = BorderStroke(1.dp, if (danger) colors.danger.copy(alpha = 0.4f) else colors.rule2),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = tint),
        contentPadding = PaddingValues(horizontal = if (small) 12.dp else 16.dp),
    ) {
        if (icon != null) {
            Icon(icon, null, Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
        }
        Text(text, fontWeight = FontWeight.SemiBold, fontSize = if (small) 14.sp else 15.sp)
    }
}

@Composable
fun Field(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: String? = null,
    placeholder: String? = null,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    keyboardActions: KeyboardActions = KeyboardActions.Default,
    visualTransformation: VisualTransformation = VisualTransformation.None,
    singleLine: Boolean = true,
    textStyle: TextStyle = TextStyle(fontSize = 16.sp),
) {
    Column(modifier) {
        if (label != null) {
            SectionLabel(label, Modifier.padding(bottom = 6.dp))
        }
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier.fillMaxWidth(),
            placeholder = placeholder?.let { { Text(it, color = colors.ink3) } },
            keyboardOptions = keyboardOptions,
            keyboardActions = keyboardActions,
            visualTransformation = visualTransformation,
            singleLine = singleLine,
            textStyle = textStyle.copy(color = colors.ink, fontFamily = Grotesk),
            shape = RadiusShape,
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = colors.ink, unfocusedBorderColor = colors.rule2,
                focusedContainerColor = colors.field, unfocusedContainerColor = colors.field,
                cursorColor = colors.accent,
            ),
        )
    }
}

/** The list's check box: a rounded square that fills with blue. */
@Composable
fun CheckBox(checked: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val fill by animateColorAsState(if (checked) colors.accent else colors.sheet, label = "check")
    val border by animateColorAsState(if (checked) colors.accent else colors.ink, label = "border")
    Box(modifier.size(48.dp).clip(CircleShape).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        Box(
            Modifier.size(26.dp).clip(RoundedCornerShape(7.dp)).background(fill).border(2.dp, border, RoundedCornerShape(7.dp)),
            contentAlignment = Alignment.Center,
        ) {
            if (checked) Icon(AppIcons.Check, null, Modifier.size(18.dp), tint = colors.accentInk)
        }
    }
}

@Composable
fun Dot(color: Color, size: Int = 8) {
    Box(Modifier.size(size.dp).clip(CircleShape).background(color))
}

/** "Live", "Offline · 3 waiting", ... in the header. */
@Composable
fun StatusPill(status: SyncStatus, onClick: () -> Unit) {
    val (label, color) = when {
        status.connection == Connection.Offline -> (if (status.pending > 0) "Offline · ${status.pending} waiting" else "Offline") to colors.ink3
        status.pending > 0 -> "Syncing" to colors.accent
        status.connection == Connection.Live -> "Live" to colors.successInk
        status.connection == Connection.Online -> "Online" to colors.successInk
        else -> "Connecting" to colors.ink3
    }
    Row(
        Modifier.clip(RoundedCornerShape(50)).clickable(onClick = onClick).padding(horizontal = 10.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (status.connection == Connection.Offline) Icon(AppIcons.CloudOff, null, Modifier.size(16.dp), tint = color)
        else Dot(color)
        Text(label, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = if (status.connection == Connection.Offline) colors.ink2 else colors.ink2)
    }
}

/** Top of the main screens: Lists / Recipes, the sync status and the gear, like the website's header. */
@Composable
fun TopNav(current: Screen, status: SyncStatus, onTab: (Screen) -> Unit, onSettings: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().background(colors.paper).statusBarsPadding().padding(start = 6.dp, end = 4.dp).height(56.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        for ((screen, label) in listOf(Screen.Lists to "Lists", Screen.Recipes to "Recipes")) {
            val on = current == screen
            Text(
                label,
                Modifier.clip(RoundedCornerShape(8.dp)).clickable { onTab(screen) }.padding(horizontal = 10.dp, vertical = 12.dp),
                fontSize = 17.sp,
                fontWeight = if (on) FontWeight.Bold else FontWeight.Medium,
                color = if (on) colors.ink else colors.ink2,
            )
        }
        Spacer(Modifier.weight(1f))
        StatusPill(status, onSettings)
        IconButton(onClick = onSettings) { Icon(AppIcons.Gear, "Settings", tint = colors.ink2) }
    }
}

/** Back arrow + title for screens below the top level. */
@Composable
fun BackBar(title: String, onBack: () -> Unit, trailing: @Composable () -> Unit = {}) {
    Row(
        Modifier.fillMaxWidth().background(colors.paper).statusBarsPadding().padding(horizontal = 4.dp).height(56.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(
            Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onBack).padding(end = 10.dp, top = 10.dp, bottom = 10.dp, start = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(AppIcons.Back, "Back", Modifier.size(20.dp), tint = colors.ink2)
            Text(title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = colors.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.weight(1f))
        trailing()
    }
}
