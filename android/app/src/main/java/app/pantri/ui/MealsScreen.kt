package app.pantri.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.pantri.data.Connection
import app.pantri.data.LocalView
import app.pantri.data.MealDto
import app.pantri.data.SyncStatus
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

private val SLOTS = listOf("lunch" to "Lunch", "dinner" to "Dinner")
private val MONTH_DAY = DateTimeFormatter.ofPattern("MMM d", Locale.US)

/** The first day (first: 0 = Monday ... 6 = Sunday; Saturday unless set) of the week with this day in it (actions.week_start). */
fun weekStart(day: LocalDate, first: Int = 5): LocalDate = day.minusDays((((day.dayOfWeek.value - 1 - first) % 7 + 7) % 7).toLong())

private fun dayName(day: LocalDate) = day.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.US)

/** The meal calendar (the website's Meals page): a week of lunches and dinners. */
@Composable
fun MealsScreen(vm: AppViewModel, view: LocalView, status: SyncStatus, snackbar: SnackbarHostState) {
    val today = LocalDate.now()
    val first = view.weekStart
    val thisWeek = weekStart(today, first)
    val start = vm.mealsWeek?.let { weekStart(it, first) } ?: thisWeek
    val days = (0L..6L).map { start.plusDays(it) }
    val byDay = view.meals.groupBy { it.day to it.slot }
    // The week's recipe meals in calendar order, for choosing which to shop for.
    val weekMeals = days.flatMap { d -> SLOTS.flatMap { (slot, _) -> byDay[d.toString() to slot].orEmpty().sortedWith(compareBy<MealDto> { it.position }.thenBy { it.id }) } }
        .filter(view::hasRecipe)
    var adding by remember { mutableStateOf<Pair<LocalDate, String>?>(null) }
    var choosing by remember(start) { mutableStateOf(false) }
    val chosen = remember(start) { mutableStateListOf<Long>() }
    fun toggle(id: Long) {
        if (id in chosen) chosen.remove(id) else chosen.add(id)
    }
    val weeksAway = java.time.temporal.ChronoUnit.WEEKS.between(thisWeek, start)
    val weekLabel = when (weeksAway) {
        0L -> "This week"
        1L -> "Next week"
        -1L -> "Last week"
        else -> start.year.toString()
    }
    fun setWeek(d: LocalDate) {
        vm.mealsWeek = if (d == thisWeek) null else d
    }

    Scaffold(
        containerColor = colors.paper,
        topBar = { TopNav(Screen.Meals, status, onTab = vm::tab, onSettings = { vm.go(Screen.Settings) }) },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (choosing) {
                Row(Modifier.background(colors.paper).navigationBarsPadding().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val n = chosen.count { id -> weekMeals.any { it.id == id } }
                    PrimaryButton(
                        if (n == 0) "Check the meals to shop for" else "Shop for $n meal${if (n == 1) "" else "s"}",
                        sub = "Next, check the ingredients you need", enabled = n > 0, modifier = Modifier.weight(1f),
                        onClick = {
                            // Once per meal: a recipe cooked twice needs twice the ingredients.
                            val counts = weekMeals.filter { it.id in chosen }.mapNotNull { it.recipeId }.groupingBy { it }.eachCount()
                            choosing = false
                            vm.go(Screen.Plan(counts.keys.toList(), counts))
                        },
                    )
                    OutlineButton("Cancel", onClick = { choosing = false }, modifier = Modifier.heightIn(min = 54.dp))
                }
            }
        },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp)) {
            item {
                PageTitle("Meals", Modifier.padding(top = 8.dp, bottom = 10.dp))
                Row(Modifier.fillMaxWidth().padding(bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    SquareButton(AppIcons.Back, "Previous week") { setWeek(start.minusWeeks(1)) }
                    Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                        val end = days.last()
                        Text(
                            start.format(MONTH_DAY) + " – " + if (end.month == start.month) end.dayOfMonth.toString() else end.format(MONTH_DAY),
                            fontSize = 18.sp, fontWeight = FontWeight.ExtraBold, color = colors.ink,
                        )
                        Text(weekLabel, fontSize = 13.sp, color = colors.ink2)
                    }
                    SquareButton(AppIcons.ChevronRight, "Next week") { setWeek(start.plusWeeks(1)) }
                    if (weeksAway != 0L) {
                        Spacer(Modifier.width(8.dp))
                        OutlineButton("Today", small = true, onClick = { setWeek(thisWeek) })
                    }
                }
                if (choosing) {
                    Column(
                        Modifier.fillMaxWidth().padding(bottom = 12.dp).clip(RadiusShape).background(colors.accentWash).padding(horizontal = 14.dp, vertical = 12.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text("Check the meals to buy ingredients for. Leave out leftovers and repeats; a recipe checked for two meals counts twice.", fontSize = 15.sp, color = colors.ink)
                        val all = weekMeals.all { it.id in chosen }
                        Text(
                            if (all) "Select none" else "Select all",
                            Modifier.clip(RoundedCornerShape(8.dp)).clickable { chosen.clear(); if (!all) chosen.addAll(weekMeals.map { it.id }) }.padding(vertical = 4.dp),
                            color = colors.accent, fontWeight = FontWeight.SemiBold, fontSize = 15.sp,
                        )
                    }
                }
            }
            for (day in days) {
                item(key = day.toString()) {
                    DaySection(vm, view, day, today, byDay, if (choosing) chosen else null, ::toggle, onAdd = { slot ->
                        if (status.connection == Connection.Offline) vm.message("Changing meals needs a connection.")
                        else adding = day to slot
                    })
                }
            }
            if (weekMeals.isNotEmpty() && !choosing) {
                item {
                    OutlineButton(
                        "Choose meals to shop for", icon = AppIcons.Import,
                        onClick = {
                            // Meals still ahead start checked; past days don't.
                            chosen.clear()
                            chosen.addAll(weekMeals.filter { it.day >= today.toString() }.map { it.id })
                            choosing = true
                        },
                        modifier = Modifier.fillMaxWidth().padding(top = 24.dp),
                    )
                }
            }
        }
    }
    adding?.let { (day, slot) -> AddMealSheet(vm, view, day, slot, onDismiss = { adding = null }) }
}

