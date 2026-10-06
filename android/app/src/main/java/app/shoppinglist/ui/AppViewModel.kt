package app.shoppinglist.ui

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.shoppinglist.ShoppingApp
import app.shoppinglist.data.AddOp
import app.shoppinglist.data.ApiException
import app.shoppinglist.data.CheckOp
import app.shoppinglist.data.DeleteOp
import app.shoppinglist.data.EngineEvent
import app.shoppinglist.data.Household
import app.shoppinglist.data.ItemKey
import app.shoppinglist.data.LocalItem
import app.shoppinglist.data.Op
import app.shoppinglist.data.Part
import app.shoppinglist.data.ReorderOp
import app.shoppinglist.data.UpdateOp
import app.shoppinglist.data.toJson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.UUID

sealed interface Screen {
    data object Lists : Screen
    data object Recipes : Screen
    data class Recipe(val id: Long) : Screen
    data class Plan(val recipeIds: List<Long>) : Screen
    data object Settings : Screen
}

/** Undo puts back what a delete or clear removed. */
data class Undo(val opIds: List<String>, val items: List<LocalItem>)

data class UiMessage(val text: String, val undo: Undo? = null)

/** One ingredient row to add from the recipe picker. */
data class PlanAdd(val name: String, val parts: List<Part>, val storeId: Long?, val tags: List<String>)

