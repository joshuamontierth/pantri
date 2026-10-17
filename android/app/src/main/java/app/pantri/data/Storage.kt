package app.pantri.data

import android.content.Context
import androidx.core.util.AtomicFile
import kotlinx.serialization.builtins.ListSerializer
import java.io.File
import java.util.UUID

/** Small settings: where the server is, who's logged in, which household is open. */
class Settings(context: Context) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = prefs.getString("server_url", "") ?: ""
        set(v) = prefs.edit().putString("server_url", v).apply()

    var token: String?
        get() = prefs.getString("token", null)
        set(v) = prefs.edit().putString("token", v).apply()

    var username: String
        get() = prefs.getString("username", "") ?: ""
        set(v) = prefs.edit().putString("username", v).apply()

    var householdId: Long
        get() = prefs.getLong("household_id", -1)
        set(v) = prefs.edit().putLong("household_id", v).apply()

    var households: List<Household>
        get() = prefs.getString("households", null)?.let {
            runCatching { AppJson.decodeFromString(ListSerializer(Household.serializer()), it) }.getOrNull()
        } ?: emptyList()
        set(v) = prefs.edit().putString("households", AppJson.encodeToString(ListSerializer(Household.serializer()), v)).apply()

    /** Whether this server can read recipes from photos (from /me). */
    var scanEnabled: Boolean
        get() = prefs.getBoolean("scan_enabled", true)
        set(v) = prefs.edit().putBoolean("scan_enabled", v).apply()

    var catalogFilter: String
        get() = prefs.getString("catalog_filter_$householdId", "all") ?: "all"
        set(v) = prefs.edit().putString("catalog_filter_$householdId", v).apply()

    /** Sent with changes so this phone can ignore the live events its own changes cause. */
    val clientId: String
        get() = prefs.getString("client_id", null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString("client_id", it).apply()
        }

    fun listPage(householdId: Long) = prefs.getInt("page_$householdId", 0)
    fun setListPage(householdId: Long, page: Int) = prefs.edit().putInt("page_$householdId", page).apply()

    /** Who the files on this phone belong to, so a different login doesn't send someone else's queued changes. */
    var dataOwner: String
        get() = prefs.getString("data_owner", "") ?: ""
        set(v) = prefs.edit().putString("data_owner", v).apply()

    fun signOut() {
        prefs.edit().remove("token").remove("households").apply()
    }
}

/** The last snapshot and the queued changes for each household, kept in the app's private files. */
class LocalStore(private val dir: File) {

    private fun file(householdId: Long, name: String) = AtomicFile(File(dir, "h$householdId-$name.json"))

    private fun read(f: AtomicFile): String? = runCatching { String(f.readFully(), Charsets.UTF_8) }.getOrNull()

    private fun write(f: AtomicFile, text: String) {
        val out = f.startWrite()
        try {
            out.write(text.toByteArray(Charsets.UTF_8))
            f.finishWrite(out)
        } catch (e: Exception) {
            f.failWrite(out)
            throw e
        }
    }

    fun loadState(householdId: Long): HouseholdState? =
        read(file(householdId, "state"))?.let { runCatching { AppJson.decodeFromString(HouseholdState.serializer(), it) }.getOrNull() }

    fun saveState(householdId: Long, state: HouseholdState) =
        write(file(householdId, "state"), AppJson.encodeToString(HouseholdState.serializer(), state))

    fun loadOutbox(householdId: Long): Outbox =
        read(file(householdId, "outbox"))?.let { runCatching { AppJson.decodeFromString(Outbox.serializer(), it) }.getOrNull() } ?: Outbox()

    fun saveOutbox(householdId: Long, outbox: Outbox) =
        write(file(householdId, "outbox"), AppJson.encodeToString(Outbox.serializer(), outbox))

    fun pendingCount(householdId: Long) = loadOutbox(householdId).ops.size

    fun clearAll() {
        dir.listFiles()?.filter { it.name.startsWith("h") && it.name.endsWith(".json") }?.forEach { it.delete() }
    }
}
