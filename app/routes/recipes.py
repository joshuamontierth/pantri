from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

import re
from urllib.parse import urlsplit

from .. import directions, importer, quantities, scan, services
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


def _editor(request, db, membership, recipe=None, name="", rows=None, directions_text="", source_url="",
            errors=None, notice=None, status_code=200):
    hid = membership.household_id
    catalog = services.catalog_items(db, hid)
    return render(
        request,
        "recipes/edit.html",
        {
            "recipe": recipe,
            "name": name,
            "rows": rows if rows is not None else [],
            "directions": directions_text,
            "source_url": source_url,
            "errors": errors or [],
            "notice": notice,
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
    return form.get("name", "").strip(), rows


def _read_extras(form):
    """(directions, source_url, errors) from the editor form."""
    errors = []
    text = directions.normalize(form.get("directions", ""))
    if len(text) > directions.MAX_LENGTH:
        errors.append(f"Directions can be up to {directions.MAX_LENGTH:,} characters.")
    link = form.get("source_url", "").strip()
    if link:
        try:
            link = importer.normalize_link(link)
        except ValueError:
            errors.append("The recipe link should be a web address, like https://www.allrecipes.com/recipe/…")
    return text, link, errors


def _validate(db, household_id, name, raw_rows):
    errors = []
    if not name or len(name) > 150:
        errors.append("Recipe name must be 1 to 150 characters.")
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
    return errors, rows, parsed


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


def _recipes_page(request, db, membership, scan_error=None, status_code=200):
    recipes = db.query(Recipe).filter_by(household_id=membership.household_id).order_by(Recipe.name).all()
    return render(request, "recipes/index.html", {"recipes": recipes, "scan_error": scan_error},
                  db=db, membership=membership, status_code=status_code)


@router.get("/h/{household_id}/recipes")
def recipes_page(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    return _recipes_page(request, db, membership)


# Seasoning-sized measures don't belong on a shopping list; these become a blank amount.
_VAGUE_RE = re.compile(r"\b(pinch|pinches|dash|dashes|smidgen|splash|sprinkle|drizzle|to taste|as needed|as desired|optional)\b", re.I)


def _clean_scanned_amount(amount_text, unit_text):
    """Tidy what the model read ("1-2", "Tbsp.", "cloves") into what the editor accepts, or blank it."""
    amount_text, unit_text = amount_text.strip(), unit_text.strip()
    if _VAGUE_RE.search(amount_text) or _VAGUE_RE.search(unit_text):
        return "", ""
    # A package size that ended up in the unit: "4" + "4 ounce" is 4, "1" + "16 ounce package" is 1 package.
    unit_text = re.sub(r"^\(?\s*[\d./]+\s*-?\s*[a-z]+\.?\s*\)?\s*", "", unit_text, flags=re.I) if amount_text else unit_text
    rng = re.match(r"^(.+?)\s*(?:-|–|to)\s*(.+)$", amount_text)
    if rng:
        amount_text = rng.group(2)  # ranges: buy enough for the larger amount
    if not amount_text:
        return "", ""
    try:
        value = quantities.parse_amount(amount_text)
        unit = quantities.normalize_unit(unit_text)
    except ValueError:
        try:
            # e.g. amount "2 cups" with the unit folded in
            value, unit = quantities.parse_part(f"{amount_text} {unit_text}")
        except ValueError:
            return "", ""  # "some", "a few": leave it blank so the recipe still saves
    if not value or value <= 0:
        return "", ""
    return quantities.amount_input_text(value), quantities.unit_label(unit)


@router.post("/h/{household_id}/recipes/scan")
def scan_recipe(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Read a recipe from photos and open it in the editor for review. Nothing is saved yet."""
    if not scan.enabled():
        raise HTTPException(404, "Reading recipes from photos isn't set up on this server.")
    photos = [f for f in form.getlist("photos") if hasattr(f, "file") and f.filename]
    if len(photos) > scan.MAX_PHOTOS:
        return _recipes_page(request, db, membership, f"Use up to {scan.MAX_PHOTOS} photos at a time.", 400)
    catalog = services.catalog_items(db, household_id)
    try:
        data = scan.read_recipe([f.file.read(scan.MAX_PHOTO_BYTES + 1) for f in photos], [c.name for c in catalog])
    except scan.ScanError as e:
        return _recipes_page(request, db, membership, str(e), 400)

    n = len(photos)
    return _prefilled_editor(request, db, membership, catalog, data,
                             f"Read from your photo{'s' if n != 1 else ''}. Check the ingredients and stores, then save.")


@router.post("/h/{household_id}/recipes/import")
def import_recipe(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Read a recipe from a link and open it in the editor for review. Nothing is saved yet."""
    catalog = services.catalog_items(db, household_id)
    try:
        data = importer.import_link(form.get("url", ""), [c.name for c in catalog])
    except scan.ScanError as e:
        return _recipes_page(request, db, membership, str(e), 400)
    site = re.sub(r"^www\.", "", urlsplit(data["source_url"]).hostname or "the link")
    return _prefilled_editor(request, db, membership, catalog, data,
                             f"Read from {site}. Check the ingredients and stores, then save.")


def _prefilled_editor(request, db, membership, catalog, data, notice):
    by_name = {c.name_lower: c for c in catalog}
    rows, seen = [], set()
    for ing in data["ingredients"]:
        known = by_name.get(ing["item"].lower())
        amount, unit = _clean_scanned_amount(ing["amount"], ing["unit"])
        key = ing["item"].lower()
        if key in seen and not amount:
            continue  # "1 tsp salt, plus more for sprinkling" read as two salts
        seen.add(key)
        rows.append({
            "name": known.name if known else ing["item"][:1].upper() + ing["item"][1:],
            "amount": amount,
            "unit": unit,
            "ranks": known.ranked_store_ids if known else [],
            "dirty": False,
        })
    return _editor(request, db, membership, name=data["name"], rows=rows, directions_text=data.get("directions", ""),
                   source_url=data.get("source_url", ""), notice=notice)


@router.get("/h/{household_id}/recipes/new")
def new_recipe(request: Request, membership=Depends(household_member), db: Session = Depends(get_db)):
    return _editor(request, db, membership)


@router.post("/h/{household_id}/recipes")
def create_recipe(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    name, raw_rows = _read_editor_form(form)
    directions_text, source_url, extra_errors = _read_extras(form)
    errors, rows, parsed = _validate(db, household_id, name, raw_rows)
    if errors or extra_errors:
        return _editor(request, db, membership, name=name, rows=rows, directions_text=directions_text,
                       source_url=form.get("source_url", "").strip(), errors=errors + extra_errors, status_code=400)
    recipe = Recipe(household_id=household_id, name=name, directions=directions_text or None, source_url=source_url or None)
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
        {"recipe": recipe, "store_names": stores, "other_households": other_households, "copied": copied,
         "steps": directions.steps(recipe.directions or ""),
         "source_site": re.sub(r"^www\.", "", urlsplit(recipe.source_url).hostname or "") if recipe.source_url else ""},
        db=db,
        membership=membership,
    )


@router.get("/h/{household_id}/recipes/{recipe_id}/edit")
def edit_recipe(request: Request, household_id: int, recipe_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    recipe = _get_recipe(db, household_id, recipe_id)
    return _editor(
        request, db, membership, recipe=recipe, name=recipe.name, rows=_rows_from_recipe(recipe),
        directions_text=recipe.directions or "", source_url=recipe.source_url or "",
    )


@router.post("/h/{household_id}/recipes/{recipe_id}")
def update_recipe(request: Request, household_id: int, recipe_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    recipe = _get_recipe(db, household_id, recipe_id)
    name, raw_rows = _read_editor_form(form)
    directions_text, source_url, extra_errors = _read_extras(form)
    errors, rows, parsed = _validate(db, household_id, name, raw_rows)
    if errors or extra_errors:
        return _editor(request, db, membership, recipe=recipe, name=name, rows=rows, directions_text=directions_text,
                       source_url=form.get("source_url", "").strip(), errors=errors + extra_errors, status_code=400)
    recipe.name = name
    recipe.directions = directions_text or None
    recipe.source_url = source_url or None
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
    copy = Recipe(household_id=target_household_id, name=recipe.name, directions=recipe.directions, source_url=recipe.source_url)
    db.add(copy)
    db.flush()
    for ing in recipe.ingredients:
        item = services.find_catalog_item(db, target_household_id, ing.catalog_item.name)
        if item is None:
            item = services.create_catalog_item(db, target_household_id, ing.catalog_item.name)
        db.add(RecipeIngredient(recipe_id=copy.id, catalog_item_id=item.id, amount=ing.amount, unit=ing.unit, position=ing.position))
    db.commit()
    return RedirectResponse(f"/h/{target_household_id}/recipes/{copy.id}?copied=1", status_code=303)
