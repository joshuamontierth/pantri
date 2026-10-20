import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import actions, scan, services
from ..db import get_db
from ..deps import form_data, household_member
from ..templating import render

router = APIRouter()

ALL = "all"


def _filter_cookie(household_id):
    return f"catalog_store_{household_id}"


def _safe_next(household_id, next_url):
    prefix = f"/h/{household_id}"
    if next_url and (next_url == prefix or next_url.startswith((prefix + "/", prefix + "?", prefix + "#"))):
        return next_url
    return f"/h/{household_id}/catalog"


def _get_item(db, household_id, item_id):
    try:
        return actions.get_catalog_item(db, household_id, item_id)
    except actions.ActionError as e:
        raise HTTPException(404, e.message)


# ---- the store filter, remembered per household in a cookie ----

def _current_filter(request, household_id, stores, requested=None):
    """'all', 'none' (no stores = Other) or a store id as a string."""
    key = requested if requested is not None else request.cookies.get(_filter_cookie(household_id), ALL)
    valid = {ALL, services.NO_STORE} | {str(s.id) for s in stores}
    return key if key in valid else ALL


def _matches(item, key):
    if key == ALL:
        return True
    if key == services.NO_STORE:
        return not item.ranks
    return int(key) in item.ranked_store_ids


def _filter_label(key, stores):
    if key == services.NO_STORE:
        return services.OTHER_LABEL
    return next((s.name for s in stores if str(s.id) == key), "All")


def _form(request, db, membership, item=None, name="", rank_ids=None, error=None, next_url="", notice=None, status_code=200):
    hid = membership.household_id
    stores = services.household_stores(db, hid)
    return render(
        request,
        "catalog/edit.html",
        {
            "item": item,
            "notice": notice,
            "others": [c for c in services.catalog_items(db, hid) if item is None or c.id != item.id],
            "name": name if name or item is None else item.name,
            "rank_ids": rank_ids if rank_ids is not None else (item.ranked_store_ids if item else []),
            "stores": stores,
            "used_by": services.recipes_using(db, item.id) if item else [],
            "error": error,
            "next": _safe_next(hid, next_url) if next_url else "",
        },
        db=db,
        membership=membership,
        status_code=status_code,
    )


@router.get("/h/{household_id}/catalog")
def catalog_page(request: Request, household_id: int, store: str | None = None, membership=Depends(household_member), db: Session = Depends(get_db)):
    stores = services.household_stores(db, household_id)
    key = _current_filter(request, household_id, stores, requested=store)
    everything = services.catalog_items(db, household_id)
    filters = [{"key": ALL, "label": "All", "count": len(everything)}]
    filters += [{"key": str(s.id), "label": s.name, "count": sum(_matches(c, str(s.id)) for c in everything)} for s in stores]
    filters.append({"key": services.NO_STORE, "label": services.OTHER_LABEL, "count": sum(_matches(c, services.NO_STORE) for c in everything)})
    response = render(
        request,
        "catalog/index.html",
        {
            "items": [c for c in everything if _matches(c, key)],
            "total": len(everything),
            "filters": filters,
            "current": key,
            "current_label": _filter_label(key, stores),
            "store_names": {s.id: s.name for s in stores},
            "uses_model": scan.enabled(),
        },
        db=db,
        membership=membership,
    )
    response.set_cookie(_filter_cookie(household_id), key, max_age=365 * 24 * 3600, samesite="lax")
    return response


@router.get("/h/{household_id}/catalog/new")
def new_item(request: Request, household_id: int, name: str = "", next: str = "", membership=Depends(household_member), db: Session = Depends(get_db)):
    return _form(request, db, membership, name=name.strip(), next_url=next)


@router.post("/h/{household_id}/catalog")
def create_item(
    request: Request, household_id: int,
    name: str = Form(""), ranks: str = Form(""), next: str = Form(""),
    membership=Depends(household_member), db: Session = Depends(get_db),
):
    rank_ids = services.parse_rank_ids(db, household_id, ranks)
    try:
        actions.create_catalog_item(db, household_id, name, rank_ids)
    except actions.ActionError as e:
        return _form(request, db, membership, name=name.strip(), rank_ids=rank_ids, error=e.message, next_url=next, status_code=400)
    return RedirectResponse(_safe_next(household_id, next), status_code=303)


# ---- possible duplicates, one group at a time (before the /{item_id} routes) ----

