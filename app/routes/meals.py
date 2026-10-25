"""The meal calendar: a week of lunches and dinners. Each can have several recipes and meals typed in without one.

Plan the week first, then "Choose meals to shop for" picks which meals' recipes go to the ingredient picker
(plan.js), leaving out leftovers and repeats. Changes need a connection; the page opens as last seen offline.
"""

from collections import Counter
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, selectinload

from .. import actions
from ..db import get_db
from ..deps import form_data, household_member
from ..models import Meal, Recipe
from ..templating import render

router = APIRouter()

SLOT_LABELS = {"lunch": "Lunch", "dinner": "Dinner"}


def _week_of(text, first):
    try:
        day = actions.parse_day(text) if text else actions.today()
    except actions.ActionError:
        day = actions.today()
    return actions.week_start(day, first)


def _week_url(household_id, start, first):
    this_week = actions.week_start(actions.today(), first)
    return f"/h/{household_id}/meals" + ("" if start == this_week else f"?week={start.isoformat()}")


def _page(request, db, membership, start, error=None, status_code=200):
    hid = membership.household_id
    first = actions.first_weekday(membership.household)
    days = [start + timedelta(days=i) for i in range(7)]
    meals = (
        db.query(Meal).options(selectinload(Meal.recipe))
        .filter(Meal.household_id == hid, Meal.day >= days[0], Meal.day <= days[-1])
        .order_by(Meal.position, Meal.id).all()
    )
    grid = {(d, slot): [] for d in days for slot in actions.MEAL_SLOTS}
    for m in meals:
        grid.setdefault((m.day, m.slot), []).append(m)
    today = actions.today()
    this_week = actions.week_start(today, first)
    weeks_away = (start - this_week).days // 7
    week_label = {0: "This week", 1: "Next week", -1: "Last week"}.get(weeks_away, str(start.year))
    # Without JavaScript, "Choose meals to shop for" goes straight to the picker with the meals still ahead.
    ahead = Counter(m.recipe_id for m in meals if m.recipe is not None and m.day >= today)
    return render(
        request,
        "meals/index.html",
        {
            "days": days,
            "today": today,
            "grid": grid,
            "slots": SLOT_LABELS,
            "this_week": weeks_away == 0,
            "week_label": week_label,
            "week": start.isoformat(),
            "week_url": _week_url(hid, start, first),
            "prev_url": _week_url(hid, start - timedelta(days=7), first),
            "next_url": _week_url(hid, start + timedelta(days=7), first),
            "this_url": _week_url(hid, this_week, first),
            "recipes": db.query(Recipe).filter_by(household_id=hid).order_by(Recipe.name).all(),
            "has_recipes": any(m.recipe is not None for m in meals),
            "shop_url": plan_url(hid, ahead, _week_url(hid, start, first)) if ahead else None,
            "error": error,
        },
        db=db,
        membership=membership,
        status_code=status_code,
    )


def plan_url(household_id, counts, back):
    """The ingredient picker with these recipes chosen (a recipe planned twice counts twice); back returns to the week."""
    pairs = [("step", "pick")] + [("r", str(rid)) for rid in counts]
    pairs += [(f"m_{rid}", str(n)) for rid, n in counts.items() if n > 1]
    return f"/h/{household_id}/plan#" + urlencode(pairs + [("back", back)])


@router.get("/h/{household_id}/meals")
def meals_page(request: Request, household_id: int, week: str = "", membership=Depends(household_member), db: Session = Depends(get_db)):
    return _page(request, db, membership, _week_of(week, actions.first_weekday(membership.household)))


@router.post("/h/{household_id}/meals")
def add_meals(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Put recipes and/or a meal without one on a lunch or dinner, and stay on the week to plan the next."""
    first = actions.first_weekday(membership.household)
    start = _week_of(form.get("week", ""), first)
    ids = [i for i in (_int(v) for v in form.getlist("recipe_id")) if i is not None]
    try:
        actions.add_meals(db, household_id, form.get("day"), form.get("slot"), ids, form.get("title", ""))
    except actions.ActionError as e:
        return _page(request, db, membership, start, error=e.message, status_code=e.status)
    return RedirectResponse(_week_url(household_id, start, first) + f"#day-{form.get('day')}", status_code=303)


@router.post("/h/{household_id}/meals/{meal_id}/delete")
def delete_meal(request: Request, household_id: int, meal_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    first = actions.first_weekday(membership.household)
    start = _week_of(form.get("week", ""), first)
    try:
        actions.delete_meal(db, household_id, meal_id)
    except actions.ActionError:
        pass  # already gone: the week shows without it
    return RedirectResponse(_week_url(household_id, start, first), status_code=303)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
