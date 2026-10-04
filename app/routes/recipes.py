from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import quantities, services
from ..db import get_db
from ..deps import form_data, household_member
from ..models import Household, Membership, Recipe, RecipeIngredient
from ..templating import render

router = APIRouter()


def _get_recipe(db, household_id, recipe_id):
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.household_id != household_id:
        raise HTTPException(404, "Recipe not found")
    return recipe


def _parse_ingredient_amount(amount_text, unit_text):
    """Return (amount or None, canonical unit). Accepts '2' + 'cups' or '2 cups' + ''."""
    amount_text = (amount_text or "").strip()
    if not amount_text:
        return None, ""
    try:
        return quantities.parse_amount(amount_text), quantities.normalize_unit(unit_text)
    except ValueError:
        amount, unit = quantities.parse_part(amount_text)  # may raise ValueError
        if (unit_text or "").strip():
            raise ValueError("amount has a unit in it and the unit box is filled too")
        return amount, unit


def _rows_from_recipe(recipe):
    return [
        {
            "name": ing.catalog_item.name,
            "amount": "" if ing.amount is None else quantities.amount_input_text(ing.amount),
            "unit": quantities.unit_label(ing.unit),
            "ranks": ing.catalog_item.ranked_store_ids,
            "dirty": False,
        }
        for ing in recipe.ingredients
    ]


def _editor(request, db, membership, recipe=None, name="", base_servings="", rows=None, errors=None, status_code=200):
    hid = membership.household_id
    catalog = services.catalog_items(db, hid)
    return render(
        request,
        "recipes/edit.html",
        {
            "recipe": recipe,
            "name": name,
            "base_servings": base_servings,
            "rows": rows if rows is not None else [],
            "errors": errors or [],
            "stores": services.household_stores(db, hid),
            "catalog_json": {c.name_lower: {"name": c.name, "ranks": c.ranked_store_ids} for c in catalog},
        },
        db=db,
        membership=membership,
        status_code=status_code,
    )


def _read_editor_form(form):
    names = form.getlist("ing_name")
    amounts = form.getlist("ing_amount")
    units = form.getlist("ing_unit")
    ranks = form.getlist("ing_ranks")
    dirty = form.getlist("ing_ranks_dirty")
    n = len(names)
    if not (len(amounts) == len(units) == len(ranks) == len(dirty) == n):
        raise HTTPException(400, "The ingredient form was incomplete. Reload and try again.")
    rows = [
        {"name": names[i].strip(), "amount": amounts[i].strip(), "unit": units[i].strip(),
         "ranks_text": ranks[i], "dirty": dirty[i] == "1"}
        for i in range(n)
    ]
    return form.get("name", "").strip(), form.get("base_servings", "").strip(), rows


def _validate(db, household_id, name, base_servings_text, raw_rows):
    errors = []
    if not name or len(name) > 150:
        errors.append("Recipe name must be 1–150 characters.")
    base_servings = None
    if base_servings_text:
        n = services.parse_int(base_servings_text)
        if n is not None and 0 < n <= 1000:
            base_servings = n
        else:
            errors.append("Servings must be a whole number like 4 (or leave it blank).")
    rows, parsed = [], []
    for raw in raw_rows:
        rank_ids = services.parse_rank_ids(db, household_id, raw["ranks_text"])
        row = {"name": raw["name"], "amount": raw["amount"], "unit": raw["unit"], "ranks": rank_ids, "dirty": raw["dirty"]}
        if not raw["name"]:
            if raw["amount"] or raw["unit"]:
                errors.append(f"An ingredient row has an amount ({raw['amount']} {raw['unit']}) but no name.")
                rows.append(row)
            continue
        rows.append(row)
        if len(raw["name"]) > 100:
            errors.append(f"Ingredient name too long: {raw['name'][:30]}…")
            continue
        try:
            amount, unit = _parse_ingredient_amount(raw["amount"], raw["unit"])
            if amount is not None and amount <= 0:
                raise ValueError("must be positive")
        except ValueError:
            errors.append(f"Couldn't read the amount for {raw['name']}: “{raw['amount']} {raw['unit']}”. Use e.g. 2, 1/2, 1 1/2 or 0.75.")
            continue
        parsed.append((raw["name"], amount, unit, rank_ids, raw["dirty"]))
    if not parsed and not errors:
        errors.append("Add at least one ingredient.")
    return errors, base_servings, rows, parsed


def _save_ingredients(db, household_id, recipe, parsed):
    db.query(RecipeIngredient).filter_by(recipe_id=recipe.id).delete(synchronize_session=False)
    db.flush()
    for pos, (name, amount, unit, rank_ids, dirty) in enumerate(parsed):
        item = services.find_catalog_item(db, household_id, name)
        if item is None:
            item = services.create_catalog_item(db, household_id, name, rank_ids)
        elif dirty:
            services.set_ranks(db, item, rank_ids)
        db.add(RecipeIngredient(recipe_id=recipe.id, catalog_item_id=item.id, amount=amount, unit=unit if amount is not None else "", position=pos))
    db.flush()
    db.expire(recipe, ["ingredients"])


