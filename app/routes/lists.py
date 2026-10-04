import asyncio
import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from .. import quantities, services
from ..db import get_db
from ..deps import form_data, household_member
from ..events import broker
from ..models import ListItem, Store
from ..routes.households import LAST_HOUSEHOLD_COOKIE
from ..templating import render

router = APIRouter()


def _client_id(request):
    return request.headers.get("X-Client-Id")


def _store_names(stores):
    names = {services.store_key(s.id): s.name for s in stores}
    names[services.NO_STORE] = services.OTHER_LABEL
    return names


def _panel(db, household_id, key, stores):
    ok, sid = services.parse_store_key(db, household_id, key)
    if not ok:
        return None
    unchecked, checked = services.list_items(db, household_id, sid)
    return {
        "key": key,
        "name": _store_names(stores)[key],
        "store_id": sid,
        "unchecked": unchecked,
        "checked": checked,
    }


def _all_panels(db, household_id, stores):
    keys = [services.store_key(s.id) for s in stores] + [services.NO_STORE]
    return [_panel(db, household_id, k, stores) for k in keys]


def _oob_response(request, db, membership, keys, toast=None):
    """Re-render the given panels + the tab bar as out-of-band swaps."""
    hid = membership.household_id
    stores = services.household_stores(db, hid)
    valid = {services.store_key(s.id) for s in stores} | {services.NO_STORE}
    panels = [_panel(db, hid, k, stores) for k in dict.fromkeys(keys) if k in valid]
    return render(
        request,
        "lists/_oob.html",
        {
            "panels": panels,
            "stores": stores,
            "counts": services.unchecked_counts(db, hid),
            "toast": toast,
            "household_id": hid,
        },
        membership=membership,
    )


def _publish(request, household_id, keys):
    broker.publish(household_id, "lists", origin=_client_id(request), stores=list(dict.fromkeys(keys)))


