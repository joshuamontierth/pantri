package app.shoppinglist.ui

import app.shoppinglist.data.Household
import app.shoppinglist.data.HouseholdState
import app.shoppinglist.data.LocalApply
import app.shoppinglist.data.MealDto
import app.shoppinglist.data.RecipeDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class MealsTest {
    @Test
    fun weeksStartOnSunday() {
        assertEquals(LocalDate.of(2026, 10, 11), weekStart(LocalDate.of(2026, 10, 17))) // Saturday
        assertEquals(LocalDate.of(2026, 10, 18), weekStart(LocalDate.of(2026, 10, 18))) // Sunday
        assertEquals(LocalDate.of(2026, 10, 11), weekStart(LocalDate.of(2026, 10, 12))) // Monday
    }

    @Test
    fun mealNamesFollowTheirRecipe() {
        val state = HouseholdState(
            household = Household(1, "Home"),
            recipes = listOf(RecipeDto(id = 5, name = "Tacos al pastor")),
            meals = listOf(
                MealDto(1, "2026-10-15", "dinner", recipeId = 5, title = "Tacos"),
                MealDto(2, "2026-10-15", "dinner", recipeId = 9, title = "Guacamole"), // recipe deleted since
                MealDto(3, "2026-10-15", "dinner", title = "Chips"),
            ),
        )
        val view = LocalApply.view(state, emptyList(), emptyMap())
        assertEquals(listOf("Tacos al pastor", "Guacamole", "Chips"), view.meals.map(view::mealName))
        assertTrue(view.hasRecipe(view.meals[0]))
        assertFalse(view.hasRecipe(view.meals[1]))
        assertFalse(view.hasRecipe(view.meals[2]))
    }
}