@router.get("/h/{household_id}/recipes")
def recipes_page(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    recipes = db.query(Recipe).filter_by(household_id=household_id).order_by(Recipe.name).all()
    return render(request, "recipes/index.html", {"recipes": recipes}, db=db, membership=membership)


@router.get("/h/{household_id}/recipes/new")
def new_recipe(request: Request, membership=Depends(household_member), db: Session = Depends(get_db)):
    return _editor(request, db, membership)


@router.post("/h/{household_id}/recipes")
def create_recipe(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    name, servings_text, raw_rows = _read_editor_form(form)
    errors, base_servings, rows, parsed = _validate(db, household_id, name, servings_text, raw_rows)
    if errors:
        return _editor(request, db, membership, name=name, base_servings=servings_text, rows=rows, errors=errors, status_code=400)
    recipe = Recipe(household_id=household_id, name=name, base_servings=base_servings)
    db.add(recipe)
    db.flush()
    _save_ingredients(db, household_id, recipe, parsed)
    db.commit()
    return RedirectResponse(f"/h/{household_id}/recipes/{recipe.id}", status_code=303)


@router.get("/h/{household_id}/recipes/{recipe_id}")
def view_recipe(request: Request, household_id: int, recipe_id: int, copied: int = 0, membership=Depends(household_member), db: Session = Depends(get_db)):
    recipe = _get_recipe(db, household_id, recipe_id)
    stores = {s.id: s.name for s in services.household_stores(db, household_id)}
    other_households = (
        db.query(Household)
        .join(Membership, Membership.household_id == Household.id)
        .filter(Membership.user_id == membership.user_id, Household.id != household_id)
        .order_by(Household.name)
        .all()
    )
    return render(
        request,
        "recipes/view.html",
        {"recipe": recipe, "store_names": stores, "other_households": other_households, "copied": copied},
        db=db,
        membership=membership,
    )


@router.get("/h/{household_id}/recipes/{recipe_id}/edit")
def edit_recipe(request: Request, household_id: int, recipe_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    recipe = _get_recipe(db, household_id, recipe_id)
    return _editor(
        request, db, membership, recipe=recipe, name=recipe.name,
        base_servings=str(recipe.base_servings or ""), rows=_rows_from_recipe(recipe),
    )


@router.post("/h/{household_id}/recipes/{recipe_id}")
def update_recipe(request: Request, household_id: int, recipe_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    recipe = _get_recipe(db, household_id, recipe_id)
    name, servings_text, raw_rows = _read_editor_form(form)
    errors, base_servings, rows, parsed = _validate(db, household_id, name, servings_text, raw_rows)
    if errors:
        return _editor(request, db, membership, recipe=recipe, name=name, base_servings=servings_text, rows=rows, errors=errors, status_code=400)
    recipe.name = name
    recipe.base_servings = base_servings
    _save_ingredients(db, household_id, recipe, parsed)
    db.commit()
    return RedirectResponse(f"/h/{household_id}/recipes/{recipe.id}", status_code=303)


@router.post("/h/{household_id}/recipes/{recipe_id}/delete")
def delete_recipe(household_id: int, recipe_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    db.delete(_get_recipe(db, household_id, recipe_id))
    db.commit()
    return RedirectResponse(f"/h/{household_id}/recipes", status_code=303)


@router.post("/h/{household_id}/recipes/{recipe_id}/copy")
def copy_recipe(
    household_id: int, recipe_id: int, target_household_id: int = Form(...),
    membership=Depends(household_member), db: Session = Depends(get_db),
):
    recipe = _get_recipe(db, household_id, recipe_id)
    target_member = db.query(Membership).filter_by(household_id=target_household_id, user_id=membership.user_id).one_or_none()
    if target_member is None or target_household_id == household_id:
        raise HTTPException(404, "Household not found")
    copy = Recipe(household_id=target_household_id, name=recipe.name, base_servings=recipe.base_servings)
    db.add(copy)
    db.flush()
    for ing in recipe.ingredients:
        item = services.find_catalog_item(db, target_household_id, ing.catalog_item.name)
        if item is None:
            item = services.create_catalog_item(db, target_household_id, ing.catalog_item.name)
        db.add(RecipeIngredient(recipe_id=copy.id, catalog_item_id=item.id, amount=ing.amount, unit=ing.unit, position=ing.position))
    db.commit()
    return RedirectResponse(f"/h/{target_household_id}/recipes/{copy.id}?copied=1", status_code=303)
