package app.shoppinglist.ui

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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.shoppinglist.BuildConfig
import app.shoppinglist.data.Connection
import app.shoppinglist.data.LocalView
import app.shoppinglist.data.SyncStatus
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun SetupScreen(vm: AppViewModel) {
    var server by rememberSaveable { mutableStateOf(vm.serverUrl) }
    var username by rememberSaveable { mutableStateOf(vm.username) }
    var password by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    fun submit() {
        if (busy) return
        busy = true
        error = null
        scope.launch {
            error = vm.login(server, username, password)
            busy = false
        }
    }

    Box(Modifier.fillMaxSize().background(colors.paper).statusBarsPadding().navigationBarsPadding().imePadding(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 460.dp).fillMaxWidth().verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            PageTitle("Shopping List")
            Text(
                "Connect to your server. Your lists are kept on this phone too, so they work without a connection.",
                color = colors.ink2, fontSize = 16.sp, lineHeight = 23.sp,
            )
            Field(
                server, { server = it }, label = "Server", placeholder = "https://shopping.example.com",
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next, autoCorrectEnabled = false),
            )
            Field(
                username, { username = it }, label = "Username",
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next, autoCorrectEnabled = false),
            )
            Field(
                password, { password = it }, label = "Password", visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Go),
                keyboardActions = KeyboardActions(onGo = { submit() }),
            )
            error?.let {
                Text(it, Modifier.fillMaxWidth().clip(RadiusShape).background(colors.dangerWash).padding(12.dp), color = colors.danger, fontSize = 15.sp)
            }
            PrimaryButton(
                "Log in", onClick = ::submit, busy = busy, modifier = Modifier.fillMaxWidth(),
                enabled = server.isNotBlank() && username.isNotBlank() && password.isNotEmpty(),
            )
            Text("Use the same username and password as the website.", color = colors.ink3, fontSize = 14.sp)
        }
    }
}

