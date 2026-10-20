package app.pantri.ui

import android.app.Application
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.pantri.BuildConfig
import app.pantri.PantriApp
import app.pantri.data.AddOp
import app.pantri.data.AddScanned
import app.pantri.data.AddScannedItem
import app.pantri.data.ApiException
import app.pantri.data.CheckOp
import app.pantri.data.DeleteOp
import app.pantri.data.DuplicatesResult
import app.pantri.data.EngineEvent
import app.pantri.data.Household
import app.pantri.data.HouseholdSettings
import app.pantri.data.ItemKey
import app.pantri.data.LocalItem
import app.pantri.data.LocalView
import app.pantri.data.LoginResult
import app.pantri.data.Me
import app.pantri.data.Op
import app.pantri.data.Part
import app.pantri.data.PhotoException
import app.pantri.data.Photos
import app.pantri.data.RecipeDraft
import app.pantri.data.ReorderOp
import app.pantri.data.SaveIngredient
import app.pantri.data.SaveRecipe
import app.pantri.data.ScannedItem
import app.pantri.data.ScannedList
import app.pantri.data.StateResult
import app.pantri.data.UpdateOp
import app.pantri.data.toJson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.UUID

/** Every page of the website has a screen here. */
sealed interface Screen {
    // The top tabs, like the website's header.
    data object Lists : Screen
    data object Meals : Screen
    data object Recipes : Screen
    data object Catalog : Screen

    data class Recipe(val id: Long) : Screen
    data class PlanChoose(val preselected: List<Long> = emptyList()) : Screen
    data class Plan(val recipeIds: List<Long>) : Screen
    data object Editor : Screen // the recipe being edited is AppViewModel.editor
    data object ScanReview : Screen // what was read from a shopping list is AppViewModel.scanReview
    data object Duplicates : Screen // the groups being gone through are AppViewModel.duplicates
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

/** One row of "Add from your list": what the list reader found, as the person fixes it up. */
class ScanRow(item: ScannedItem) {
    val key = nextKey++
    private val original = item.name
    private val suggested = item.store
    val readAs = item.readAs
    val onList = item.onList
    var name by mutableStateOf(item.name)
    var qty by mutableStateOf(item.qty)
    var include by mutableStateOf(true)
    /** A store picked by hand (pickedStore null is Other) stays picked when the name changes. */
    var pickedByHand by mutableStateOf(false)
    var pickedStore by mutableStateOf<Long?>(null)

    private val unchanged get() = name.trim().equals(original, ignoreCase = true)

    /** Like the website: a different name is matched to the catalog again. */
    fun isNew(view: LocalView) = name.isNotBlank() && view.matchCatalog(name) == null
    fun ranks(view: LocalView) = view.matchCatalog(name)?.ranks.orEmpty().filter { view.hasStore(it) }
    fun store(view: LocalView): Long? = when {
        pickedByHand -> pickedStore.takeIf { view.hasStore(it) }
        unchanged -> suggested.takeIf { view.hasStore(it) }
        else -> ranks(view).firstOrNull()
    }
    fun showOnList() = unchanged && onList.isNotEmpty()

    companion object {
        private var nextKey = 0L
    }
}

/** "Add from your list" (the website's review page after scanning a list). Nothing is added until Add. */
class ScanReview(list: ScannedList) {
    val notice = list.notice
    val rows = list.items.map(::ScanRow)
    var saveNew by mutableStateOf(true)
    var adding by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
}

/** Going through possible duplicates (the website's page): one group at a time, merge or not. */
class DuplicatesReview(result: DuplicatesResult) {
    val groups = result.groups
    val usesModel = result.usesModel
    var index by mutableStateOf(0)
    var merged by mutableStateOf(0)
    var skipped by mutableStateOf(0)
    /** For the group on screen: the item to keep (null: the suggested one), and any left out. */
    var keep by mutableStateOf<Long?>(null)
    val leftOut = mutableStateListOf<Long>()
    var busy by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    fun next() {
        index++
        keep = null
        leftOut.clear()
        error = null
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
    private val pantri = app as PantriApp
    private val settings = pantri.settings
    private val engine = pantri.engine
    private val api = pantri.api

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

    /** Set while the model reads: "Reading the recipe" or "Reading the list", over everything. */
    var reading by mutableStateOf<String?>(null)
        private set

    /** A shopping list just read, being checked before it's added. */
    var scanReview by mutableStateOf<ScanReview?>(null)
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
        val base = normalizeServer(server) ?: return "Enter the server's address, like $EXAMPLE_SERVER"
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
            pantri.store.clearAll()
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
            pantri.store.clearAll()
            settings.householdId = -1
            settings.dataOwner = ""
        }
        loggedIn = false
        me = null
        mustChangePassword = false
        householdId = -1
        households = emptyList()
        editor = null
        scanReview = null
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

