package app.shoppinglist.ui

import android.content.ClipboardManager
import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import app.shoppinglist.data.LocalView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/** New or edit a recipe (the website's recipe form). Saving needs a connection, as on the website. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EditorScreen(vm: AppViewModel, view: LocalView, ed: EditorState, snackbar: SnackbarHostState) {
    var importing by remember { mutableStateOf(false) }
    val title = if (ed.recipeId != null) "Edit recipe" else "New recipe"
    val catalogByLower = view.catalog.associateBy { it.name.lowercase() }

    Scaffold(
        containerColor = colors.paper,
        topBar = { BackBar(if (ed.recipeId != null) ed.name.ifBlank { "Recipe" } else "Recipes", onBack = { vm.closeEditor() }) },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            Row(Modifier.background(colors.paper).navigationBarsPadding().imePadding().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryButton("Save recipe", onClick = { vm.saveEditor() }, busy = ed.saving, modifier = Modifier.weight(1f))
                OutlineButton("Cancel", onClick = { vm.closeEditor() }, modifier = Modifier.heightIn(min = 54.dp))
            }
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                PageTitle(title, Modifier.weight(1f))
                if (ed.recipeId == null && ed.notice == null) OutlineButton("Import", small = true, icon = AppIcons.Import, onClick = { importing = true })
            }
            ed.notice?.let { Alert(it, kind = "info") }
            for (e in ed.errors) Alert(e)
            Field(ed.name, { ed.name = it }, label = "Name", keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences))

            Column {
                Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), verticalAlignment = Alignment.Bottom) {
                    SectionLabel("Ingredients", Modifier.weight(1f))
                    Text("Amounts like 2, 1/2, 1 1/2 or 0.75", color = colors.ink2, fontSize = 13.sp)
                }
                HorizontalDivider(color = colors.ink, thickness = 2.dp)
                for (row in ed.rows) {
                    androidx.compose.runtime.key(row.key) { IngredientRow(view, ed, row, catalogByLower.keys) }
                }
                Spacer(Modifier.size(12.dp))
                OutlineButton("Add ingredient", small = true, icon = AppIcons.Plus, onClick = { ed.rows.add(EditorRow("", "", "", emptyList())) })
            }

            Column {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 6.dp)) {
                    SectionLabel("Directions")
                    if (ed.freshDirections) { Spacer(Modifier.width(8.dp)); Badge("Added") }
                }
                OutlinedTextField(
                    ed.directions, { ed.directions = it }, Modifier.fillMaxWidth().heightIn(min = 140.dp),
                    placeholder = { Text("Number the steps, or leave a blank line between them.", color = colors.ink3) },
                    textStyle = TextStyle(fontSize = 16.sp, lineHeight = 24.sp, color = colors.ink, fontFamily = Grotesk),
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                    shape = RadiusShape,
                    colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = colors.ink, unfocusedBorderColor = colors.rule2,
                        focusedContainerColor = colors.field, unfocusedContainerColor = colors.field, cursorColor = colors.accent),
                )
            }
            Column {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 6.dp)) {
                    SectionLabel("Recipe link")
                    if (ed.freshLink) { Spacer(Modifier.width(8.dp)); Badge("Added") }
                }
                Field(ed.sourceUrl, { ed.sourceUrl = it }, placeholder = "https://", keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false))
            }
        }
    }
    if (importing) ImportSheet(vm, recipeId = null, onDismiss = { importing = false })
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun IngredientRow(view: LocalView, ed: EditorState, row: EditorRow, known: Set<String>) {
    val name = row.name.trim()
    val isKnown = name.lowercase() in known
    val typed = name.lowercase()
    val suggestions = if (typed.isEmpty() || isKnown) emptyList()
    else view.catalog.filter { it.name.lowercase().contains(typed) }.sortedBy { !it.name.lowercase().startsWith(typed) }.take(3)

    fun setName(value: String) {
        row.name = value
        val c = view.catalogItem(value)
        if (c != null) {
            row.ranks = c.ranks.filter { r -> view.stores.any { it.id == r } }
            row.ranksChanged = false
            row.showRanks = false
        } else if (value.isNotBlank()) {
            row.showRanks = true
        }
    }

    Column(Modifier.fillMaxWidth().padding(vertical = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            SmallField(row.name, ::setName, "Ingredient", Modifier.weight(1f), bold = true, capitalize = true)
            Spacer(Modifier.width(6.dp))
            SmallField(row.amount, { row.amount = it }, "Amt", Modifier.width(70.dp))
            Spacer(Modifier.width(6.dp))
            SmallField(row.unit, { row.unit = it }, "unit", Modifier.width(76.dp))
            Box(Modifier.size(36.dp, 44.dp).clickable {
                if (ed.rows.size > 1) ed.rows.remove(row) else { row.name = ""; row.amount = ""; row.unit = "" }
            }, contentAlignment = Alignment.Center) { Icon(AppIcons.Close, "Remove ingredient", Modifier.size(18.dp), tint = colors.ink3) }
        }
        if (suggestions.isNotEmpty()) {
            FlowRow(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (s in suggestions) {
                    Text(s.name, Modifier.clip(RadiusShape).border(1.dp, colors.rule2, RadiusShape).clickable { setName(s.name) }.padding(horizontal = 10.dp, vertical = 6.dp),
                        color = colors.ink, fontSize = 14.sp)
                }
            }
        }
        if (name.isNotEmpty()) {
            Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                row.fresh?.let { Badge(it); Spacer(Modifier.width(8.dp)) }
                if (isKnown) {
                    val summary = row.ranks.joinToString(" › ") { view.storeName(it) }.ifEmpty { view.otherLabel }
                    Text(summary + if (row.ranksChanged) " (changed)" else "", color = colors.ink2, fontSize = 14.sp, modifier = Modifier.weight(1f, fill = false))
                    Text(if (row.showRanks) "Done" else "Change", Modifier.clickable { row.showRanks = !row.showRanks }.padding(start = 10.dp, top = 4.dp, bottom = 4.dp),
                        color = colors.accent, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                } else {
                    Text("New item. Tap its stores in order of preference.", color = colors.ink2, fontSize = 14.sp)
                }
            }
            if (row.showRanks || !isKnown) {
                Box(Modifier.padding(top = 8.dp)) {
                    RankPicker(view.stores, row.ranks) {
                        row.ranks = it
                        row.ranksChanged = true
                    }
                }
            }
        }
        HorizontalDivider(Modifier.padding(top = 12.dp), color = colors.rule)
    }
}

@Composable
internal fun SmallField(value: String, onChange: (String) -> Unit, placeholder: String, modifier: Modifier, bold: Boolean = false, capitalize: Boolean = false) {
    OutlinedTextField(
        value, onChange, modifier.heightIn(min = 48.dp), singleLine = true,
        placeholder = { Text(placeholder, color = colors.ink3, fontSize = 15.sp) },
        textStyle = TextStyle(fontSize = 15.sp, color = colors.ink, fontFamily = Grotesk, fontWeight = if (bold) FontWeight.SemiBold else FontWeight.Normal),
        keyboardOptions = KeyboardOptions(capitalization = if (capitalize) KeyboardCapitalization.Sentences else KeyboardCapitalization.None, autoCorrectEnabled = capitalize),
        shape = RadiusShape,
        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = colors.ink, unfocusedBorderColor = colors.rule2,
            focusedContainerColor = colors.field, unfocusedContainerColor = colors.field, cursorColor = colors.accent),
    )
}

/**
 * Import a recipe (recipeId = null) or add details to one: take photos, choose photos, or paste a link.
 * The same choices as the website's Import / Add details sheet.
 */