def _duplicates_page(request, db, membership, queue, total, merged=0, skipped=0, error=None, status_code=200):
    """The next group in the queue that still has two or more items, or the end."""
    hid = membership.household_id
    group = None
    while queue and group is None:
        ids, reason = queue.pop(0)
        group = actions.describe_group(db, hid, ids, reason)
    return render(
        request,
        "catalog/duplicates.html",
        {
            "group": group,
            "position": total - len(queue),
            "total": total,
            "queue": json.dumps([[sorted(ids), reason] for ids, reason in queue]),
            "merged": merged,
            "skipped": skipped,
            "uses_model": scan.enabled(),
            "error": error,
        },
        db=db,
        membership=membership,
        status_code=status_code,
    )


def _ints(values):
    out = []
    for v in values:
        i = services.parse_int(v)
        if i is not None:
            out.append(i)
    return out


@router.post("/h/{household_id}/catalog/duplicates")
def find_duplicates(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    """Look for catalog items that are the same product (plurals always; more with the model), to merge or skip."""
    try:
        groups = actions.duplicate_groups(db, household_id)
    except scan.ScanError as e:
        return _duplicates_page(request, db, membership, [], 0, error=str(e), status_code=400)
    queue = [([i["id"] for i in g["items"]], g["reason"]) for g in groups]
    return _duplicates_page(request, db, membership, queue, len(queue))


@router.post("/h/{household_id}/catalog/duplicates/next")
def next_duplicate(request: Request, household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Merge or skip the group on screen, then show the next one."""
    try:
        queue = [(set(_ints(ids)), str(reason)[:80]) for ids, reason in json.loads(form.get("queue") or "[]")][:200]
    except (ValueError, TypeError):
        queue = []
    total = services.parse_int(form.get("total")) or len(queue)
    merged = services.parse_int(form.get("merged")) or 0
    skipped = services.parse_int(form.get("skipped")) or 0
    error = None
    if form.get("decision") == "merge":
        keep = services.parse_int(form.get("keep"))
        others = [i for i in _ints(form.getlist("include")) if i != keep]
        try:
            if keep is None or not others:
                raise actions.ActionError("Pick at least two to merge, and the one to keep.")
            actions.merge_catalog_items(db, household_id, keep, others)
            merged += 1
        except actions.ActionError as e:
            error = e.message
            queue.insert(0, (set(_ints(form.getlist("group"))), str(form.get("reason") or "")))
            total = max(total, 1)
    else:
        skipped += 1
    return _duplicates_page(request, db, membership, queue, total, merged, skipped, error)


@router.post("/h/{household_id}/catalog/{item_id}/merge")
def merge_item(request: Request, household_id: int, item_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    """Merge this item and another; keep=this or other says whose name (and place in recipes) stays."""
    item = _get_item(db, household_id, item_id)
    other = services.parse_int(form.get("with"))
    keep, gone = (item_id, other) if form.get("keep") == "this" else (other, item_id)
    try:
        if other is None:
            raise actions.ActionError("Pick the item to merge with.")
        kept = actions.merge_catalog_items(db, household_id, keep, [gone])
    except actions.ActionError as e:
        return _form(request, db, membership, item=item, error=e.message, status_code=e.status)
    return RedirectResponse(f"/h/{household_id}/catalog/{kept.id}?merged=1", status_code=303)


@router.get("/h/{household_id}/catalog/{item_id}")
def edit_item(request: Request, household_id: int, item_id: int, next: str = "", merged: int = 0, membership=Depends(household_member), db: Session = Depends(get_db)):
    notice = "Merged. Recipes and lists that used the other item use this one now." if merged else None
    return _form(request, db, membership, item=_get_item(db, household_id, item_id), next_url=next, notice=notice)


@router.post("/h/{household_id}/catalog/{item_id}")
def update_item(
    request: Request, household_id: int, item_id: int,
    name: str = Form(""), ranks: str = Form(""), next: str = Form(""),
    membership=Depends(household_member), db: Session = Depends(get_db),
):
    item = _get_item(db, household_id, item_id)
    rank_ids = services.parse_rank_ids(db, household_id, ranks)
    try:
        actions.update_catalog_item(db, household_id, item_id, name, rank_ids)
    except actions.ActionError as e:
        return _form(request, db, membership, item=item, name=name.strip(), rank_ids=rank_ids, error=e.message, next_url=next, status_code=400)
    # Back to the catalog list, which reopens on the filter the user last picked.
    return RedirectResponse(_safe_next(household_id, next), status_code=303)


@router.post("/h/{household_id}/catalog/{item_id}/delete")
def delete_item(request: Request, household_id: int, item_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    item = _get_item(db, household_id, item_id)
    try:
        actions.delete_catalog_item(db, household_id, item_id)
    except actions.ActionError as e:
        return _form(request, db, membership, item=item, error=e.message, status_code=400)
    return RedirectResponse(f"/h/{household_id}/catalog", status_code=303)
