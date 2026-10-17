package app.pantri.data

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonEncoder
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

val AppJson = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
    explicitNulls = true
    classDiscriminator = "type"
    coerceInputValues = true
}

// ---------- what the server sends (see app/routes/api.py) ----------

@Serializable
data class Household(val id: Long, val name: String, val role: String = "member")

@Serializable
data class UserInfo(val id: Long, val username: String)

@Serializable
data class InviteDto(val id: Long, val household: String, @SerialName("invited_by") val invitedBy: String? = null)

@Serializable
data class Features(val scan: Boolean = false)

/** Who's logged in, their households and invites, and what this server can do. */
@Serializable
data class Me(
    val user: UserInfo,
    @SerialName("must_change_password") val mustChangePassword: Boolean = false,
    val households: List<Household> = emptyList(),
    val invites: List<InviteDto> = emptyList(),
    val features: Features = Features(),
    @SerialName("household_id") val householdId: Long? = null,
)

@Serializable
data class LoginResult(
    val token: String,
    val user: UserInfo,
    @SerialName("must_change_password") val mustChangePassword: Boolean = false,
    val households: List<Household> = emptyList(),
    val invites: List<InviteDto> = emptyList(),
    val features: Features = Features(),
) {
    fun me() = Me(user, mustChangePassword, households, invites, features)
}

// ---------- household settings (the website's settings page) ----------

@Serializable
data class MemberDto(
    val id: Long,
    @SerialName("user_id") val userId: Long,
    val username: String,
    val role: String,
    @SerialName("is_me") val isMe: Boolean = false,
)

@Serializable
data class PendingInviteDto(val id: Long, val username: String)

@Serializable
data class HouseholdSettings(
    val household: Household,
    val role: String,
    val members: List<MemberDto> = emptyList(),
    val invites: List<PendingInviteDto> = emptyList(),
    val notice: String? = null,
)

// ---------- recipe editing ----------

@Serializable
data class DraftIngredient(
    val name: String,
    val amount: String = "",
    val unit: String = "",
    val ranks: List<Long> = emptyList(),
    val fresh: String? = null,
)

@Serializable
data class DraftFresh(val directions: Boolean = false, val link: Boolean = false)

/** A recipe for the editor: an existing one, or what an import read. Nothing is saved until Save. */
@Serializable
data class RecipeDraft(
    @SerialName("recipe_id") val recipeId: Long? = null,
    val name: String = "",
    val ingredients: List<DraftIngredient> = emptyList(),
    val directions: String = "",
    @SerialName("source_url") val sourceUrl: String = "",
    val notice: String? = null,
    val fresh: DraftFresh = DraftFresh(),
    @SerialName("nothing_new") val nothingNew: Boolean = false,
)

@Serializable
data class SaveIngredient(
    val name: String,
    val amount: String,
    val unit: String,
    val ranks: List<Long>,
    @SerialName("ranks_changed") val ranksChanged: Boolean,
)

@Serializable
data class SaveRecipe(
    val name: String,
    val ingredients: List<SaveIngredient>,
    val directions: String,
    @SerialName("source_url") val sourceUrl: String,
)

/** Answers that carry the fresh household (stores, catalog, recipes changed). */
@Serializable
data class StateResult(
    val state: HouseholdState,
    @SerialName("recipe_id") val recipeId: Long? = null,
    val id: Long? = null,
)

// ---------- a shopping list read from photos or pasted text ----------

/** One thing the list reader found, matched to the catalog, with a store suggested. */
@Serializable
data class ScannedItem(
    val name: String,
    val qty: String = "",
    /** How it was written, when that doesn't show the name ("OJ"). */
    @SerialName("read_as") val readAs: String = "",
    @SerialName("catalog_id") val catalogId: Long? = null,
    val ranks: List<Long> = emptyList(),
    val store: Long? = null,
    /** "Costco: 2 lb" for each list it's already on, unchecked. */
    @SerialName("on_list") val onList: List<String> = emptyList(),
)

@Serializable
data class ScannedList(val notice: String = "", val items: List<ScannedItem> = emptyList())

@Serializable
data class AddScannedItem(val name: String, val qty: String, val store: Long?)

@Serializable
data class AddScanned(val items: List<AddScannedItem>, @SerialName("save_new") val saveNew: Boolean)

@Serializable
data class AddScannedResult(val added: Int, @SerialName("store_id") val storeId: Long? = null, val state: HouseholdState)

@Serializable
data class CopyResult(@SerialName("household_id") val householdId: Long, @SerialName("recipe_id") val recipeId: Long)

@Serializable
data class StoreDto(val id: Long, val name: String)

@Serializable
data class ItemDto(
    val id: Long,
    @SerialName("store_id") val storeId: Long? = null,
    val name: String,
    @SerialName("catalog_id") val catalogId: Long? = null,
    val quantities: List<JsonArray> = emptyList(),
    val qty: String = "",
    @SerialName("qty_text") val qtyText: String = "",
    val note: String = "",
    val tags: List<String> = emptyList(),
    val checked: Boolean = false,
    @SerialName("checked_at") val checkedAt: String? = null,
    val position: Int = 0,
)

