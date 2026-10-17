package app.pantri.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.pantri.BuildConfig
import app.pantri.data.Connection
import app.pantri.data.SyncStatus
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val noAutocorrect = KeyboardOptions(autoCorrectEnabled = false, capitalization = KeyboardCapitalization.None)

/** Log in, or create an account (the website's login and signup pages). */
@Composable
fun SetupScreen(vm: AppViewModel) {
    var signingUp by rememberSaveable { mutableStateOf(false) }
    var server by rememberSaveable { mutableStateOf(vm.serverUrl.ifEmpty { BuildConfig.SERVER_URL }) }
    var username by rememberSaveable { mutableStateOf(vm.username) }
    var password by rememberSaveable { mutableStateOf("") }
    var confirm by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    fun submit() {
        if (busy) return
        busy = true
        error = null
        scope.launch {
            error = vm.login(server, username, password, if (signingUp) confirm else null)
            busy = false
        }
    }

    Box(Modifier.fillMaxSize().background(colors.paper).statusBarsPadding().navigationBarsPadding().imePadding(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 460.dp).fillMaxWidth().verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("Pantri", color = colors.ink2, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            PageTitle(if (signingUp) "Create an account" else "Log in")
            if (!signingUp) {
                Text("Your lists are kept on this phone too, so they work without a connection.", color = colors.ink2, fontSize = 16.sp, lineHeight = 23.sp)
            }
            error?.let { Alert(it) }
            Field(
                server, { server = it }, label = "Server", placeholder = AppViewModel.EXAMPLE_SERVER,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next, autoCorrectEnabled = false),
            )
            Field(username, { username = it }, label = "Username", keyboardOptions = noAutocorrect.copy(imeAction = ImeAction.Next))
            Column {
                Field(
                    password, { password = it }, label = "Password", visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = if (signingUp) ImeAction.Next else ImeAction.Go),
                    keyboardActions = KeyboardActions(onGo = { submit() }),
                )
                if (signingUp) Text("At least 8 characters", color = colors.ink2, fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp))
            }
            if (signingUp) {
                Field(
                    confirm, { confirm = it }, label = "Confirm password", visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Go),
                    keyboardActions = KeyboardActions(onGo = { submit() }),
                )
            }
            PrimaryButton(
                if (signingUp) "Sign up" else "Log in", onClick = ::submit, busy = busy, modifier = Modifier.fillMaxWidth(),
                enabled = server.isNotBlank() && username.isNotBlank() && password.isNotEmpty() && (!signingUp || confirm.isNotEmpty()),
            )
            Text(
                buildAnnotatedString {
                    append(if (signingUp) "Already have an account? " else "No account yet? ")
                    withStyle(SpanStyle(color = colors.accent, fontWeight = FontWeight.SemiBold)) { append(if (signingUp) "Log in" else "Create one") }
                },
                Modifier.clickable { signingUp = !signingUp; error = null }.padding(vertical = 6.dp),
                color = colors.ink2, fontSize = 15.sp,
            )
        }
    }
}

/** Change password; forced after an admin reset (then nothing else is possible until it's done). */
@Composable
fun ChangePasswordScreen(vm: AppViewModel, forced: Boolean) {
    var current by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().background(colors.paper)) {
        if (forced) Spacer(Modifier.statusBarsPadding().size(16.dp)) else BackBar("Account", onBack = { vm.back() })
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(horizontal = 16.dp).padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            PageTitle(if (forced) "Choose a new password" else "Change password", Modifier.padding(top = 4.dp))
            if (forced) Alert("An admin reset your password. Choose a new one to continue.", kind = "info")
            error?.let { Alert(it) }
            val pw = KeyboardOptions(keyboardType = KeyboardType.Password)
            if (!forced) Field(current, { current = it }, label = "Current password", visualTransformation = PasswordVisualTransformation(), keyboardOptions = pw)
            Field(password, { password = it }, label = "New password", visualTransformation = PasswordVisualTransformation(), keyboardOptions = pw)
            Field(confirm, { confirm = it }, label = "Confirm new password", visualTransformation = PasswordVisualTransformation(), keyboardOptions = pw)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryButton("Save password", busy = busy, enabled = password.isNotEmpty() && confirm.isNotEmpty(), onClick = {
                    busy = true
                    scope.launch {
                        error = vm.changePassword(current, password, confirm)
                        busy = false
                    }
                })
                if (!forced) OutlineButton("Cancel", onClick = { vm.back() })
            }
            if (forced) {
                Text("Log out", Modifier.clickable { vm.logout() }.padding(vertical = 8.dp), color = colors.accent, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun MenuRow(text: String, onClick: () -> Unit, trailing: @Composable () -> Unit = { Icon(AppIcons.ChevronRight, null, Modifier.size(18.dp), tint = colors.ink3) }) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).heightIn(min = 56.dp).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(text, Modifier.weight(1f), fontSize = 17.sp, color = colors.ink)
        trailing()
    }
    HorizontalDivider(color = colors.rule)
}