@Composable
private fun SquareButton(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, onClick: () -> Unit) {
    Box(
        Modifier.size(44.dp).clip(RadiusShape).border(1.dp, colors.rule2, RadiusShape).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, label, Modifier.size(20.dp), tint = colors.ink)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DaySection(
    vm: AppViewModel, view: LocalView, day: LocalDate, today: LocalDate, byDay: Map<Pair<String, String>, List<MealDto>>,
    chosen: List<Long>?, onToggle: (Long) -> Unit, onAdd: (String) -> Unit,
) {
    val isToday = day == today
    Column(Modifier.fillMaxWidth()) {
        HorizontalDivider(color = if (isToday) colors.accent else colors.rule, thickness = if (isToday) 2.dp else 1.dp)
        Row(Modifier.padding(top = 14.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(dayName(day), fontSize = 18.sp, fontWeight = FontWeight.ExtraBold, color = if (day < today) colors.ink2 else colors.ink)
            Spacer(Modifier.width(8.dp))
            Text(day.format(MONTH_DAY), fontSize = 15.sp, color = colors.ink2)
            if (isToday) {
                Spacer(Modifier.width(8.dp))
                Badge("Today")
            }
        }
        for ((slot, label) in SLOTS) {
            val meals = byDay[day.toString() to slot].orEmpty().sortedWith(compareBy<MealDto> { it.position }.thenBy { it.id })
            Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.Top) {
                Text(
                    label.uppercase(), Modifier.width(72.dp).padding(top = 12.dp),
                    fontSize = 12.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.7.sp, color = colors.ink2,
                )
                FlowRow(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (m in meals) MealChip(view, m, chosen, onToggle, onOpen = { m.recipeId?.let { vm.go(Screen.Recipe(it)) } }, onRemove = { vm.deleteMeal(m.id) })
                    if (chosen == null) Row(
                        Modifier.heightIn(min = 40.dp).clip(RoundedCornerShape(10.dp))
                            .border(1.dp, colors.rule2, RoundedCornerShape(10.dp)).clickable { onAdd(slot) }.padding(horizontal = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(AppIcons.Plus, null, Modifier.size(16.dp), tint = colors.ink2)
                        Spacer(Modifier.width(4.dp))
                        Text("Add", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = colors.ink2)
                    }
                }
            }
        }
        Spacer(Modifier.size(8.dp))
    }
}

/** chosen: while choosing meals to shop for, the meals checked (a recipe's chip checks it); null otherwise. */
@Composable
private fun MealChip(view: LocalView, meal: MealDto, chosen: List<Long>?, onToggle: (Long) -> Unit, onOpen: () -> Unit, onRemove: () -> Unit) {
    val recipe = view.hasRecipe(meal)
    val shape = RoundedCornerShape(10.dp)
    if (chosen != null) {
        val on = meal.id in chosen
        Row(
            Modifier.heightIn(min = 40.dp).clip(shape)
                .background(if (on) colors.accentWash else colors.field)
                .border(1.dp, if (on) colors.accent else colors.rule2, shape)
                .then(if (recipe) Modifier.clickable { onToggle(meal.id) } else Modifier)
                .padding(start = 10.dp, end = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (recipe) {
                Box(
                    Modifier.size(20.dp).clip(RoundedCornerShape(6.dp)).background(if (on) colors.accent else colors.field)
                        .border(2.dp, if (on) colors.accent else colors.ink, RoundedCornerShape(6.dp)),
                    contentAlignment = Alignment.Center,
                ) {
                    if (on) Icon(AppIcons.Check, null, Modifier.size(14.dp), tint = colors.accentInk)
                }
                Spacer(Modifier.width(8.dp))
            }
            Text(
                view.mealName(meal), Modifier.padding(vertical = 8.dp),
                fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = if (recipe) colors.ink else colors.ink3,
                maxLines = 2, overflow = TextOverflow.Ellipsis,
            )
        }
        return
    }
    Row(
        Modifier.heightIn(min = 40.dp).clip(shape)
            .then(if (recipe) Modifier.background(colors.accentWash) else Modifier.background(colors.field).border(1.dp, colors.rule2, shape))
            .clickable(enabled = recipe, onClick = onOpen),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            view.mealName(meal), Modifier.padding(start = 12.dp, top = 8.dp, bottom = 8.dp),
            fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = if (recipe) colors.accent else colors.ink,
            maxLines = 2, overflow = TextOverflow.Ellipsis,
        )
        Box(Modifier.size(width = 36.dp, height = 40.dp).clickable(onClick = onRemove), contentAlignment = Alignment.Center) {
            Icon(AppIcons.Close, "Remove ${view.mealName(meal)}", Modifier.size(15.dp), tint = colors.ink3)
        }
    }
}

/** Add recipes and/or a meal without one (the website's sheet). Shopping for them comes later ("Choose meals to shop for"). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddMealSheet(vm: AppViewModel, view: LocalView, day: LocalDate, slot: String, onDismiss: () -> Unit) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var title by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var saving by remember { mutableStateOf(false) }
    val chosen = remember { mutableStateListOf<Long>() }
    val shown = view.recipes.filter { query.isBlank() || it.name.contains(query.trim(), ignoreCase = true) }
    val n = chosen.size
    val typed = title.isNotBlank()
    val label = "${dayName(day)} ${SLOTS.first { it.first == slot }.second.lowercase()}"

    fun save() {
        saving = true
        error = null
        scope.launch {
            val ids = view.recipes.map { it.id }.filter { it in chosen } // in the list's order, like the website
            val failed = vm.addMeals(day, slot, ids, title)
            saving = false
            if (failed != null) {
                error = failed
                return@launch
            }
            onDismiss()
        }
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = colors.sheet) {
        Column(Modifier.fillMaxWidth().imePadding().padding(horizontal = 16.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Add to $label", fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, color = colors.ink)
            error?.let { Alert(it) }
            if (view.recipes.isNotEmpty()) {
                Field(query, { query = it }, placeholder = "Search recipes", keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search))
                Column(Modifier.fillMaxWidth().heightIn(max = 280.dp).verticalScroll(rememberScrollState())) {
                    HorizontalDivider(color = colors.rule)
                    for (r in shown) {
                        val on = r.id in chosen
                        Row(
                            Modifier.fillMaxWidth().clickable { if (on) chosen.remove(r.id) else chosen.add(r.id) }.heightIn(min = 52.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            CheckBox(on, { if (on) chosen.remove(r.id) else chosen.add(r.id) })
                            Text(r.name, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                        }
                        HorizontalDivider(color = colors.rule)
                    }
                }
            }
            Field(
                title, { title = it }, label = if (view.recipes.isNotEmpty()) "Or a meal without a recipe" else "Meal",
                placeholder = "Leftovers, eating out…",
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences, imeAction = ImeAction.Done),
            )
            PrimaryButton(
                when {
                    n == 0 && !typed -> "Pick a recipe or type a meal"
                    n == 0 -> "Add ${title.trim()}"
                    else -> "Add $n recipe${if (n == 1) "" else "s"}" + if (typed) " and ${title.trim()}" else ""
                },
                enabled = (n > 0 || typed) && !saving, busy = saving,
                onClick = ::save, modifier = Modifier.fillMaxWidth(),
            )
            OutlineButton("Cancel", onClick = onDismiss, modifier = Modifier.fillMaxWidth())
        }
    }
}
