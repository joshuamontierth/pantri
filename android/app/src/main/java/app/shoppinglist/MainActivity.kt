package app.shoppinglist

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
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
import androidx.lifecycle.viewmodel.compose.viewModel
import app.shoppinglist.data.Connection
import app.shoppinglist.ui.AppViewModel
import app.shoppinglist.ui.HouseholdPicker
import app.shoppinglist.ui.ListsScreen
import app.shoppinglist.ui.OutlineButton
import app.shoppinglist.ui.PlanScreen
import app.shoppinglist.ui.RecipeScreen
import app.shoppinglist.ui.RecipesScreen
import app.shoppinglist.ui.Screen
import app.shoppinglist.ui.SettingsScreen
import app.shoppinglist.ui.SetupScreen
import app.shoppinglist.ui.ShoppingTheme
import app.shoppinglist.ui.colors

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { ShoppingTheme { AppRoot(viewModel()) } }
    }
}

@Composable
private fun AppRoot(vm: AppViewModel) {
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(vm) {
        vm.messages.collect { msg ->
            snackbar.currentSnackbarData?.dismiss()
            val result = snackbar.showSnackbar(
                msg.text,
                actionLabel = if (msg.undo != null) "Undo" else null,
                duration = if (msg.undo != null) SnackbarDuration.Long else SnackbarDuration.Short,
            )
            if (result == SnackbarResult.ActionPerformed) msg.undo?.let(vm::undo)
        }
    }
    when {
        !vm.loggedIn -> SetupScreen(vm)
        vm.householdId < 0 -> HouseholdPicker(vm)
        else -> MainScreens(vm, snackbar)
    }
}

@Composable
private fun MainScreens(vm: AppViewModel, snackbar: SnackbarHostState) {
    val view by vm.view.collectAsStateWithLifecycle()
    val status by vm.status.collectAsStateWithLifecycle()
    BackHandler(enabled = vm.stack.size > 1) { vm.back() }

    if (vm.householdGone) {
        AlertDialog(
            onDismissRequest = {},
            containerColor = colors.sheet,
            title = { Text("Household unavailable") },
            text = { Text("It was deleted, or you're no longer a member.") },
            confirmButton = { TextButton(onClick = { vm.forgetHousehold() }) { Text("Pick another", color = colors.ink) } },
        )
    }

    val current = view
    val screen = vm.screen
    if (current == null && screen != Screen.Settings) {
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
        Screen.Lists -> ListsScreen(vm, current!!, status, snackbar)
        Screen.Recipes -> RecipesScreen(vm, current!!, status, snackbar)
        is Screen.Recipe -> RecipeScreen(vm, current!!, screen.id, snackbar)
        is Screen.Plan -> PlanScreen(vm, current!!, screen.recipeIds, snackbar)
        Screen.Settings -> SettingsScreen(vm, current, status, snackbar)
    }
}
