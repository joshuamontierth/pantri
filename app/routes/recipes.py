from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

import re
from urllib.parse import urlsplit

from .. import actions, directions, importer, quantities, scan, services
from ..db import get_db
from ..deps import form_data, household_member
from ..events import broker
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
            errors=None, notice=None, fresh=None, status_code=200):
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
            "fresh": fresh or {},  # {"directions": bool, "link": bool}: just filled in from an import
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


def save_recipe(db, household_id, recipe, name, parsed, directions_text, source_url):
    """Create (recipe=None) or update a recipe from validated input. Commits and tells other devices."""
    if recipe is None:
        recipe = Recipe(household_id=household_id, name=name)
        db.add(recipe)
    recipe.name = name
    recipe.directions = directions_text or None
    recipe.source_url = source_url or None
    db.flush()
    _save_ingredients(db, household_id, recipe, parsed)
    db.commit()
    broker.publish(household_id, "recipes")
    return recipe


def _recipes_page(request, db, membership, scan_error=None, status_code=200):
    recipes = db.query(Recipe).filter_by(household_id=membership.household_id).order_by(Recipe.name).all()
    return render(request, "recipes/index.html", {"recipes": recipes, "scan_error": scan_error},
                  db=db, membership=membership, status_code=status_code)


@router.get("/h/{household_id}/recipes")
def recipes_page(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    return _recipes_page(request, db, membership)


@router.post("/h/{household_id}/recipes/scan")
def scan_recipe(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Read a recipe from photos and open it in the editor for review. Nothing is saved yet."""
    if not scan.enabled():
        raise HTTPException(404, "Reading recipes from photos isn't set up on this server.")
    catalog = services.catalog_items(db, household_id)
    try:
        photos = _photo_bytes(form)
        data = scan.read_recipe(photos, [c.name for c in catalog])
    except scan.ScanError as e:
        return _recipes_page(request, db, membership, str(e), 400)
    return _prefilled_editor(request, db, membership, catalog, data,
                             f"Read from {_your_photos(photos)}. Check the ingredients and stores, then save.")


def _photo_bytes(form):
    photos = [f for f in form.getlist("photos") if hasattr(f, "file") and f.filename]
    if len(photos) > scan.MAX_PHOTOS:
        raise scan.ScanError(f"Use up to {scan.MAX_PHOTOS} photos at a time.")
    return [f.file.read(scan.MAX_PHOTO_BYTES + 1) for f in photos]


def _your_photos(photos):
    return "your photo" + ("s" if len(photos) != 1 else "")


def _site(url):
    return re.sub(r"^www\.", "", urlsplit(url).hostname or "") if url else ""


@router.post("/h/{household_id}/recipes/import")
def import_recipe(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Read a recipe from a link and open it in the editor for review. Nothing is saved yet."""
    catalog = services.catalog_items(db, household_id)
    try:
        data = importer.import_link(form.get("url", ""), [c.name for c in catalog])
    except scan.ScanError as e:
        return _recipes_page(request, db, membership, str(e), 400)
    return _prefilled_editor(request, db, membership, catalog, data,
                             f"Read from {_site(data['source_url']) or 'the link'}. Check the ingredients and stores, then save.")


def _prefilled_editor(request, db, membership, catalog, data, notice):
    return _editor(request, db, membership, name=data["name"], rows=_rows_from_import(catalog, data["ingredients"]),
                   directions_text=data.get("directions", ""), source_url=data.get("source_url", ""), notice=notice)


def _rows_from_import(catalog, ingredients):
    by_name = {c.name_lower: c for c in catalog}
    rows, seen = [], set()
    for ing in ingredients:
        known = by_name.get(ing["item"].lower())
        amount, unit = scan.clean_amount(ing["amount"], ing["unit"])
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
    return rows


# ---------- adding details to an existing recipe ----------

def _names_for_model(recipe, catalog):
    """The recipe's own ingredients first, so the model reuses their names."""
    mine = [ing.catalog_item.name for ing in recipe.ingredients]
    have = {n.lower() for n in mine}
    return mine + [c.name for c in catalog if c.name_lower not in have]


def _and(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def augment(recipe, catalog, data):
    """The recipe with only its gaps filled in from an import: nothing it already has is changed.

    Returns {rows, directions, source_url, fresh: {directions, link}, found: ["directions", "2 ingredients", ...]}.
    """
    rows = _rows_from_recipe(recipe)
    by_key = {services.name_key(r["name"]): r for r in rows}
    added = filled = 0
    for row in _rows_from_import(catalog, data["ingredients"]):
        have = by_key.get(services.name_key(row["name"]))
        if have is None:
            row["fresh"] = "Added"
            rows.append(row)
            by_key[services.name_key(row["name"])] = row
            added += 1
        elif not have["amount"] and row["amount"] and not have.get("fresh"):
            have.update(amount=row["amount"], unit=row["unit"], fresh="Amount added")
            filled += 1
    directions_text = recipe.directions or ""
    new_directions = not directions_text and bool(data.get("directions"))
    if new_directions:
        directions_text = data["directions"]
    source_url = recipe.source_url or ""
    new_link = not source_url and bool(data.get("source_url"))
    if new_link:
        source_url = data["source_url"]

    found = []
    if new_directions:
        found.append("directions")
    if added:
        found.append(f"{added} ingredient{'s' if added != 1 else ''}")
    if filled:
        found.append(f"{filled} amount{'s' if filled != 1 else ''}")
    if new_link:
        found.append("the link")
    return {"rows": rows, "directions": directions_text, "source_url": source_url,
            "fresh": {"directions": new_directions, "link": new_link}, "found": found}


def nothing_new_notice(source):
    return f"Nothing to add from {source}. This recipe already has everything it found."


def added_notice(found, source):
    return f"Added {_and(found)} from {source}. Check them, then save."


def _augmented_editor(request, db, membership, recipe, catalog, data, source):
    """The recipe in the editor with only its gaps filled in: nothing it already has is changed."""
    merged = augment(recipe, catalog, data)
    if not merged["found"]:
        return _view(request, db, membership, recipe, notice=nothing_new_notice(source))
    return _editor(request, db, membership, recipe=recipe, name=recipe.name, rows=merged["rows"],
                   directions_text=merged["directions"], source_url=merged["source_url"], fresh=merged["fresh"],
                   notice=added_notice(merged["found"], source))


@router.post("/h/{household_id}/recipes/{recipe_id}/scan")
def scan_into_recipe(request: Request, household_id: int, recipe_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Fill in what a recipe is missing (directions, ingredients, amounts) from photos. Nothing is saved yet."""
    if not scan.enabled():
        raise HTTPException(404, "Reading recipes from photos isn't set up on this server.")
    recipe = _get_recipe(db, household_id, recipe_id)
    catalog = services.catalog_items(db, household_id)
    try:
        photos = _photo_bytes(form)
        data = scan.read_recipe(photos, _names_for_model(recipe, catalog), recipe_name=recipe.name)
    except scan.ScanError as e:
        return _view(request, db, membership, recipe, error=str(e), status_code=400)
    return _augmented_editor(request, db, membership, recipe, catalog, data, _your_photos(photos))


@router.post("/h/{household_id}/recipes/{recipe_id}/import")
def import_into_recipe(request: Request, household_id: int, recipe_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Fill in what a recipe is missing from a link. Nothing is saved yet."""
    recipe = _get_recipe(db, household_id, recipe_id)
    catalog = services.catalog_items(db, household_id)
    try:
        data = importer.import_link(form.get("url", ""), _names_for_model(recipe, catalog), recipe_name=recipe.name)
    except scan.ScanError as e:
        return _view(request, db, membership, recipe, error=str(e), status_code=400)
    return _augmented_editor(request, db, membership, recipe, catalog, data, _site(data["source_url"]) or "the link")


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
    recipe = save_recipe(db, household_id, None, name, parsed, directions_text, source_url)
    return RedirectResponse(f"/h/{household_id}/recipes/{recipe.id}", status_code=303)


@router.get("/h/{household_id}/recipes/{recipe_id}")
def view_recipe(request: Request, household_id: int, recipe_id: int, copied: int = 0, membership=Depends(household_member), db: Session = Depends(get_db)):
    return _view(request, db, membership, _get_recipe(db, household_id, recipe_id), copied=copied)


def _view(request, db, membership, recipe, copied=0, notice=None, error=None, status_code=200):
    hid = membership.household_id
    stores = {s.id: s.name for s in services.household_stores(db, hid)}
    other_households = (
        db.query(Household)
        .join(Membership, Membership.household_id == Household.id)
        .filter(Membership.user_id == membership.user_id, Household.id != hid)
        .order_by(Household.name)
        .all()
    )
    return render(
        request,
        "recipes/view.html",
        {"recipe": recipe, "store_names": stores, "other_households": other_households, "copied": copied,
         "notice": notice, "error": error,
         "steps": directions.steps(recipe.directions or ""), "source_site": _site(recipe.source_url)},
        db=db,
        membership=membership,
        status_code=status_code,
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
    save_recipe(db, household_id, recipe, name, parsed, directions_text, source_url)
    return RedirectResponse(f"/h/{household_id}/recipes/{recipe.id}", status_code=303)


@router.post("/h/{household_id}/recipes/{recipe_id}/delete")
def delete_recipe(household_id: int, recipe_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    db.delete(_get_recipe(db, household_id, recipe_id))
    db.commit()
    broker.publish(household_id, "recipes")
    return RedirectResponse(f"/h/{household_id}/recipes", status_code=303)


@router.post("/h/{household_id}/recipes/{recipe_id}/copy")
def copy_recipe(
    household_id: int, recipe_id: int, target_household_id: int = Form(...),
    membership=Depends(household_member), db: Session = Depends(get_db),
):
    try:
        copy = actions.copy_recipe(db, membership, recipe_id, target_household_id)
    except actions.ActionError as e:
        raise HTTPException(e.status, e.message)
    return RedirectResponse(f"/h/{target_household_id}/recipes/{copy.id}?copied=1", status_code=303)