    /** Merge catalog items into one. Returns an error, or null when merged. */
    suspend fun mergeCatalog(keep: Long, others: List<Long>): String? = stateAction { api.mergeCatalog(it, keep, others) }.error()

    var duplicates by mutableStateOf<DuplicatesReview?>(null)
        private set

    /** Look for catalog items that are the same product, then go through them. */
    fun findDuplicates() {
        val hid = householdId
        reading = "Looking for duplicates"
        viewModelScope.launch {
            val r = online { api.findDuplicates(hid) }
            reading = null
            when (r) {
                is Outcome.Ok -> {
                    duplicates = DuplicatesReview(r.value)
                    go(Screen.Duplicates)
                }
                is Outcome.Failed -> message(r.message)
            }
        }
    }

    /** Merge the group on screen (keeping one) or leave it, then on to the next. */
    fun decideDuplicates(merge: Boolean, keep: Long, others: List<Long>) {
        val review = duplicates ?: return
        if (!merge) {
            review.skipped++
            review.next()
            return
        }
        review.busy = true
        viewModelScope.launch {
            val failed = if (others.isEmpty()) "Pick at least two to merge, and the one to keep." else mergeCatalog(keep, others)
            review.busy = false
            if (failed != null) {
                review.error = failed
            } else {
                review.merged++
                review.next()
            }
        }
    }

    fun closeDuplicates() {
        duplicates = null
        back()
    }

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
        reading = "Reading the recipe"
        viewModelScope.launch {
            val r = online {
                if (link != null) api.importLink(hid, link, recipeId)
                else api.scanRecipe(hid, photos.take(4).map { Photos.prepare(getApplication(), it) }, recipeId)
            }
            reading = null
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

    // ---------- the meal calendar (changes are online, like the website; it reads from the household copy) ----------

    /** The Sunday of the week on screen; null is this week. */
    var mealsWeek by mutableStateOf<LocalDate?>(null)

    /** Recipes and/or a meal without one on a lunch or dinner. Returns an error, or null when added. */
    suspend fun addMeals(day: LocalDate, slot: String, recipeIds: List<Long>, title: String): String? =
        stateAction { api.addMeals(it, day.toString(), slot, recipeIds, title.trim()) }.error()

    fun deleteMeal(id: Long) {
        viewModelScope.launch { stateAction { api.deleteMeal(it, id) }.error()?.let(::message) }
    }

    // ---------- a shopping list from photos or pasted text (online, like the website) ----------

    /** Read a shopping list from photos, or from text when there are none, and open it for checking. */
    fun scanList(photos: List<Uri>, text: String?) {
        val hid = householdId
        reading = "Reading the list"
        viewModelScope.launch {
            val r = online { api.scanList(hid, photos.take(4).map { Photos.prepare(getApplication(), it) }, text) }
            reading = null
            when (r) {
                is Outcome.Ok -> {
                    scanReview = ScanReview(r.value)
                    go(Screen.ScanReview)
                }
                is Outcome.Failed -> message(r.message)
            }
        }
    }

    /** Add the checked rows; new things join the catalog when saveNew is on. Then on to the lists. */
    fun addScanned() {
        val review = scanReview ?: return
        val v = view.value ?: return
        val hid = householdId
        val picked = review.rows.filter { it.include }
        val body = AddScanned(picked.map { AddScannedItem(it.name.trim(), it.qty.trim(), it.store(v)) }, review.saveNew)
        review.adding = true
        review.error = null
        viewModelScope.launch {
            when (val r = online { api.addScanned(hid, body) }) {
                is Outcome.Ok -> {
                    engine.acceptState(hid, r.value.state)
                    scanReview = null
                    // Like the website: open the lists at the first store something went to.
                    setListPage(v.listIds.indexOf(r.value.storeId).coerceAtLeast(0))
                    tab(Screen.Lists)
                    val n = r.value.added
                    message("Added $n item${if (n == 1) "" else "s"} from your list")
                }
                is Outcome.Failed -> review.error = r.message
            }
            review.adding = false
        }
    }

    fun closeScanReview() {
        scanReview = null
        back()
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
        /** Your server (ANDROID_SERVER_URL in .env), or an example of what an address looks like. */
        val EXAMPLE_SERVER: String = BuildConfig.SERVER_URL.ifEmpty { "https://pantri.example.com" }

        /** "pantri.example.com" -> "https://pantri.example.com". Null if blank. */
        fun normalizeServer(input: String): String? {
            var s = input.trim().trimEnd('/')
            if (s.isEmpty()) return null
            if (!s.startsWith("http://", ignoreCase = true) && !s.startsWith("https://", ignoreCase = true)) s = "https://$s"
            return s
        }
    }
}