/** The website's households page: invites, your households, and making a new one. */
@Composable
fun HouseholdsScreen(vm: AppViewModel, canGoBack: Boolean) {
    val scope = rememberCoroutineScope()
    var error by remember { mutableStateOf<String?>(null) }
    var name by remember { mutableStateOf("") }
    val me = vm.me
    LaunchedEffect(Unit) { vm.refreshMe() }
    Column(Modifier.fillMaxSize().background(colors.paper)) {
        if (canGoBack) BackBar("Back", onBack = { vm.back() }) else Spacer(Modifier.statusBarsPadding().size(16.dp))
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(horizontal = 16.dp).padding(bottom = 32.dp),
        ) {
            PageTitle("Households", Modifier.padding(top = 4.dp, bottom = 12.dp))
            error?.let { Alert(it, modifier = Modifier.padding(bottom = 12.dp)) }
            val invites = me?.invites.orEmpty()
            if (invites.isNotEmpty()) {
                SectionLabel("Invites", Modifier.padding(top = 12.dp, bottom = 8.dp))
                HorizontalDivider(color = colors.rule)
                for (inv in invites) {
                    Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(inv.household, fontWeight = FontWeight.Bold, fontSize = 17.sp, color = colors.ink)
                            Text("from ${inv.invitedBy ?: "someone"}", color = colors.ink2, fontSize = 14.sp)
                        }
                        OutlineButton("Decline", small = true, onClick = { scope.launch { error = vm.declineInvite(inv.id) } })
                        Spacer(Modifier.width(8.dp))
                        PrimaryButton("Join", onClick = { scope.launch { error = vm.acceptInvite(inv.id) } })
                    }
                    HorizontalDivider(color = colors.rule)
                }
            }
            if (vm.households.isNotEmpty()) {
                if (invites.isNotEmpty()) SectionLabel("Yours", Modifier.padding(top = 24.dp, bottom = 8.dp))
                HorizontalDivider(color = colors.rule)
                for (h in vm.households) {
                    MenuRow(h.name, onClick = { vm.chooseHousehold(h) }, trailing = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (h.role == "admin") Badge("Admin")
                            Spacer(Modifier.width(8.dp))
                            Icon(AppIcons.ChevronRight, null, Modifier.size(18.dp), tint = colors.ink3)
                        }
                    })
                }
            } else if (invites.isEmpty()) {
                Text(
                    buildAnnotatedString {
                        append("You're not in a household yet. Create one, or ask someone to invite your username, ")
                        withStyle(SpanStyle(fontWeight = FontWeight.Bold, color = colors.ink)) { append(vm.username) }
                        append(".")
                    },
                    color = colors.ink2, fontSize = 16.sp, lineHeight = 23.sp,
                )
            }
            SectionLabel("New household", Modifier.padding(top = 28.dp, bottom = 8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Field(name, { name = it }, Modifier.weight(1f), placeholder = "Home", keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words))
                Spacer(Modifier.width(8.dp))
                PrimaryButton("Create", enabled = name.isNotBlank(), onClick = { scope.launch { error = vm.createHousehold(name) } })
            }
            if (!canGoBack) {
                Spacer(Modifier.size(32.dp))
                OutlineButton("Log out", onClick = { vm.logout() })
            }
        }
    }
}

/** The website's account page. */
@Composable
fun AccountScreen(vm: AppViewModel) {
    var confirmLogout by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().background(colors.paper)) {
        BackBar("Settings", onBack = { vm.back() })
        Column(Modifier.padding(horizontal = 16.dp)) {
            PageTitle(vm.username, Modifier.padding(top = 4.dp, bottom = 12.dp))
            HorizontalDivider(color = colors.rule)
            MenuRow("Households  ${vm.households.size}", onClick = { vm.go(Screen.Households) })
            MenuRow("Change password", onClick = { vm.go(Screen.ChangePassword) })
            Row(Modifier.fillMaxWidth().clickable { if (vm.pendingCount() > 0) confirmLogout = true else vm.logout() }.heightIn(min = 56.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Log out", color = colors.danger, fontSize = 17.sp)
            }
            HorizontalDivider(color = colors.rule)
            Text(vm.serverUrl, color = colors.ink3, fontSize = 13.sp, modifier = Modifier.padding(top = 16.dp))
            Text("App version ${BuildConfig.VERSION_NAME}", color = colors.ink3, fontSize = 13.sp)
        }
    }
    if (confirmLogout) LogoutConfirm(vm) { confirmLogout = false }
}

