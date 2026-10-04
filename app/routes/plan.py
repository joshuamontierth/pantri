"""Add one or more recipes to the store lists via the combined ingredient picker."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import quantities, services
from ..db import get_db
from ..deps import form_data, household_member
from ..events import broker
from ..models import CatalogItem, ListItem, Recipe
from ..templating import render

router = APIRouter()

ORDINALS = ["1st", "2nd", "3rd"]


def _ordinal(i):
    return ORDINALS[i] if i < len(ORDINALS) else f"{i + 1}th"


def _selections(db, household_id, params):
    """Read r=<id> (repeated) and m_<id>=<multiplier> from a query string or form.

    Returns (selections, errors) where selections is a list of dicts.
    """
    seen, selections, errors = set(), [], []
    for raw in params.getlist("r"):
        rid = services.parse_int(raw)
        if rid is None or rid in seen:
            continue
        recipe = db.get(Recipe, rid)
        if recipe is None or recipe.household_id != household_id:
            continue
        seen.add(recipe.id)
        mult_text = (params.get(f"m_{recipe.id}") or "1").strip()
        try:
            mult = quantities.parse_amount(mult_text)
            if mult is None or mult <= 0 or mult > 100:
                raise ValueError
        except ValueError:
            errors.append(f"Couldn't read the multiplier for {recipe.name}: “{mult_text}”.")
            mult = 1.0
        selections.append({"recipe": recipe, "mult": mult, "mult_text": mult_text})
    return selections, errors


def _combined_rows(selections):
    """One row per catalog item across all selected recipes, scaled and merged."""
    rows = {}
    for sel in selections:
        recipe, mult = sel["recipe"], sel["mult"]
        for ing in recipe.ingredients:
            row = rows.setdefault(
                ing.catalog_item_id,
                {"catalog_item": ing.catalog_item, "qty": [], "tags": []},
            )
            if ing.amount is not None:
                row["qty"] = quantities.combine(row["qty"], [[ing.amount * mult, ing.unit]])
            if recipe.name not in row["tags"]:
                row["tags"].append(recipe.name)
    return list(rows.values())


def _decorate_rows(db, household_id, rows, params):
    """Add store options, current selections (from params) and 'already on a list' info."""
    stores = services.household_stores(db, household_id)
    store_names = {s.id: s.name for s in stores}
    included = set(params.getlist("include"))
    ids = [r["catalog_item"].id for r in rows]
    on_list = {}
    if ids:
        existing = (
            db.query(ListItem)
            .filter(ListItem.household_id == household_id, ListItem.checked.is_(False), ListItem.catalog_item_id.in_(ids))
            .all()
        )
        for li in existing:
            where = store_names.get(li.store_id, services.OTHER_LABEL)
            qty = quantities.format_quantity(li.quantities or [])
            on_list.setdefault(li.catalog_item_id, []).append(f"{where}: {qty}" if qty else where)

    for row in rows:
        item = row["catalog_item"]
        ranked = [sid for sid in item.ranked_store_ids if sid in store_names]
        # (value, store name, rank label); the template shows "Costco · 1st".
        ranked_opts = [(str(sid), store_names[sid], _ordinal(i)) for i, sid in enumerate(ranked)]
        other_opts = [(str(s.id), s.name, "") for s in stores if s.id not in ranked]
        default = str(ranked[0]) if ranked else services.NO_STORE
        chosen = params.get(f"store_{item.id}") or default
        valid = {opt[0] for opt in ranked_opts + other_opts} | {services.NO_STORE}
        row.update(
            {
                "id": item.id,
                "qty_text": quantities.format_quantity(row["qty"]),
                "ranked_opts": ranked_opts,
                "other_opts": other_opts,
                "selected": chosen if chosen in valid else default,
                "included": str(item.id) in included,
                "on_list": on_list.get(item.id, []),
            }
        )
    return rows


@router.get("/h/{household_id}/plan")
def choose_recipes(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    selections, _ = _selections(db, household_id, request.query_params)
    recipes = db.query(Recipe).filter_by(household_id=household_id).order_by(Recipe.name).all()
    return render(
        request,
        "plan/choose.html",
        {
            "recipes": recipes,
            "selected": {s["recipe"].id: s["mult_text"] for s in selections},
        },
        db=db,
        membership=membership,
    )


@router.get("/h/{household_id}/plan/pick")
def pick(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    params = request.query_params
    selections, errors = _selections(db, household_id, params)
    if not selections:
        return RedirectResponse(f"/h/{household_id}/plan", status_code=303)
    rows = _decorate_rows(db, household_id, _combined_rows(selections), params)
    back = urlencode([("r", s["recipe"].id) for s in selections] + [(f"m_{s['recipe'].id}", s["mult_text"]) for s in selections])
    return render(
        request,
        "plan/pick.html",
        {"selections": selections, "rows": rows, "errors": errors, "back_query": back},
        db=db,
        membership=membership,
    )


@router.post("/h/{household_id}/plan/rows")
def rows_fragment(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    selections, errors = _selections(db, household_id, form)
    rows = _decorate_rows(db, household_id, _combined_rows(selections), form)
    return render(request, "plan/_rows.html", {"rows": rows, "errors": errors}, membership=membership)


@router.post("/h/{household_id}/plan/apply")
def apply(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    selections, errors = _selections(db, household_id, form)
    if errors:
        raise HTTPException(400, " ".join(errors))
    rows = _decorate_rows(db, household_id, _combined_rows(selections), form)
    keys, added = [], 0
    for row in rows:
        if not row["included"]:
            continue
        ok, store_id = services.parse_store_key(db, household_id, row["selected"])
        if not ok:
            store_id = None
        item = db.get(CatalogItem, row["id"])
        services.add_to_list(db, household_id, store_id, item.name, row["qty"], catalog_item=item, tags=row["tags"])
        keys.append(services.store_key(store_id))
        added += 1
    db.commit()
    if keys:
        broker.publish(household_id, "lists", stores=list(dict.fromkeys(keys)))
    first = f"#store-{keys[0]}" if keys else ""
    return RedirectResponse(f"/h/{household_id}?added={added}{first}", status_code=303)
