"""The meal calendar: a week of lunches and dinners. Each can have several recipes and meals typed in without one.

Adding recipes can go straight on to the ingredient picker (plan.js) to put what's needed on the lists;
that's skipped for leftovers or a repeat. Changes need a connection; the page opens as last seen offline.
"""

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


def _week_of(text):
    try:
        return actions.week_start(actions.parse_day(text)) if text else actions.week_start(actions.today())
    except actions.ActionError:
        return actions.week_start(actions.today())


def _week_url(household_id, start):
    return f"/h/{household_id}/meals" + ("" if start == actions.week_start(actions.today()) else f"?week={start.isoformat()}")


def _page(request, db, membership, start, error=None, status_code=200):
    hid = membership.household_id
    days = [start + timedelta(days=i) for i in range(7)]
    meals = (
        db.query(Meal).options(selectinload(Meal.recipe))
        .filter(Meal.household_id == hid, Meal.day >= days[0], Meal.day <= days[-1])
        .order_by(Meal.position, Meal.id).all()
    )
    grid = {(d, slot): [] for d in days for slot in actions.MEAL_SLOTS}
    for m in meals:
        grid.setdefault((m.day, m.slot), []).append(m)
    week_recipe_ids = list(dict.fromkeys(m.recipe_id for m in meals if m.recipe_id is not None))
    today = actions.today()
    weeks_away = (start - actions.week_start(today)).days // 7
    week_label = {0: "This week", 1: "Next week", -1: "Last week"}.get(weeks_away, str(start.year))
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
            "prev_url": _week_url(hid, start - timedelta(days=7)),
            "next_url": _week_url(hid, start + timedelta(days=7)),
            "this_url": _week_url(hid, actions.week_start(today)),
            "recipes": db.query(Recipe).filter_by(household_id=hid).order_by(Recipe.name).all(),
            "shop_url": _plan_url(hid, week_recipe_ids, start) if week_recipe_ids else None,
            "error": error,
        },
        db=db,
        membership=membership,
        status_code=status_code,
    )


def _plan_url(household_id, recipe_ids, start):
    """The ingredient picker with these recipes chosen; its back link returns to this week."""
    pairs = [("step", "pick")] + [("r", str(i)) for i in recipe_ids] + [("back", _week_url(household_id, start))]
    return f"/h/{household_id}/plan#" + urlencode(pairs)


@router.get("/h/{household_id}/meals")
def meals_page(request: Request, household_id: int, week: str = "", membership=Depends(household_member), db: Session = Depends(get_db)):
    return _page(request, db, membership, _week_of(week))


@router.post("/h/{household_id}/meals")
def add_meals(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    start = _week_of(form.get("week", ""))
    ids = [i for i in (_int(v) for v in form.getlist("recipe_id")) if i is not None]
    try:
        recipes = actions.add_meals(db, household_id, form.get("day"), form.get("slot"), ids, form.get("title", ""))
    except actions.ActionError as e:
        return _page(request, db, membership, start, error=e.message, status_code=e.status)
    if recipes and form.get("shop") == "1":
        return RedirectResponse(_plan_url(household_id, [r.id for r in recipes], start), status_code=303)
    return RedirectResponse(_week_url(household_id, start) + f"#day-{form.get('day')}", status_code=303)


@router.post("/h/{household_id}/meals/{meal_id}/delete")
def delete_meal(request: Request, household_id: int, meal_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    start = _week_of(form.get("week", ""))
    try:
        actions.delete_meal(db, household_id, meal_id)
    except actions.ActionError:
        pass  # already gone: the week shows without it
    return RedirectResponse(_week_url(household_id, start), status_code=303)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