@Composable
private fun LogoutConfirm(vm: AppViewModel, onDismiss: () -> Unit) {
    val n = vm.pendingCount()
    Confirm(
        "Log out? $n change${if (n == 1) " hasn't" else "s haven't"} reached the server yet and will be lost.",
        "Log out", onConfirm = { vm.logout() }, onDismiss = onDismiss,
    )
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
private fun ColumnScope.Section(title: String) {
    SectionLabel(title, Modifier.padding(top = 28.dp, bottom = 10.dp))
}

/** The website's settings page (stores, households, members, invites, account, leave/delete), plus sync. */
@Composable
fun SettingsScreen(vm: AppViewModel, status: SyncStatus, snackbar: SnackbarHostState) {
    val uri = LocalUriHandler.current
    val scope = rememberCoroutineScope()
    var error by remember { mutableStateOf<String?>(null) }
    var syncing by remember { mutableStateOf(false) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var confirmLeave by remember { mutableStateOf(false) }
    var confirmLogout by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf<Long?>(null) }
    LaunchedEffect(vm.householdId) { vm.loadHouseholdSettings() }
    LaunchedEffect(Unit) {
        while (true) {
            delay(5_000)
            now = System.currentTimeMillis()
        }
    }
    val hs = vm.householdSettings
    val isAdmin = hs?.role == "admin"
    val current = vm.households.firstOrNull { it.id == vm.householdId }
    fun act(block: suspend () -> String?) = scope.launch { error = block() }

    Scaffold(containerColor = colors.paper, topBar = { BackBar("Back", onBack = { vm.back() }) }, snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Column(Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(horizontal = 16.dp).padding(bottom = 40.dp)) {
            PageTitle(hs?.household?.name ?: current?.name ?: "Settings", Modifier.padding(top = 4.dp, bottom = 12.dp))
            error?.let { Alert(it, modifier = Modifier.padding(bottom = 8.dp)) }
            HorizontalDivider(color = colors.rule)
            MenuRow("Stores", onClick = { vm.go(Screen.Stores) })

            Section("Switch household")
            HorizontalDivider(color = colors.rule)
            for (h in vm.households) {
                val on = h.id == vm.householdId
                MenuRow(h.name, onClick = { if (!on) vm.chooseHousehold(h) }, trailing = {
                    Icon(if (on) AppIcons.Check else AppIcons.ChevronRight, null, Modifier.size(18.dp), tint = if (on) colors.accent else colors.ink3)
                })
            }
            val invites = vm.me?.invites?.size ?: 0
            MenuRow("New household or invites", onClick = { vm.go(Screen.Households) }, trailing = {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (invites > 0) Badge("$invites")
                    Spacer(Modifier.width(8.dp))
                    Icon(AppIcons.ChevronRight, null, Modifier.size(18.dp), tint = colors.ink3)
                }
            })

            if (hs == null) {
                Text(if (status.connection == Connection.Offline) NEEDS_CONNECTION else "Loading…", color = colors.ink2, modifier = Modifier.padding(top = 24.dp))
            } else {
                if (isAdmin) {
                    Section("Household name")
                    var name by remember(hs.household.name) { mutableStateOf(hs.household.name) }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Field(name, { name = it }, Modifier.weight(1f), keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words))
                        Spacer(Modifier.width(8.dp))
                        OutlineButton("Rename", onClick = { act { vm.renameHousehold(name) } })
                    }
                }

                Section("Members")
                HorizontalDivider(color = colors.rule)
                for (m in hs.members) {
                    var managing by remember(m.id) { mutableStateOf(false) }
                    var temp by remember(m.id) { mutableStateOf("") }
                    Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            buildAnnotatedString {
                                append(m.username)
                                if (m.isMe) withStyle(SpanStyle(color = colors.ink2, fontWeight = FontWeight.Normal)) { append(" (you)") }
                            },
                            Modifier.weight(1f), fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink,
                        )
                        if (m.role == "admin") Badge("Admin")
                        if (isAdmin && !m.isMe) {
                            Text("Manage", Modifier.clickable { managing = !managing }.padding(start = 12.dp, top = 8.dp, bottom = 8.dp), color = colors.accent, fontWeight = FontWeight.SemiBold)
                        }
                    }
                    if (managing) {
                        Column(Modifier.padding(bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            OutlineButton(if (m.role == "admin") "Make regular member" else "Make admin", small = true,
                                onClick = { act { vm.setRole(m.id, if (m.role == "admin") "member" else "admin") } })
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Field(temp, { temp = it }, Modifier.weight(1f), placeholder = "Temporary password", keyboardOptions = noAutocorrect)
                                Spacer(Modifier.width(8.dp))
                                OutlineButton("Reset password", small = true, onClick = { act { vm.resetPassword(m.id, temp).also { if (it == null) temp = "" } } })
                            }
                            OutlineButton("Remove from household", danger = true, small = true, onClick = { removing = m.id })
                        }
                    }
                    HorizontalDivider(color = colors.rule)
                }

                if (isAdmin) {
                    Section("Invite someone")
                    var who by remember { mutableStateOf("") }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Field(who, { who = it }, Modifier.weight(1f), placeholder = "Their username", keyboardOptions = noAutocorrect)
                        Spacer(Modifier.width(8.dp))
                        PrimaryButton("Invite", enabled = who.isNotBlank(), onClick = { act { vm.inviteMember(who).also { if (it == null) who = "" } } })
                    }
                    if (hs.invites.isNotEmpty()) {
                        Section("Pending invites")
                        HorizontalDivider(color = colors.rule)
                        for (inv in hs.invites) {
                            Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text(inv.username, Modifier.weight(1f), fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                                OutlineButton("Cancel", small = true, onClick = { act { vm.cancelInvite(inv.id) } })
                            }
                            HorizontalDivider(color = colors.rule)
                        }
                    }
                }
            }

            Section("Account")
            HorizontalDivider(color = colors.rule)
            MenuRow(vm.username, onClick = { vm.go(Screen.Account) })
            Row(Modifier.fillMaxWidth().clickable { if (vm.pendingCount() > 0) confirmLogout = true else vm.logout() }.heightIn(min = 56.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Log out", color = colors.danger, fontSize = 17.sp)
            }
            HorizontalDivider(color = colors.rule)

            // The app's own part: syncing (the website shows this as the "Offline" pill).
            Section("Sync")
            val (dot, line) = when (status.connection) {
                Connection.Live -> colors.successInk to "Connected. Changes from others show up as they happen."
                Connection.Online -> colors.successInk to "Connected."
                Connection.Offline -> colors.ink3 to "Can't reach the server. Lists and recipes still work here; changes are saved on this phone and sent when it's back."
                Connection.Connecting -> colors.ink3 to "Connecting…"
            }
            Row(verticalAlignment = Alignment.Top) {
                Box(Modifier.padding(top = 7.dp).size(9.dp).clip(CircleShape).background(dot))
                Text(line, Modifier.padding(start = 10.dp), color = colors.ink, fontSize = 16.sp, lineHeight = 23.sp)
            }
            Text(
                (if (status.pending == 0) "Everything is synced" else "${status.pending} change${if (status.pending == 1) "" else "s"} waiting to sync") +
                    " · last synced ${ago(status.lastSynced, now)}",
                Modifier.padding(top = 6.dp, start = 19.dp, bottom = 12.dp), color = colors.ink2, fontSize = 14.sp,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlineButton(if (syncing) "Syncing…" else "Sync now", small = true, icon = AppIcons.Refresh, onClick = {
                    if (!syncing) scope.launch {
                        syncing = true
                        vm.refresh()
                        syncing = false
                    }
                })
                OutlineButton("Open the website", small = true, icon = AppIcons.External,
                    onClick = { runCatching { uri.openUri(vm.webUrl("/h/${vm.householdId}/settings")) } })
            }

            if (hs != null) {
                Section("Leave or delete")
                if (hs.members.size > 1) OutlineButton("Leave household", onClick = { confirmLeave = true })
                if (isAdmin) {
                    var confirmName by remember { mutableStateOf("") }
                    Text(
                        buildAnnotatedString {
                            append("Deletes this household with all of its lists, stores, catalog and recipes. Type ")
                            withStyle(SpanStyle(fontWeight = FontWeight.Bold, color = colors.ink)) { append(hs.household.name) }
                            append(" to confirm.")
                        },
                        Modifier.padding(top = 16.dp, bottom = 8.dp), color = colors.ink2, fontSize = 14.sp,
                    )
                    Field(confirmName, { confirmName = it }, keyboardOptions = noAutocorrect)
                    Spacer(Modifier.size(10.dp))
                    OutlineButton("Delete household", danger = true, onClick = { act { vm.leaveOrDelete(confirmName) } })
                }
            }
        }
    }
    if (confirmLeave && hs != null) {
        Confirm("Leave ${hs.household.name}? You'll need a new invite to come back.", "Leave",
            onDismiss = { confirmLeave = false }, onConfirm = { act { vm.leaveOrDelete(null) } })
    }
    removing?.let { id ->
        val m = hs?.members?.firstOrNull { it.id == id }
        if (m != null && hs != null) {
            Confirm("Remove ${m.username} from ${hs.household.name}?", "Remove", onDismiss = { removing = null }, onConfirm = { act { vm.removeMember(id) } })
        }
    }
    if (confirmLogout) LogoutConfirm(vm) { confirmLogout = false }
}