@Serializable
data class CatalogDto(val id: Long, val name: String, val ranks: List<Long> = emptyList())

@Serializable
data class IngredientDto(
    @SerialName("catalog_id") val catalogId: Long? = null,
    val name: String,
    val amount: Double? = null,
    val unit: String = "",
    val qty: String = "",
)

@Serializable
data class RecipeDto(
    val id: Long,
    val name: String,
    val directions: String = "",
    @SerialName("source_url") val sourceUrl: String = "",
    val ingredients: List<IngredientDto> = emptyList(),
)

@Serializable
data class HouseholdState(
    val household: Household,
    @SerialName("other_label") val otherLabel: String = "Other",
    val stores: List<StoreDto> = emptyList(),
    val items: List<ItemDto> = emptyList(),
    val catalog: List<CatalogDto> = emptyList(),
    val recipes: List<RecipeDto> = emptyList(),
    val meals: List<MealDto> = emptyList(),
)

/** One thing on the meal calendar: a recipe (with its name when added), or a meal typed in without one. */
@Serializable
data class MealDto(
    val id: Long,
    val day: String,
    val slot: String,
    @SerialName("recipe_id") val recipeId: Long? = null,
    val title: String = "",
    val position: Int = 0,
)

@Serializable
data class ServerEvent(val kind: String = "", val origin: String? = null)

// ---------- items: the server's id, or ours for something added offline ----------

@Serializable(with = ItemKeySerializer::class)
sealed interface ItemKey {
    data class Server(val id: Long) : ItemKey
    data class Local(val ref: String) : ItemKey
}

/** The server takes an int (its id) or a string (our ref), so the JSON type carries the meaning. */
object ItemKeySerializer : KSerializer<ItemKey> {
    override val descriptor = PrimitiveSerialDescriptor("ItemKey", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: ItemKey) {
        val element = when (value) {
            is ItemKey.Server -> JsonPrimitive(value.id)
            is ItemKey.Local -> JsonPrimitive(value.ref)
        }
        (encoder as JsonEncoder).encodeJsonElement(element)
    }

    override fun deserialize(decoder: Decoder): ItemKey {
        val p = (decoder as JsonDecoder).decodeJsonElement().jsonPrimitive
        return if (p.isString) ItemKey.Local(p.content) else ItemKey.Server(p.long)
    }
}

// ---------- changes made on the phone, queued until the server has them ----------

@Serializable
sealed class Op {
    abstract val opId: String
}

/** store: a store id, or null for the "Other" list. Either qty (typed) or parts (exact, from a recipe). */
@Serializable
@SerialName("add")
data class AddOp(
    @SerialName("op_id") override val opId: String,
    val ref: String,
    val name: String,
    val qty: String? = null,
    val parts: List<JsonArray>? = null,
    val note: String = "",
    val store: Long? = null,
    val tags: List<String> = emptyList(),
) : Op()

@Serializable
@SerialName("check")
data class CheckOp(
    @SerialName("op_id") override val opId: String,
    val item: ItemKey,
    val checked: Boolean,
    val at: String = "",
) : Op()

@Serializable
@SerialName("update")
data class UpdateOp(
    @SerialName("op_id") override val opId: String,
    val item: ItemKey,
    val name: String,
    val qty: String,
    val note: String,
    val store: Long?,
) : Op()

@Serializable
@SerialName("delete")
data class DeleteOp(@SerialName("op_id") override val opId: String, val item: ItemKey) : Op()

@Serializable
@SerialName("reorder")
data class ReorderOp(
    @SerialName("op_id") override val opId: String,
    val store: Long?,
    val items: List<ItemKey>,
) : Op()

@Serializable
data class OpsRequest(val ops: List<Op>)

@Serializable
data class OpResult(
    @SerialName("op_id") val opId: String? = null,
    val status: String = "",
    @SerialName("item_id") val itemId: Long? = null,
    val message: String? = null,
)

@Serializable
data class OpsResponse(val results: List<OpResult> = emptyList(), val state: HouseholdState)

/** What's kept on disk between launches: queued changes, and the server ids learned for our refs. */
@Serializable
data class Outbox(val ops: List<Op> = emptyList(), val refs: Map<String, Long> = emptyMap())

// ---------- quantities: [[amount, unit], ...] ----------

data class Part(val amount: Double, val unit: String)

fun List<JsonArray>.toParts(): List<Part> = mapNotNull { arr ->
    val amount = arr.getOrNull(0)?.jsonPrimitive?.doubleOrNull ?: return@mapNotNull null
    val unit = arr.getOrNull(1)?.jsonPrimitive?.content ?: ""
    Part(amount, unit)
}

fun List<Part>.toJson(): List<JsonArray> = map { JsonArray(listOf(JsonPrimitive(it.amount), JsonPrimitive(it.unit))) }