def _get_item(db, household_id, item_id):
    item = db.get(ListItem, item_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(404, "That item is gone. Someone may have removed it.")
    return item


@router.get("/h/{household_id}")
def lists_page(request: Request, household_id: int, added: int = -1, membership=Depends(household_member), db: Session = Depends(get_db)):
    stores = services.household_stores(db, household_id)
    names = _store_names(stores)
    catalog = services.catalog_items(db, household_id)
    # For quick-add suggestions: each catalog item and where "Auto" would send it.
    suggest = []
    for c in catalog:
        key = services.store_key(services.primary_store_id(c))
        suggest.append({"n": c.name, "s": key, "sn": names.get(key, services.OTHER_LABEL)})
    response = render(
        request,
        "lists/index.html",
        {
            "stores": stores,
            "panels": _all_panels(db, household_id, stores),
            "counts": services.unchecked_counts(db, household_id),
            "catalog": catalog,
            "suggest": suggest,
            "added": added,
        },
        db=db,
        membership=membership,
    )
    response.set_cookie(LAST_HOUSEHOLD_COOKIE, str(household_id), max_age=365 * 24 * 3600, samesite="lax")
    return response


@router.get("/h/{household_id}/lists/refresh")
def refresh(request: Request, household_id: int, stores: str = "", membership=Depends(household_member), db: Session = Depends(get_db)):
    if stores == "all":
        keys = [services.store_key(s.id) for s in services.household_stores(db, household_id)] + [services.NO_STORE]
    else:
        keys = [k for k in stores.split(",") if k]
    return _oob_response(request, db, membership, keys)


@router.post("/h/{household_id}/items")
def quick_add(
    request: Request,
    household_id: int,
    name: str = Form(""),
    qty: str = Form(""),
    target: str = Form("auto"),
    membership=Depends(household_member),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Type an item name first.")
    if len(name) > 100:
        raise HTTPException(400, "Item name is too long.")
    note = ""
    try:
        parsed = quantities.parse_quantity(qty)
    except ValueError:
        # Not a quantity we understand ("a few", "big one"), so keep it as a note instead.
        parsed, note = [], qty.strip()[:300]

    catalog_item = services.find_catalog_item(db, household_id, name)
    if target == "auto":
        store_id = services.primary_store_id(catalog_item)
    else:
        ok, store_id = services.parse_store_key(db, household_id, target)
        if not ok:
            raise HTTPException(400, "That store no longer exists. Reload the page.")

    item, merged = services.add_to_list(db, household_id, store_id, name, parsed, catalog_item=catalog_item, note=note)
    db.commit()

    key = services.store_key(store_id)
    store_name = db.get(Store, store_id).name if store_id else services.OTHER_LABEL
    toast = {
        "text": f"Updated {item.name} on {store_name}" if merged else f"Added {item.name} to {store_name}",
        "catalog_offer": None if catalog_item else item.name,
        "key": key,
    }
    _publish(request, household_id, [key])
    return _oob_response(request, db, membership, [key], toast=toast)


@router.post("/h/{household_id}/items/{item_id}/toggle")
def toggle(request: Request, household_id: int, item_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    item = _get_item(db, household_id, item_id)
    if item.checked:
        # Un-checking: if the same item was re-added meanwhile, fold back into that line.
        services.set_checked(item, False)
        db.flush()
        twin = services.find_mergeable(db, household_id, item.store_id, item.name_lower, item.catalog_item_id, item.id)
        if twin is not None:
            services.merge_into(twin, item.quantities or [], item.note, item.recipe_tags or [])
            db.delete(item)
    else:
        services.set_checked(item, True)
    db.commit()
    key = services.store_key(item.store_id)
    _publish(request, household_id, [key])
    return _oob_response(request, db, membership, [key])


@router.get("/h/{household_id}/items/{item_id}/edit")
def edit_form(request: Request, household_id: int, item_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    item = _get_item(db, household_id, item_id)
    return render(
        request,
        "lists/_item_edit.html",
        {
            "item": item,
            "stores": services.household_stores(db, household_id),
            "qty_text": quantities.quantity_input_text(item.quantities or []),
            "household_id": household_id,
        },
    )


@router.post("/h/{household_id}/items/{item_id}")
def update_item(
    request: Request,
    household_id: int,
    item_id: int,
    name: str = Form(""),
    qty: str = Form(""),
    note: str = Form(""),
    store: str = Form("none"),
    membership=Depends(household_member),
    db: Session = Depends(get_db),
):
    item = _get_item(db, household_id, item_id)
    name = name.strip()
    if not name or len(name) > 100:
        raise HTTPException(400, "Name must be 1–100 characters.")
    try:
        parsed = quantities.parse_quantity(qty)
    except ValueError:
        raise HTTPException(400, f"Couldn't read the quantity “{qty}”. Try e.g. “2 lb” or “1 1/2 cups + 3 oz”.")
    ok, store_id = services.parse_store_key(db, household_id, store)
    if not ok:
        raise HTTPException(400, "That store no longer exists.")

    old_key = services.store_key(item.store_id)
    if name.lower() != item.name_lower:
        item.name = name
        item.name_lower = name.lower()
        catalog_item = services.find_catalog_item(db, household_id, name)
        item.catalog_item_id = catalog_item.id if catalog_item else None
    elif name != item.name:
        item.name = name
    item.quantities = parsed
    item.note = note.strip()[:300]
    survivor = services.move_item(db, item, store_id)
    services.merge_duplicate(db, survivor)
    db.commit()

    keys = [old_key, services.store_key(store_id)]
    _publish(request, household_id, keys)
    return _oob_response(request, db, membership, keys)


@router.post("/h/{household_id}/items/{item_id}/delete")
def delete_item(request: Request, household_id: int, item_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    item = _get_item(db, household_id, item_id)
    key = services.store_key(item.store_id)
    toast = {"text": f"Deleted {item.name}", "undo": services.snapshot([item])}
    db.delete(item)
    db.commit()
    _publish(request, household_id, [key])
    return _oob_response(request, db, membership, [key], toast=toast)


@router.post("/h/{household_id}/lists/{key}/clear-checked")
def clear_checked(request: Request, household_id: int, key: str, membership=Depends(household_member), db: Session = Depends(get_db)):
    ok, store_id = services.parse_store_key(db, household_id, key)
    if not ok:
        raise HTTPException(404, "List not found")
    _, checked = services.list_items(db, household_id, store_id)
    toast = None
    if checked:
        n = len(checked)
        toast = {"text": f"Cleared {n} item{'' if n == 1 else 's'}", "undo": services.snapshot(checked)}
    for item in checked:
        db.delete(item)
    db.commit()
    _publish(request, household_id, [key])
    return _oob_response(request, db, membership, [key], toast=toast)


@router.post("/h/{household_id}/restore-items")
def restore(request: Request, household_id: int, data: str = Form(""), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Undo for delete / clear checked."""
    try:
        snaps = json.loads(data)
    except ValueError:
        raise HTTPException(400, "Couldn't undo that.")
    if not isinstance(snaps, list) or len(snaps) > 500:
        raise HTTPException(400, "Couldn't undo that.")
    keys = []
    for snap in snaps:
        item = services.restore_snapshot(db, household_id, snap)
        if item is not None:
            keys.append(services.store_key(item.store_id))
    db.commit()
    if keys:
        _publish(request, household_id, keys)
    return _oob_response(request, db, membership, keys)


@router.post("/h/{household_id}/lists/{key}/reorder")
def reorder(request: Request, household_id: int, key: str, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    ok, store_id = services.parse_store_key(db, household_id, key)
    if not ok:
        raise HTTPException(404, "List not found")
    unchecked, _ = services.list_items(db, household_id, store_id)
    by_id = {i.id: i for i in unchecked}
    ids = dict.fromkeys(services.parse_int(x) for x in form.getlist("item"))
    ordered = [by_id[i] for i in ids if i in by_id]
    # Anything not in the submitted order (added meanwhile) keeps its relative order at the end.
    ordered += [i for i in unchecked if i not in ordered]
    for pos, item in enumerate(ordered):
        item.position = pos
    db.commit()
    _publish(request, household_id, [key])
    return HTMLResponse("")


@router.get("/h/{household_id}/events")
async def events(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    db.close()  # don't hold a DB connection for the life of the stream
    queue = broker.subscribe(household_id)

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
        finally:
            broker.unsubscribe(household_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
