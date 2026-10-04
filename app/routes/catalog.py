from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..deps import household_member
from ..models import CatalogItem
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
    item = db.get(CatalogItem, item_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(404, "Catalog item not found")
    return item


def _name_error(db, household_id, name, exclude_id=None):
    if not name or len(name) > 100:
        return "Name must be 1 to 100 characters."
    existing = services.find_catalog_item(db, household_id, name)
    if existing is not None and existing.id != exclude_id:
        return f"“{existing.name}” is already in the catalog."
    return None


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


def _form(request, db, membership, item=None, name="", rank_ids=None, error=None, next_url="", status_code=200):
    hid = membership.household_id
    stores = services.household_stores(db, hid)
    return render(
        request,
        "catalog/edit.html",
        {
            "item": item,
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
    name = name.strip()
    rank_ids = services.parse_rank_ids(db, household_id, ranks)
    error = _name_error(db, household_id, name)
    if error:
        return _form(request, db, membership, name=name, rank_ids=rank_ids, error=error, next_url=next, status_code=400)
    services.create_catalog_item(db, household_id, name, rank_ids)
    db.commit()
    return RedirectResponse(_safe_next(household_id, next), status_code=303)


@router.get("/h/{household_id}/catalog/{item_id}")
def edit_item(request: Request, household_id: int, item_id: int, next: str = "", membership=Depends(household_member), db: Session = Depends(get_db)):
    return _form(request, db, membership, item=_get_item(db, household_id, item_id), next_url=next)


@router.post("/h/{household_id}/catalog/{item_id}")
def update_item(
    request: Request, household_id: int, item_id: int,
    name: str = Form(""), ranks: str = Form(""), next: str = Form(""),
    membership=Depends(household_member), db: Session = Depends(get_db),
):
    item = _get_item(db, household_id, item_id)
    name = name.strip()
    rank_ids = services.parse_rank_ids(db, household_id, ranks)
    error = _name_error(db, household_id, name, exclude_id=item.id)
    if error:
        return _form(request, db, membership, item=item, name=name, rank_ids=rank_ids, error=error, next_url=next, status_code=400)
    if name != item.name:
        services.rename_catalog_item(db, item, name)
    services.set_ranks(db, item, rank_ids)
    db.commit()
    # Back to the catalog list, which reopens on the filter the user last picked.
    return RedirectResponse(_safe_next(household_id, next), status_code=303)


@router.post("/h/{household_id}/catalog/{item_id}/delete")
def delete_item(request: Request, household_id: int, item_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    item = _get_item(db, household_id, item_id)
    used_by = services.recipes_using(db, item.id)
    if used_by:
        names = ", ".join(r.name for r in used_by)
        return _form(request, db, membership, item=item, error=f"Can't delete: used by {names}. Remove it from those recipes first.", status_code=400)
    db.delete(item)
    db.commit()
    return RedirectResponse(f"/h/{household_id}/catalog", status_code=303)