@Composable
fun ImportSheet(vm: AppViewModel, recipeId: Long?, onDismiss: () -> Unit) = PhotosOrTextSheet(vm, recipeId, forList = false, onDismiss)

/** Scan a shopping list: take photos, choose photos, or paste the list (the website's sheet on the lists page). */
@Composable
fun ScanListSheet(vm: AppViewModel, onDismiss: () -> Unit) = PhotosOrTextSheet(vm, null, forList = true, onDismiss)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PhotosOrTextSheet(vm: AppViewModel, recipeId: Long?, forList: Boolean, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val photos = remember { mutableStateListOf<Uri>() }
    // Without the photo reader a recipe can still come from a link (a list can't be read at all).
    var textMode by remember { mutableStateOf(!vm.scanEnabled) }
    var text by remember { mutableStateOf("") }
    var pendingShot by remember { mutableStateOf<Uri?>(null) }

    val takePicture = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        pendingShot?.let { if (ok && photos.size < 4) photos.add(it) }
        pendingShot = null
    }
    val choose = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(4)) { uris ->
        photos.addAll(uris.take(4 - photos.size))
    }
    fun shoot() {
        val dir = File(context.cacheDir, "photos").apply { mkdirs() }
        val uri = FileProvider.getUriForFile(context, context.packageName + ".files", File(dir, "shot-${System.currentTimeMillis()}.jpg"))
        pendingShot = uri
        takePicture.launch(uri)
    }
    fun read() {
        onDismiss()
        when {
            forList -> if (textMode) vm.scanList(emptyList(), text.trim()) else vm.scanList(photos.toList(), null)
            textMode -> vm.importRecipe(emptyList(), text.trim(), recipeId)
            else -> vm.importRecipe(photos.toList(), null, recipeId)
        }
    }
    fun paste() {
        val clip = (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).primaryClip
        clip?.getItemAt(0)?.coerceToText(context)?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let { text = it }
    }
    val readLabel = if (forList) "Read list" else "Read recipe"

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = colors.sheet) {
        Column(Modifier.fillMaxWidth().imePadding().padding(horizontal = 16.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(
                when {
                    forList -> "Scan a shopping list"
                    recipeId == null -> "Import a recipe"
                    else -> "Add details"
                },
                fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, color = colors.ink,
            )
            if (recipeId != null) {
                Text("Fills in directions, missing ingredients and missing amounts. Nothing this recipe already has is changed.", color = colors.ink2, fontSize = 14.sp)
            }
            when {
                textMode && forList -> {
                    SectionLabel("Your list")
                    Field(text, { text = it }, Modifier.fillMaxWidth(), placeholder = "Milk\nEggs x2\n2 lb ground beef",
                        singleLine = false, minLines = 5, keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlineButton("Paste", onClick = ::paste)
                        Spacer(Modifier.width(8.dp))
                        PrimaryButton(readLabel, onClick = ::read, enabled = text.isNotBlank(), modifier = Modifier.weight(1f))
                    }
                }
                textMode -> {
                    SectionLabel("Recipe link")
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Field(text, { text = it }, Modifier.weight(1f), placeholder = "https://",
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false))
                        Spacer(Modifier.width(8.dp))
                        OutlineButton("Paste", onClick = ::paste)
                    }
                    PrimaryButton("Import", onClick = ::read, enabled = text.isNotBlank(), modifier = Modifier.fillMaxWidth())
                }
                photos.isNotEmpty() -> {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        for (uri in photos.toList()) {
                            Box(Modifier.size(72.dp).clip(RoundedCornerShape(10.dp)).clickable { photos.remove(uri) }) {
                                Thumbnail(uri)
                                Box(Modifier.align(Alignment.TopEnd).padding(4.dp).size(20.dp).clip(RoundedCornerShape(10.dp)).background(colors.ink.copy(alpha = 0.6f)), contentAlignment = Alignment.Center) {
                                    Icon(AppIcons.Close, "Remove photo", Modifier.size(12.dp), tint = colors.paper)
                                }
                            }
                        }
                    }
                    Text(
                        when {
                            photos.size >= 4 -> "4 photos is the most"
                            forList -> "Add another photo, like the rest of the list, or read it now."
                            else -> "Add another photo, like the back of the card, or read it now."
                        },
                        color = colors.ink2, fontSize = 14.sp,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (photos.size < 4) OutlineButton("Take another", small = true, icon = AppIcons.Camera, onClick = ::shoot)
                        if (photos.size < 4) OutlineButton("Choose", small = true, icon = AppIcons.Image, onClick = { choose.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) })
                    }
                    PrimaryButton(if (photos.size > 1) "Read ${photos.size} photos" else readLabel, onClick = ::read, modifier = Modifier.fillMaxWidth())
                }
                else -> {
                    Choice(AppIcons.Camera, "Take a photo", if (forList) "A handwritten or printed list" else "A recipe card or cookbook page", ::shoot)
                    Choice(AppIcons.Image, "Choose photos", "Up to 4, screenshots work too") { choose.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
                    if (forList) Choice(AppIcons.Paste, "Paste a list", "Typed in a note or a message") { textMode = true }
                    else Choice(AppIcons.Link, "Paste a link", "From a recipe website") { textMode = true }
                }
            }
            OutlineButton("Cancel", onClick = onDismiss, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun Choice(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, sub: String, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.field).border(1.dp, colors.rule2, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick).heightIn(min = 68.dp).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(44.dp).clip(RoundedCornerShape(12.dp)).background(colors.accentWash), contentAlignment = Alignment.Center) {
            Icon(icon, null, Modifier.size(22.dp), tint = colors.accent)
        }
        Spacer(Modifier.width(14.dp))
        Column {
            Text(title, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = colors.ink)
            Text(sub, fontSize = 14.sp, color = colors.ink2)
        }
    }
}

@Composable
private fun Thumbnail(uri: Uri) {
    val context = LocalContext.current
    val image by produceState<ImageBitmap?>(null, uri) {
        value = withContext(Dispatchers.IO) {
            runCatching {
                context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = 16 }) }?.asImageBitmap()
            }.getOrNull()
        }
    }
    image?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop) } ?: Box(Modifier.fillMaxSize().background(colors.rule))
}

/** Over everything while the model reads (the website's "Reading the recipe" / "Reading the list" card). */
@Composable
fun ReadingOverlay(title: String) {
    Box(Modifier.fillMaxSize().background(colors.ink.copy(alpha = 0.42f)).clickable(enabled = true, onClick = {}), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 320.dp).clip(RoundedCornerShape(18.dp)).background(colors.sheet).padding(horizontal = 24.dp, vertical = 30.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            CircularProgressIndicator(Modifier.size(40.dp), color = colors.accent, strokeWidth = 3.dp)
            Spacer(Modifier.size(6.dp))
            Text(title, fontSize = 20.sp, fontWeight = FontWeight.ExtraBold, color = colors.ink)
            Text("This usually takes a few seconds.", color = colors.ink2, fontSize = 15.sp)
        }
    }
}
