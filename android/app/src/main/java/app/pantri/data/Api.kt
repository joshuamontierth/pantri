package app.pantri.data

import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import java.io.IOException
import java.util.concurrent.TimeUnit

/** The server answered, but with an error (wrong password, logged out, a check failed...). */
class ApiException(val code: Int, message: String, val errors: List<String> = emptyList()) : Exception(message)

/** Talks to the server's /api/v1 (app/routes/api.py). Calls block; run them off the main thread. */
class Api(private val settings: Settings) {
    private val json = "application/json".toMediaType()

    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    // Reading a recipe from photos or a page asks the model, which can take a while.
    private val slowHttp = http.newBuilder().readTimeout(5, TimeUnit.MINUTES).writeTimeout(2, TimeUnit.MINUTES).build()

    // The live stream sends a ping every 20 s, so a minute of silence means the connection is dead.
    private val streamHttp = http.newBuilder().readTimeout(60, TimeUnit.SECONDS).build()

    private fun url(path: String, base: String = settings.serverUrl) = base.trimEnd('/') + "/api/v1" + path

    private fun request(path: String, base: String = settings.serverUrl): Request.Builder {
        val b = Request.Builder().url(url(path, base)).header("X-Client-Id", settings.clientId)
        settings.token?.let { b.header("Authorization", "Bearer $it") }
        return b
    }