@Composable
fun HouseholdPicker(vm: AppViewModel) {
    val uri = LocalUriHandler.current
    Column(
        Modifier.fillMaxSize().background(colors.paper).statusBarsPadding().navigationBarsPadding().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        PageTitle("Pick a household")
        if (vm.households.isEmpty()) {
            Text("You're not in a household yet. Create one on the website, or accept an invite there, then come back.", color = colors.ink2, fontSize = 16.sp)
            OutlineButton("Open the website", onClick = { runCatching { uri.openUri(vm.webUrl("/households")) } }, icon = AppIcons.External)
        }
        Column {
            HorizontalDivider(color = colors.rule)
            for (h in vm.households) {
                Row(
                    Modifier.fillMaxWidth().clickable { vm.chooseHousehold(h) }.heightIn(min = 60.dp).padding(vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(h.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                        Text(if (h.role == "admin") "Admin" else "Member", fontSize = 14.sp, color = colors.ink2)
                    }
                    androidx.compose.material3.Icon(AppIcons.ChevronRight, null, Modifier.size(18.dp), tint = colors.ink3)
                }
                HorizontalDivider(color = colors.rule)
            }
        }
        Spacer(Modifier.weight(1f))
        OutlineButton("Log out", onClick = { vm.logout() })
    }
}

private fun ago(ms: Long?, now: Long): String {
    if (ms == null) return "not yet"
    val s = (now - ms) / 1000
    return when {
        s < 10 -> "just now"
        s < 60 -> "${s}s ago"
        s < 3600 -> "${s / 60} min ago"
        s < 86400 -> "${s / 3600} h ago"
        else -> "${s / 86400} days ago"
    }
}

@Composable
fun SettingsScreen(vm: AppViewModel, view: LocalView?, status: SyncStatus, snackbar: SnackbarHostState) {
    val uri = LocalUriHandler.current
    var confirmLogout by remember { mutableStateOf(false) }
    var syncing by remember { mutableStateOf(false) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        while (true) {
            delay(5_000)
            now = System.currentTimeMillis()
        }
    }

    Scaffold(
        containerColor = colors.paper,
        topBar = { BackBar("Back", onBack = { vm.back() }) },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 32.dp),
        ) {
            PageTitle("Settings", Modifier.padding(top = 4.dp, bottom = 8.dp))

            SectionLabel("Sync", Modifier.padding(top = 20.dp, bottom = 10.dp))
            val (dot, line) = when (status.connection) {
                Connection.Live -> colors.successInk to "Connected. Changes from others show up as they happen."
                Connection.Online -> colors.successInk to "Connected."
                Connection.Offline -> colors.ink3 to "Can't reach the server. Everything still works here; changes are saved on this phone and sent when it's back."
                Connection.Connecting -> colors.ink3 to "Connecting…"
            }
            Row(verticalAlignment = Alignment.Top) {
                Box(Modifier.padding(top = 7.dp).size(9.dp).clip(CircleShape).background(dot))
                Text(line, Modifier.padding(start = 10.dp), color = colors.ink, fontSize = 16.sp, lineHeight = 23.sp)
            }
            Text(
                buildString {
                    append(if (status.pending == 0) "Everything is synced" else "${status.pending} change${if (status.pending == 1) "" else "s"} waiting to sync")
                    append(" · last synced ${ago(status.lastSynced, now)}")
                },
                Modifier.padding(top = 6.dp, start = 19.dp), color = colors.ink2, fontSize = 14.sp,
            )
            Spacer(Modifier.size(12.dp))
            OutlineButton(
                if (syncing) "Syncing…" else "Sync now", small = true, icon = AppIcons.Refresh,
                onClick = {
                    if (!syncing) scope.launch {
                        syncing = true
                        vm.refresh()
                        syncing = false
                    }
                },
            )

            if (vm.households.size > 1) {
                SectionLabel("Household", Modifier.padding(top = 28.dp, bottom = 10.dp))
                HorizontalDivider(color = colors.rule)
                for (h in vm.households) {
                    val on = h.id == vm.householdId
                    Row(
                        Modifier.fillMaxWidth().clickable(enabled = !on) { vm.chooseHousehold(h) }.heightIn(min = 56.dp).padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(h.name, Modifier.weight(1f), fontSize = 17.sp, fontWeight = if (on) FontWeight.Bold else FontWeight.Medium, color = colors.ink)
                        if (on) androidx.compose.material3.Icon(AppIcons.Check, "Current", tint = colors.accent)
                    }
                    HorizontalDivider(color = colors.rule)
                }
            }

            SectionLabel("Website", Modifier.padding(top = 28.dp, bottom = 10.dp))
            Text("Stores, the catalog, members, and importing or editing recipes are on the website.", color = colors.ink2, fontSize = 15.sp, lineHeight = 21.sp)
            Spacer(Modifier.size(10.dp))
            OutlineButton(
                "Open the website", icon = AppIcons.External,
                onClick = { runCatching { uri.openUri(vm.webUrl(if (view != null) "/h/${view.householdId}/settings" else "/")) } },
            )

            SectionLabel("Account", Modifier.padding(top = 28.dp, bottom = 10.dp))
            Text(vm.username, color = colors.ink, fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            Text(vm.serverUrl, color = colors.ink2, fontSize = 14.sp)
            Spacer(Modifier.size(10.dp))
            OutlineButton("Log out", danger = true, small = true, onClick = {
                if (vm.pendingCount() > 0) confirmLogout = true else vm.logout()
            })

            Text("Version ${BuildConfig.VERSION_NAME}", Modifier.padding(top = 28.dp), color = colors.ink3, fontSize = 13.sp)
        }
    }

    if (confirmLogout) {
        val n = vm.pendingCount()
        AlertDialog(
            onDismissRequest = { confirmLogout = false },
            containerColor = colors.sheet,
            title = { Text("Log out?") },
            text = { Text("$n change${if (n == 1) " hasn't" else "s haven't"} reached the server yet and will be lost.") },
            confirmButton = { TextButton(onClick = { confirmLogout = false; vm.logout() }) { Text("Log out", color = colors.danger) } },
            dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text("Cancel", color = colors.ink) } },
        )
    }
}
