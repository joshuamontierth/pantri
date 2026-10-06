package app.shoppinglist.ui

import android.app.Application
import android.net.Uri
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
import app.shoppinglist.data.HouseholdSettings
import app.shoppinglist.data.ItemKey
import app.shoppinglist.data.LocalItem
import app.shoppinglist.data.LoginResult
import app.shoppinglist.data.Me
import app.shoppinglist.data.Op
import app.shoppinglist.data.Part
import app.shoppinglist.data.PhotoException
import app.shoppinglist.data.Photos
import app.shoppinglist.data.RecipeDraft
import app.shoppinglist.data.ReorderOp
import app.shoppinglist.data.SaveIngredient
import app.shoppinglist.data.SaveRecipe
import app.shoppinglist.data.StateResult
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

/** Every page of the website has a screen here. */
sealed interface Screen {
    // The three top tabs, like the website's header.
    data object Lists : Screen
    data object Recipes : Screen
    data object Catalog : Screen

    data class Recipe(val id: Long) : Screen
    data class PlanChoose(val preselected: List<Long> = emptyList()) : Screen
    data class Plan(val recipeIds: List<Long>) : Screen
    data object Editor : Screen // the recipe being edited is AppViewModel.editor
    data class CatalogEdit(val itemId: Long?, val name: String = "") : Screen
    data object Stores : Screen
    data object Settings : Screen
    data object Households : Screen
    data object Account : Screen
    data object ChangePassword : Screen
}

/** Undo puts back what a delete or clear removed. */
data class Undo(val opIds: List<String>, val items: List<LocalItem>)

/** A snackbar; with an action button for Undo, or actionLabel + action (Save to catalog). */
data class UiMessage(val text: String, val undo: Undo? = null, val actionLabel: String? = null, val action: (() -> Unit)? = null)

/** One ingredient row to add from the recipe picker. */
data class PlanAdd(val name: String, val parts: List<Part>, val storeId: Long?, val tags: List<String>)

/** Online actions: the value, or a message to show (the website's wording). */
sealed interface Outcome<out T> {
    data class Ok<T>(val value: T) : Outcome<T>
    data class Failed(val message: String, val errors: List<String> = emptyList()) : Outcome<Nothing>
}

const val NEEDS_CONNECTION = "Can't reach the server. This needs a connection; your lists still work offline."

/** One ingredient row in the recipe editor. */
class EditorRow(name: String, amount: String, unit: String, ranks: List<Long>, val fresh: String? = null, known: Boolean = false) {
    val key = nextKey++
    var name by mutableStateOf(name)
    var amount by mutableStateOf(amount)
    var unit by mutableStateOf(unit)
    var ranks by mutableStateOf(ranks)
    var ranksChanged by mutableStateOf(false)
    var showRanks by mutableStateOf(!known && name.isNotBlank())

    companion object {
        private var nextKey = 0L
    }
}

/** The recipe editor (the website's recipe form). */
class EditorState(draft: RecipeDraft, knownNames: Set<String>) {
    val recipeId = draft.recipeId
    var name by mutableStateOf(draft.name)
    val rows = mutableStateListOf<EditorRow>().apply {
        addAll(draft.ingredients.map { EditorRow(it.name, it.amount, it.unit, it.ranks, it.fresh, it.name.lowercase() in knownNames) })
        if (isEmpty()) repeat(3) { add(EditorRow("", "", "", emptyList())) }
    }
    var directions by mutableStateOf(draft.directions)
    var sourceUrl by mutableStateOf(draft.sourceUrl)
    val notice = draft.notice
    val freshDirections = draft.fresh.directions
    val freshLink = draft.fresh.link
    var errors by mutableStateOf(listOf<String>())
    var saving by mutableStateOf(false)
}