    private fun <T> call(req: Request, client: OkHttpClient = http, read: (Response) -> T): T {
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful && resp.code != 304) throw error(resp)
            return read(resp)
        }
    }

    private fun error(resp: Response): ApiException {
        val body = runCatching { resp.body?.string().orEmpty() }.getOrDefault("")
        val obj = runCatching { AppJson.parseToJsonElement(body) as JsonObject }.getOrNull()
        val detail = runCatching { obj?.get("detail")?.jsonPrimitive?.content }.getOrNull()
        val errors = runCatching { obj?.get("errors")?.jsonArray?.map { it.jsonPrimitive.content } }.getOrNull().orEmpty()
        val message = detail ?: when (resp.code) {
            401 -> "Log in again."
            404 -> "Not found on the server."
            else -> "The server returned an error (${resp.code})."
        }
        return ApiException(resp.code, message, errors)
    }

    private fun <T> send(method: String, path: String, body: JsonElement?, out: KSerializer<T>, client: OkHttpClient = http): T {
        val b = request(path)
        val rb = (body ?: JsonObject(emptyMap())).let { AppJson.encodeToString(JsonElement.serializer(), it).toRequestBody(json) }
        when (method) {
            "GET" -> b.get()
            "POST" -> b.post(rb)
            "PUT" -> b.put(rb)
            "DELETE" -> b.delete()
        }
        return call(b.build(), client) { AppJson.decodeFromString(out, it.body!!.string()) }
    }

    private fun obj(vararg pairs: Pair<String, Any?>) = JsonObject(pairs.associate { (k, v) ->
        k to when (v) {
            null -> JsonNull
            is String -> JsonPrimitive(v)
            is Number -> JsonPrimitive(v)
            is Boolean -> JsonPrimitive(v)
            is List<*> -> JsonArray(v.map { JsonPrimitive(it as Long) })
            is JsonElement -> v
            else -> JsonPrimitive(v.toString())
        }
    })

    // ---------- account ----------

    @Throws(IOException::class, ApiException::class)
    fun login(baseUrl: String, username: String, password: String): LoginResult {
        val req = Request.Builder().url(url("/login", baseUrl))
            .post(AppJson.encodeToString(JsonObject.serializer(), obj("username" to username, "password" to password)).toRequestBody(json)).build()
        return call(req) { AppJson.decodeFromString(LoginResult.serializer(), it.body!!.string()) }
    }

    fun signup(baseUrl: String, username: String, password: String, confirm: String): LoginResult {
        val body = obj("username" to username, "password" to password, "confirm" to confirm)
        val req = Request.Builder().url(url("/signup", baseUrl))
            .post(AppJson.encodeToString(JsonObject.serializer(), body).toRequestBody(json)).build()
        return call(req) { AppJson.decodeFromString(LoginResult.serializer(), it.body!!.string()) }
    }

    fun logout() {
        runCatching { call(request("/logout").post("{}".toRequestBody(json)).build()) {} }
    }

    fun me(): Me = send("GET", "/me", null, Me.serializer())

    fun changePassword(current: String, password: String, confirm: String): Me =
        send("POST", "/account/password", obj("current" to current, "password" to password, "confirm" to confirm), Me.serializer())

    // ---------- households ----------

    fun createHousehold(name: String): Me = send("POST", "/households", obj("name" to name), Me.serializer())
    fun acceptInvite(id: Long): Me = send("POST", "/invites/$id/accept", null, Me.serializer())
    fun declineInvite(id: Long): Me = send("POST", "/invites/$id/decline", null, Me.serializer())

    fun householdSettings(hid: Long): HouseholdSettings = send("GET", "/h/$hid/settings", null, HouseholdSettings.serializer())
    fun renameHousehold(hid: Long, name: String) = send("POST", "/h/$hid/rename", obj("name" to name), HouseholdSettings.serializer())
    fun invite(hid: Long, username: String) = send("POST", "/h/$hid/invites", obj("username" to username), HouseholdSettings.serializer())
    fun cancelInvite(hid: Long, id: Long) = send("DELETE", "/h/$hid/invites/$id", null, HouseholdSettings.serializer())
    fun setRole(hid: Long, memberId: Long, role: String) = send("POST", "/h/$hid/members/$memberId/role", obj("role" to role), HouseholdSettings.serializer())
    fun removeMember(hid: Long, memberId: Long) = send("DELETE", "/h/$hid/members/$memberId", null, HouseholdSettings.serializer())
    fun resetPassword(hid: Long, memberId: Long, temp: String) =
        send("POST", "/h/$hid/members/$memberId/reset-password", obj("temp_password" to temp), HouseholdSettings.serializer())
    fun leaveHousehold(hid: Long): Me = send("POST", "/h/$hid/leave", null, Me.serializer())
    fun deleteHousehold(hid: Long, confirmName: String): Me = send("POST", "/h/$hid/delete", obj("confirm_name" to confirmName), Me.serializer())

    // ---------- stores and catalog ----------

    fun addStore(hid: Long, name: String) = send("POST", "/h/$hid/stores", obj("name" to name), StateResult.serializer())
    fun renameStore(hid: Long, id: Long, name: String) = send("PUT", "/h/$hid/stores/$id", obj("name" to name), StateResult.serializer())
    fun reorderStores(hid: Long, ids: List<Long>) = send("POST", "/h/$hid/stores/reorder", obj("ids" to ids), StateResult.serializer())
    fun deleteStore(hid: Long, id: Long) = send("DELETE", "/h/$hid/stores/$id", null, StateResult.serializer())

    fun createCatalogItem(hid: Long, name: String, ranks: List<Long>) =
        send("POST", "/h/$hid/catalog", obj("name" to name, "ranks" to ranks), StateResult.serializer())
    fun updateCatalogItem(hid: Long, id: Long, name: String, ranks: List<Long>) =
        send("PUT", "/h/$hid/catalog/$id", obj("name" to name, "ranks" to ranks), StateResult.serializer())
    fun deleteCatalogItem(hid: Long, id: Long) = send("DELETE", "/h/$hid/catalog/$id", null, StateResult.serializer())

    // ---------- recipes ----------

    fun recipeDraft(hid: Long, id: Long) = send("GET", "/h/$hid/recipes/$id/draft", null, RecipeDraft.serializer())

    fun saveRecipe(hid: Long, id: Long?, recipe: SaveRecipe): StateResult {
        val body = AppJson.encodeToJsonElement(SaveRecipe.serializer(), recipe)
        return if (id == null) send("POST", "/h/$hid/recipes", body, StateResult.serializer())
        else send("PUT", "/h/$hid/recipes/$id", body, StateResult.serializer())
    }

    fun deleteRecipe(hid: Long, id: Long) = send("DELETE", "/h/$hid/recipes/$id", null, StateResult.serializer())

    fun copyRecipe(hid: Long, id: Long, target: Long) =
        send("POST", "/h/$hid/recipes/$id/copy", obj("target_household_id" to target), CopyResult.serializer())

    /** Read a recipe from a link. With recipeId, only that recipe's gaps are filled in. */
    fun importLink(hid: Long, link: String, recipeId: Long?) =
        send("POST", "/h/$hid/recipes/import", obj("url" to link, "recipe_id" to recipeId), RecipeDraft.serializer(), slowHttp)

    /** Read a recipe from photos (JPEG bytes, up to 4). */
    fun scanRecipe(hid: Long, photos: List<ByteArray>, recipeId: Long?): RecipeDraft {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
        recipeId?.let { body.addFormDataPart("recipe_id", it.toString()) }
        val jpeg = "image/jpeg".toMediaType()
        photos.forEachIndexed { i, bytes -> body.addFormDataPart("photos", "photo-${i + 1}.jpg", bytes.toRequestBody(jpeg)) }
        return call(request("/h/$hid/recipes/scan").post(body.build()).build(), slowHttp) {
            AppJson.decodeFromString(RecipeDraft.serializer(), it.body!!.string())
        }
    }

    // ---------- the meal calendar ----------

    /** Recipes and/or a meal without one on a lunch or dinner (day as 2026-10-14). */
    fun addMeals(hid: Long, day: String, slot: String, recipeIds: List<Long>, title: String) =
        send("POST", "/h/$hid/meals", obj("day" to day, "slot" to slot, "recipe_ids" to recipeIds, "title" to title), StateResult.serializer())

    fun deleteMeal(hid: Long, id: Long) = send("DELETE", "/h/$hid/meals/$id", null, StateResult.serializer())

    // ---------- a shopping list from photos or pasted text ----------

    /** Read a shopping list from photos (JPEG bytes, up to 4), or from typed text when there are none. */
    fun scanList(hid: Long, photos: List<ByteArray>, text: String?): ScannedList {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
        if (photos.isEmpty()) body.addFormDataPart("text", text.orEmpty())
        val jpeg = "image/jpeg".toMediaType()
        photos.forEachIndexed { i, bytes -> body.addFormDataPart("photos", "list-${i + 1}.jpg", bytes.toRequestBody(jpeg)) }
        return call(request("/h/$hid/lists/scan").post(body.build()).build(), slowHttp) {
            AppJson.decodeFromString(ScannedList.serializer(), it.body!!.string())
        }
    }

    fun addScanned(hid: Long, add: AddScanned) =
        send("POST", "/h/$hid/lists/add", AppJson.encodeToJsonElement(AddScanned.serializer(), add), AddScannedResult.serializer())

    // ---------- lists ----------

    /** The household's state, or null if it hasn't changed since [etag]. */
    fun state(householdId: Long, etag: String?): Pair<HouseholdState?, String?> {
        val b = request("/h/$householdId/state").get()
        etag?.let { b.header("If-None-Match", it) }
        return call(b.build()) { resp ->
            if (resp.code == 304) null to etag
            else AppJson.decodeFromString(HouseholdState.serializer(), resp.body!!.string()) to resp.header("ETag")
        }
    }

    fun ops(householdId: Long, ops: List<Op>): OpsResponse {
        val body = AppJson.encodeToString(OpsRequest.serializer(), OpsRequest(ops))
        return call(request("/h/$householdId/ops").post(body.toRequestBody(json)).build()) {
            AppJson.decodeFromString(OpsResponse.serializer(), it.body!!.string())
        }
    }

    fun events(householdId: Long, listener: EventSourceListener): EventSource =
        EventSources.createFactory(streamHttp)
            .newEventSource(request("/h/$householdId/events").header("Accept", "text/event-stream").build(), listener)
}