class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val shopping = app as ShoppingApp
    private val settings = shopping.settings
    private val engine = shopping.engine

    val view = engine.view
    val status = engine.status

    var loggedIn by mutableStateOf(settings.token != null)
        private set
    var households by mutableStateOf(settings.households)
        private set
    var householdId by mutableStateOf(settings.householdId)
        private set
    val serverUrl get() = settings.serverUrl
    val username get() = settings.username

    /** Screens, newest last. The first is Lists or Recipes (the top-level tabs). */
    val stack = mutableStateListOf<Screen>(Screen.Lists)
    val screen: Screen get() = stack.last()

    private val _messages = MutableSharedFlow<UiMessage>(extraBufferCapacity = 8)
    val messages = _messages.asSharedFlow()

    var householdGone by mutableStateOf(false)
        private set

    init {
        viewModelScope.launch {
            engine.events.collect { event ->
                when (event) {
                    is EngineEvent.Message -> _messages.emit(UiMessage(event.text))
                    EngineEvent.LoggedOut -> signOutLocally(keepData = true)
                    EngineEvent.HouseholdGone -> householdGone = true
                }
            }
        }
        if (loggedIn) refreshHouseholds()
    }

    // ---------- navigation ----------

    fun tab(screen: Screen) {
        stack.clear()
        stack.add(screen)
    }

    fun go(screen: Screen) {
        stack.add(screen)
    }

    fun back(): Boolean {
        if (stack.size <= 1) return false
        stack.removeAt(stack.lastIndex)
        return true
    }

    // ---------- account ----------

    /** Returns an error message, or null when logged in. */
    suspend fun login(server: String, username: String, password: String): String? {
        val base = normalizeServer(server) ?: return "Enter the server's address, like https://shopping.example.com"
        return try {
            val result = withContext(Dispatchers.IO) { shopping.api.login(base, username.trim(), password) }
            val owner = "${result.user.username.lowercase()}@$base"
            if (settings.dataOwner != owner) {
                shopping.store.clearAll()
                settings.householdId = -1
                settings.dataOwner = owner
            }
            settings.serverUrl = base
            settings.token = result.token
            settings.username = result.user.username
            settings.households = result.households
            households = result.households
            loggedIn = true
            val previous = result.households.firstOrNull { it.id == settings.householdId }
            (previous ?: result.households.singleOrNull())?.let { chooseHousehold(it) } ?: run { householdId = -1 }
            null
        } catch (e: ApiException) {
            e.message
        } catch (e: IOException) {
            "Couldn't reach $base. Check the address, and that this phone is on Tailscale or the same network."
        } catch (e: IllegalArgumentException) {
            "That doesn't look like a web address."
        }
    }

    fun chooseHousehold(h: Household) {
        settings.householdId = h.id
        householdId = h.id
        householdGone = false
        engine.open(h.id)
        tab(Screen.Lists)
    }

    /** Back to the household picker (the open one was deleted, or we were removed). */
    fun forgetHousehold() {
        engine.close()
        settings.householdId = -1
        householdId = -1
        householdGone = false
        refreshHouseholds()
    }

    private fun refreshHouseholds() {
        viewModelScope.launch {
            val me = runCatching { withContext(Dispatchers.IO) { shopping.api.me() } }.getOrNull() ?: return@launch
            settings.households = me.households
            households = me.households
            if (householdId >= 0 && me.households.none { it.id == householdId }) householdGone = true
        }
    }

    fun pendingCount() = engine.pendingCount()

    fun logout() {
        viewModelScope.launch(Dispatchers.IO) { shopping.api.logout() }
        signOutLocally(keepData = false)
    }

    /**
     * keepData: the server ended the session (password reset, expiry). Queued changes stay on the
     * phone and go out after logging back in as the same person. A deliberate logout clears them.
     */
    private fun signOutLocally(keepData: Boolean) {
        engine.close()
        settings.signOut()
        if (!keepData) {
            shopping.store.clearAll()
            settings.householdId = -1
            settings.dataOwner = ""
        }
        loggedIn = false
        householdId = -1
        households = emptyList()
        tab(Screen.Lists)
    }

    suspend fun refresh() {
        engine.syncOnce()
    }

    fun webUrl(path: String = "") = settings.serverUrl.trimEnd('/') + path

    fun listPage() = settings.listPage(householdId)
    fun setListPage(page: Int) = settings.setListPage(householdId, page)

    // ---------- list changes (queued; they work offline) ----------

    private fun newId() = UUID.randomUUID().toString()
    private fun now() = LocalDateTime.now(ZoneOffset.UTC).toString()

    fun addItem(name: String, qty: String, storeId: Long?) {
        val n = name.trim()
        if (n.isEmpty()) return
        engine.enqueue(AddOp(opId = newId(), ref = newId(), name = n, qty = qty.trim().ifEmpty { null }, store = storeId))
    }

    fun setChecked(item: LocalItem, checked: Boolean) {
        engine.enqueue(CheckOp(opId = newId(), item = item.key, checked = checked, at = now()))
    }

    fun saveItem(item: LocalItem, name: String, qty: String, note: String, storeId: Long?) {
        engine.enqueue(UpdateOp(opId = newId(), item = item.key, name = name.trim().ifEmpty { item.name }, qty = qty.trim(), note = note.trim(), store = storeId))
    }

    fun deleteItem(item: LocalItem) {
        val op = DeleteOp(opId = newId(), item = item.key)
        engine.enqueue(op)
        _messages.tryEmit(UiMessage("Deleted ${item.name}", Undo(listOf(op.opId), listOf(item))))
    }

    fun clearChecked(items: List<LocalItem>) {
        if (items.isEmpty()) return
        val ops = items.map { DeleteOp(opId = newId(), item = it.key) }
        engine.enqueue(*ops.toTypedArray())
        val n = items.size
        _messages.tryEmit(UiMessage("Cleared $n item${if (n == 1) "" else "s"}", Undo(ops.map { it.opId }, items)))
    }

    fun undo(undo: Undo) {
        if (engine.cancel(undo.opIds)) return // never left the phone
        // Already on the server: add the items back.
        val ops = mutableListOf<Op>()
        for (item in undo.items) {
            val ref = newId()
            ops += AddOp(
                opId = newId(), ref = ref, name = item.name,
                qty = if (item.parts == null) item.qtyText else null, parts = item.parts?.toJson(),
                note = item.note, store = item.storeId, tags = item.tags,
            )
            if (item.checked) ops += CheckOp(opId = newId(), item = ItemKey.Local(ref), checked = true, at = now())
        }
        engine.enqueue(*ops.toTypedArray())
    }

    fun reorder(storeId: Long?, keys: List<ItemKey>) {
        engine.enqueue(ReorderOp(opId = newId(), store = storeId, items = keys))
    }

    fun addFromRecipes(rows: List<PlanAdd>, storeName: (Long?) -> String) {
        if (rows.isEmpty()) return
        val ops = rows.map {
            AddOp(opId = newId(), ref = newId(), name = it.name, parts = it.parts.toJson(), store = it.storeId, tags = it.tags)
        }
        engine.enqueue(*ops.toTypedArray())
        val stores = rows.map { storeName(it.storeId) }.distinct()
        val n = rows.size
        _messages.tryEmit(UiMessage("Added $n item${if (n == 1) "" else "s"} to ${stores.joinToString(", ")}"))
    }

    fun message(text: String) {
        _messages.tryEmit(UiMessage(text))
    }

    companion object {
        /** "shopping.example.com" -> "https://shopping.example.com". Null if blank. */
        fun normalizeServer(input: String): String? {
            var s = input.trim().trimEnd('/')
            if (s.isEmpty()) return null
            if (!s.startsWith("http://", ignoreCase = true) && !s.startsWith("https://", ignoreCase = true)) s = "https://$s"
            return s
        }
    }
}