class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val shopping = app as ShoppingApp
    private val settings = shopping.settings
    private val engine = shopping.engine
    private val api = shopping.api

    val view = engine.view
    val status = engine.status

    var loggedIn by mutableStateOf(settings.token != null)
        private set
    var me by mutableStateOf<Me?>(null)
        private set
    var households by mutableStateOf(settings.households)
        private set
    var householdId by mutableStateOf(settings.householdId)
        private set
    var scanEnabled by mutableStateOf(settings.scanEnabled)
        private set
    var mustChangePassword by mutableStateOf(false)
        private set
    val serverUrl get() = settings.serverUrl
    val username get() = settings.username

    /** Screens, newest last. The first is one of the top tabs. */
    val stack = mutableStateListOf<Screen>(Screen.Lists)
    val screen: Screen get() = stack.last()

    private val _messages = MutableSharedFlow<UiMessage>(extraBufferCapacity = 8)
    val messages = _messages.asSharedFlow()

    var householdGone by mutableStateOf(false)
        private set

    /** The recipe open in the editor (new, edited, or read from an import). */
    var editor by mutableStateOf<EditorState?>(null)
        private set

    /** Set while the model reads a recipe ("Reading the recipe" over everything). */
    var reading by mutableStateOf(false)
        private set

    /** A link or photos shared to the app, waiting for a household to be open. */
    private var pendingShare: Pair<String?, List<Uri>>? = null

    /** The open household's settings page (members, invites), loaded when shown. */
    var householdSettings by mutableStateOf<HouseholdSettings?>(null)
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
        if (loggedIn) refreshMe()
    }

    fun message(text: String) {
        _messages.tryEmit(UiMessage(text))
    }

    // ---------- navigation ----------

    fun tab(screen: Screen) {
        stack.clear()
        stack.add(screen)
    }

    fun go(screen: Screen) {
        stack.add(screen)
    }

    /** Swap the current screen (after saving, the editor gives way to the recipe). */
    fun replace(screen: Screen) {
        stack.removeAt(stack.lastIndex)
        stack.add(screen)
    }

    fun back(): Boolean {
        if (stack.size <= 1) return false
        stack.removeAt(stack.lastIndex)
        return true
    }

    // ---------- talking to the server ----------

    private suspend fun <T> online(block: () -> T): Outcome<T> {
        val r: Outcome<T> = withContext(Dispatchers.IO) {
            try {
                Outcome.Ok(block())
            } catch (e: ApiException) {
                Outcome.Failed(e.message ?: "Something went wrong.", e.errors).also { if (e.code == 401) loggedOutFromServer = true }
            } catch (e: IOException) {
                Outcome.Failed(NEEDS_CONNECTION)
            } catch (e: PhotoException) {
                Outcome.Failed(e.message ?: "Couldn't open that photo.")
            } catch (e: RuntimeException) {
                Outcome.Failed("Something went wrong: ${e.message ?: e.javaClass.simpleName}")
            }
        }
        if (loggedOutFromServer) {
            loggedOutFromServer = false
            signOutLocally(keepData = true)
        }
        return r
    }

    @Volatile private var loggedOutFromServer = false

    private fun applyMe(m: Me) {
        me = m
        households = m.households
        settings.households = m.households
        scanEnabled = m.features.scan
        settings.scanEnabled = m.features.scan
        mustChangePassword = m.mustChangePassword
        if (householdId >= 0 && m.households.none { it.id == householdId }) householdGone = true
    }

    fun refreshMe() {
        viewModelScope.launch {
            (online { api.me() } as? Outcome.Ok)?.let { applyMe(it.value) }
        }
    }

    // ---------- account ----------

    /** Log in, or sign up when confirm is given. Returns an error message, or null when in. */
    suspend fun login(server: String, username: String, password: String, confirm: String? = null): String? {
        val base = normalizeServer(server) ?: return "Enter the server's address, like https://shopping.example.com"
        val result: LoginResult = try {
            withContext(Dispatchers.IO) {
                if (confirm == null) api.login(base, username.trim(), password) else api.signup(base, username.trim(), password, confirm)
            }
        } catch (e: ApiException) {
            return e.message
        } catch (e: IOException) {
            return "Couldn't reach $base. Check the address, and that this phone is on Tailscale or the same network."
        } catch (e: IllegalArgumentException) {
            return "That doesn't look like a web address."
        }
        val owner = "${result.user.username.lowercase()}@$base"
        if (settings.dataOwner != owner) {
            shopping.store.clearAll()
            settings.householdId = -1
            settings.dataOwner = owner
        }
        settings.serverUrl = base
        settings.token = result.token
        settings.username = result.user.username
        applyMe(result.me())
        loggedIn = true
        // Like the website's home page: straight to your household unless there's a choice to make.
        val previous = result.households.firstOrNull { it.id == settings.householdId }
        val only = result.households.singleOrNull()?.takeIf { result.invites.isEmpty() }
        val open = previous ?: only
        if (open != null) chooseHousehold(open) else householdId = -1
        return null
    }

    /** Change password; after an admin reset the current one isn't needed (like the website). Null when done. */
    suspend fun changePassword(current: String, password: String, confirm: String): String? =
        when (val r = online { api.changePassword(current, password, confirm) }) {
            is Outcome.Ok -> {
                val wasForced = mustChangePassword
                applyMe(r.value)
                if (!wasForced) {
                    back()
                    message("Password changed. Your other devices were logged out.")
                }
                null
            }
            is Outcome.Failed -> r.message
        }

    fun pendingCount() = engine.pendingCount()

    fun logout() {
        viewModelScope.launch(Dispatchers.IO) { api.logout() }
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
        me = null
        mustChangePassword = false
        householdId = -1
        households = emptyList()
        editor = null
        tab(Screen.Lists)
    }

    // ---------- households ----------

    fun chooseHousehold(h: Household) {
        settings.householdId = h.id
        householdId = h.id
        householdGone = false
        householdSettings = null
        engine.open(h.id)
        tab(Screen.Lists)
        pendingShare?.let { (text, photos) ->
            pendingShare = null
            share(text, photos)
        }
    }

    /** Back to the households page (the open one was deleted, or we were removed or left). */
    fun forgetHousehold() {
        engine.close()
        settings.householdId = -1
        householdId = -1
        householdGone = false
        householdSettings = null
        tab(Screen.Lists)
        refreshMe()
    }

    suspend fun createHousehold(name: String): String? = when (val r = online { api.createHousehold(name) }) {
        is Outcome.Ok -> {
            applyMe(r.value)
            r.value.households.firstOrNull { it.id == r.value.householdId }?.let {
                chooseHousehold(it)
                go(Screen.Settings)
                go(Screen.Stores) // like the website: add your stores next
            }
            null
        }
        is Outcome.Failed -> r.message
    }

    suspend fun acceptInvite(id: Long): String? = when (val r = online { api.acceptInvite(id) }) {
        is Outcome.Ok -> {
            applyMe(r.value)
            r.value.households.firstOrNull { it.id == r.value.householdId }?.let(::chooseHousehold)
            null
        }
        is Outcome.Failed -> r.message
    }

    suspend fun declineInvite(id: Long): String? = when (val r = online { api.declineInvite(id) }) {
        is Outcome.Ok -> {
            applyMe(r.value)
            null
        }
        is Outcome.Failed -> r.message
    }

    fun loadHouseholdSettings() {
        val hid = householdId
        viewModelScope.launch {
            refreshMe()
            when (val r = online { api.householdSettings(hid) }) {
                is Outcome.Ok -> householdSettings = r.value
                is Outcome.Failed -> if (householdSettings == null) message(r.message)
            }
        }
    }

    /** A settings-page action; its notice (if any) shows as a message. Returns an error or null. */
    private suspend fun settingsAction(block: (Long) -> HouseholdSettings): String? {
        val hid = householdId
        return when (val r = online { block(hid) }) {
            is Outcome.Ok -> {
                householdSettings = r.value
                r.value.notice?.let(::message)
                refreshMe()
                null
            }
            is Outcome.Failed -> r.message
        }
    }

    suspend fun renameHousehold(name: String) = settingsAction { api.renameHousehold(it, name) }
    suspend fun inviteMember(username: String) = settingsAction { api.invite(it, username) }
    suspend fun cancelInvite(id: Long) = settingsAction { api.cancelInvite(it, id) }
    suspend fun setRole(memberId: Long, role: String) = settingsAction { api.setRole(it, memberId, role) }
    suspend fun removeMember(memberId: Long) = settingsAction { api.removeMember(it, memberId) }
    suspend fun resetPassword(memberId: Long, temp: String) = settingsAction { api.resetPassword(it, memberId, temp) }

    /** Leave the open household, or delete it when confirmName is given. */
    suspend fun leaveOrDelete(confirmName: String?): String? {
        val hid = householdId
        return when (val r = online { if (confirmName == null) api.leaveHousehold(hid) else api.deleteHousehold(hid, confirmName) }) {
            is Outcome.Ok -> {
                applyMe(r.value)
                forgetHousehold()
                null
            }
            is Outcome.Failed -> r.message
        }
    }

    // ---------- stores and catalog (online; the answer carries the fresh household) ----------

    private suspend fun stateAction(block: (Long) -> StateResult): Outcome<StateResult> {
        val hid = householdId
        val r = online { block(hid) }
        if (r is Outcome.Ok) engine.acceptState(hid, r.value.state)
        return r
    }

    private fun Outcome<*>.error() = (this as? Outcome.Failed)?.message

    suspend fun addStore(name: String) = stateAction { api.addStore(it, name) }.error()
    suspend fun renameStore(id: Long, name: String) = stateAction { api.renameStore(it, id, name) }.error()
    suspend fun reorderStores(ids: List<Long>) = stateAction { api.reorderStores(it, ids) }.error()
    suspend fun deleteStore(id: Long) = stateAction { api.deleteStore(it, id) }.error()

    /** The catalog's store filter: "all", "none" (Other) or a store id. Remembered, like the website. */
    var catalogFilter: String
        get() = settings.catalogFilter
        set(v) {
            settings.catalogFilter = v
        }

    /** Save a catalog item (new when id is null). Returns an error, or null when saved. */
    suspend fun saveCatalogItem(id: Long?, name: String, ranks: List<Long>): String? =
        stateAction { if (id == null) api.createCatalogItem(it, name, ranks) else api.updateCatalogItem(it, id, name, ranks) }.error()

    suspend fun deleteCatalogItem(id: Long) = stateAction { api.deleteCatalogItem(it, id) }.error()

    // ---------- recipes (online, like the website) ----------

    private fun knownNames() = view.value?.catalog?.map { it.name.lowercase() }?.toSet().orEmpty()

    fun newRecipe() {
        editor = EditorState(RecipeDraft(), knownNames())
        go(Screen.Editor)
    }

    fun editRecipe(id: Long) {
        val hid = householdId
        viewModelScope.launch {
            when (val r = online { api.recipeDraft(hid, id) }) {
                is Outcome.Ok -> {
                    editor = EditorState(r.value, knownNames())
                    go(Screen.Editor)
                }
                is Outcome.Failed -> message(r.message)
            }
        }
    }

    fun saveEditor() {
        val ed = editor ?: return
        val hid = householdId
        val body = SaveRecipe(
            name = ed.name.trim(),
            ingredients = ed.rows.map { SaveIngredient(it.name.trim(), it.amount.trim(), it.unit.trim(), it.ranks, it.ranksChanged) },
            directions = ed.directions,
            sourceUrl = ed.sourceUrl.trim(),
        )
        ed.saving = true
        viewModelScope.launch {
            when (val r = online { api.saveRecipe(hid, ed.recipeId, body) }) {
                is Outcome.Ok -> {
                    engine.acceptState(hid, r.value.state)
                    editor = null
                    val id = r.value.recipeId
                    if (id != null) replace(Screen.Recipe(id)) else back()
                    if (ed.recipeId != null) back() // the recipe page that opened the editor
                }
                is Outcome.Failed -> ed.errors = r.errors.ifEmpty { listOf(r.message) }
            }
            ed.saving = false
        }
    }

    fun closeEditor() {
        editor = null
        back()
    }

    suspend fun deleteRecipe(id: Long): String? = stateAction { api.deleteRecipe(it, id) }.error()

    suspend fun copyRecipe(id: Long, target: Household): String? {
        val hid = householdId
        return when (val r = online { api.copyRecipe(hid, id, target.id) }) {
            is Outcome.Ok -> {
                chooseHousehold(target)
                go(Screen.Recipes)
                go(Screen.Recipe(r.value.recipeId))
                message("Copied into ${target.name}. Ingredients that were new here have no stores yet.")
                null
            }
            is Outcome.Failed -> r.message
        }
    }

    /** Read a recipe from photos or a link. recipeId: only fill that recipe's gaps (Add details). */
    fun importRecipe(photos: List<Uri>, link: String?, recipeId: Long?) {
        val hid = householdId
        reading = true
        viewModelScope.launch {
            val r = online {
                if (link != null) api.importLink(hid, link, recipeId)
                else api.scanRecipe(hid, photos.take(4).map { Photos.prepare(getApplication(), it) }, recipeId)
            }
            reading = false
            when (r) {
                is Outcome.Ok -> {
                    val draft = r.value
                    if (draft.nothingNew) {
                        message(draft.notice ?: "Nothing new to add.")
                    } else {
                        editor = EditorState(draft, knownNames())
                        go(Screen.Editor)
                    }
                }
                is Outcome.Failed -> message(r.message)
            }
        }
    }

    /** Something shared from another app: a recipe link, or photos of a recipe. */
    fun share(text: String?, photos: List<Uri>) {
        if (!loggedIn || householdId < 0) {
            pendingShare = text to photos
            return
        }
        val link = text?.let { Regex("""https?://\S+""").find(it)?.value }
        when {
            photos.isNotEmpty() && scanEnabled -> {
                tab(Screen.Recipes)
                importRecipe(photos, null, null)
            }
            link != null -> {
                tab(Screen.Recipes)
                importRecipe(emptyList(), link, null)
            }
            else -> message("Share a link to a recipe page, or photos of a recipe.")
        }
    }

    // ---------- list changes (queued; they work offline) ----------

    private fun newId() = UUID.randomUUID().toString()
    private fun now() = LocalDateTime.now(ZoneOffset.UTC).toString()

    fun webUrl(path: String = "") = settings.serverUrl.trimEnd('/') + path

    fun listPage() = settings.listPage(householdId)
    fun setListPage(page: Int) = settings.setListPage(householdId, page)

    suspend fun refresh() {
        engine.syncOnce()
    }

    fun addItem(name: String, qty: String, storeId: Long?) {
        val n = name.trim()
        if (n.isEmpty()) return
        val v = view.value
        val merged = v?.unchecked(storeId)?.any { it.name.equals(n, ignoreCase = true) } == true
        val known = v?.catalogItem(n) != null
        engine.enqueue(AddOp(opId = newId(), ref = newId(), name = n, qty = qty.trim().ifEmpty { null }, store = storeId))
        val where = v?.storeName(storeId) ?: ""
        val text = if (merged) "Updated $n on $where" else "Added $n to $where"
        // Like the website: offer to put something new in the catalog.
        _messages.tryEmit(
            if (known) UiMessage(text)
            else UiMessage(text, actionLabel = "Save to catalog", action = { go(Screen.CatalogEdit(null, n)) }),
        )
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

    fun addFromRecipes(rows: List<PlanAdd>) {
        if (rows.isEmpty()) return
        val ops = rows.map {
            AddOp(opId = newId(), ref = newId(), name = it.name, parts = it.parts.toJson(), store = it.storeId, tags = it.tags)
        }
        engine.enqueue(*ops.toTypedArray())
        val n = rows.size
        _messages.tryEmit(UiMessage("Added $n item${if (n == 1) "" else "s"} from recipes"))
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
