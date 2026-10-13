package app.shoppinglist

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.shoppinglist.data.Connection
import app.shoppinglist.ui.AccountScreen
import app.shoppinglist.ui.AppViewModel
import app.shoppinglist.ui.CatalogEditScreen
import app.shoppinglist.ui.CatalogScreen
import app.shoppinglist.ui.ChangePasswordScreen
import app.shoppinglist.ui.EditorScreen
import app.shoppinglist.ui.HouseholdsScreen
import app.shoppinglist.ui.ListsScreen
import app.shoppinglist.ui.OutlineButton
import app.shoppinglist.ui.PlanChooseScreen
import app.shoppinglist.ui.PlanScreen
import app.shoppinglist.ui.ReadingOverlay
import app.shoppinglist.ui.RecipeScreen
import app.shoppinglist.ui.RecipesScreen
import app.shoppinglist.ui.ScanReviewScreen
import app.shoppinglist.ui.Screen
import app.shoppinglist.ui.SettingsScreen
import app.shoppinglist.ui.SetupScreen
import app.shoppinglist.ui.ShoppingTheme
import app.shoppinglist.ui.StoresScreen
import app.shoppinglist.ui.colors

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { ShoppingTheme { AppRoot(vm) } }
        if (savedInstanceState == null) handleShare(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShare(intent)
    }

    /** A recipe link or photos shared from another app (Chrome, Photos...). */
    private fun handleShare(intent: Intent?) {
        intent ?: return
        val photos = mutableListOf<Uri>()
        when (intent.action) {
            Intent.ACTION_SEND -> {
                streamExtra(intent)?.let(photos::add)
                if (photos.isEmpty() && intent.getStringExtra(Intent.EXTRA_TEXT) == null) return
            }
            Intent.ACTION_SEND_MULTIPLE -> photos += streamsExtra(intent)
            else -> return
        }
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)
        vm.share(text, if (intent.type?.startsWith("image/") == true) photos else emptyList())
    }

    @Suppress("DEPRECATION")
    private fun streamExtra(intent: Intent): Uri? =
        if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else intent.getParcelableExtra(Intent.EXTRA_STREAM)

    @Suppress("DEPRECATION")
    private fun streamsExtra(intent: Intent): List<Uri> =
        (if (Build.VERSION.SDK_INT >= 33) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM)).orEmpty()
}

@Composable
private fun AppRoot(vm: AppViewModel) {
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(vm) {
        vm.messages.collect { msg ->
            snackbar.currentSnackbarData?.dismiss()
            val label = msg.actionLabel ?: if (msg.undo != null) "Undo" else null
            val result = snackbar.showSnackbar(
                msg.text,
                actionLabel = label,
                duration = if (label != null) SnackbarDuration.Long else SnackbarDuration.Short,
            )
            if (result == SnackbarResult.ActionPerformed) {
                msg.undo?.let(vm::undo)
                msg.action?.invoke()
            }
        }
    }
    Box(Modifier.fillMaxSize()) {
        when {
            !vm.loggedIn -> SetupScreen(vm)
            vm.mustChangePassword -> ChangePasswordScreen(vm, forced = true)
            vm.householdId < 0 -> HouseholdsScreen(vm, canGoBack = false)
            else -> MainScreens(vm, snackbar)
        }
        vm.reading?.let { ReadingOverlay(it) }
    }
}

@Composable
private fun MainScreens(vm: AppViewModel, snackbar: SnackbarHostState) {
    val view by vm.view.collectAsStateWithLifecycle()
    val status by vm.status.collectAsStateWithLifecycle()
    BackHandler(enabled = vm.stack.size > 1) {
        when (vm.screen) {
            Screen.Editor -> vm.closeEditor()
            Screen.ScanReview -> vm.closeScanReview()
            else -> vm.back()
        }
    }

    if (vm.householdGone) {
        AlertDialog(
            onDismissRequest = {},
            containerColor = colors.sheet,
            title = { Text("Household unavailable") },
            text = { Text("It was deleted, or you're no longer a member.") },
            confirmButton = { TextButton(onClick = { vm.forgetHousehold() }) { Text("Pick another", color = colors.ink) } },
        )
    }

    val screen = vm.screen
    // Screens that don't need the household's copy.
    when (screen) {
        Screen.Settings -> return SettingsScreen(vm, status, snackbar)
        Screen.Households -> return HouseholdsScreen(vm, canGoBack = true)
        Screen.Account -> return AccountScreen(vm)
        Screen.ChangePassword -> return ChangePasswordScreen(vm, forced = false)
        else -> Unit
    }
    val current = view
    if (current == null) {
        // First launch for this household: nothing saved on the phone yet.
        Column(Modifier.fillMaxSize().background(colors.paper).padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    if (status.connection == Connection.Offline) {
                        Text("Can't reach the server", fontSize = 20.sp, color = colors.ink)
                        Text("Your lists will appear once this phone has connected once.", Modifier.padding(top = 6.dp, bottom = 16.dp), color = colors.ink2)
                        OutlineButton("Settings", onClick = { vm.go(Screen.Settings) })
                    } else {
                        CircularProgressIndicator(Modifier.size(36.dp), color = colors.accent)
                    }
                }
            }
        }
        return
    }

    when (screen) {
        Screen.Lists -> ListsScreen(vm, current, status, snackbar)
        Screen.Recipes -> RecipesScreen(vm, current, status, snackbar)
        Screen.Catalog -> CatalogScreen(vm, current, status, snackbar)
        is Screen.Recipe -> RecipeScreen(vm, current, screen.id, snackbar)
        is Screen.PlanChoose -> PlanChooseScreen(vm, current, screen.preselected, snackbar)
        is Screen.Plan -> PlanScreen(vm, current, screen.recipeIds, snackbar)
        is Screen.CatalogEdit -> CatalogEditScreen(vm, current, screen.itemId, screen.name, snackbar)
        Screen.Stores -> StoresScreen(vm, current, snackbar)
        Screen.Editor -> vm.editor?.let { EditorScreen(vm, current, it, snackbar) } ?: run { vm.back() }
        Screen.ScanReview -> vm.scanReview?.let { ScanReviewScreen(vm, current, it, snackbar) } ?: run { vm.back() }
        else -> Unit
    }
}
