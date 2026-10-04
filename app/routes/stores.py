from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..deps import form_data, household_member
from ..events import broker
from ..models import Store
from ..templating import render

router = APIRouter()


def _page(request, db, membership, error=None, status_code=200, is_new=False):
    return render(
        request,
        "stores/index.html",
        {
            "stores": services.household_stores(db, membership.household_id),
            "counts": services.unchecked_counts(db, membership.household_id),
            "error": error,
            "is_new": is_new,
        },
        db=db,
        membership=membership,
        status_code=status_code,
    )


def _get_store(db, household_id, store_id):
    store = db.get(Store, store_id)
    if store is None or store.household_id != household_id:
        raise HTTPException(404, "Store not found")
    return store


def _name_error(db, household_id, name, exclude_id=None):
    if not name or len(name) > 100:
        return "Store name must be 1–100 characters."
    if name.lower() in (services.OTHER_LABEL.lower(), "no store"):
        return f"“{name}” is reserved for items without a store."
    for s in services.household_stores(db, household_id):
        if s.id != exclude_id and s.name.lower() == name.lower():
            return f"There's already a store called {s.name}."
    return None


def _changed(household_id):
    broker.publish(household_id, "stores")


@router.get("/h/{household_id}/stores")
def stores_page(request: Request, new: int = 0, membership=Depends(household_member), db: Session = Depends(get_db)):
    return _page(request, db, membership, is_new=bool(new))


@router.post("/h/{household_id}/stores")
def add_store(request: Request, household_id: int, name: str = Form(""), membership=Depends(household_member), db: Session = Depends(get_db)):
    name = name.strip()
    error = _name_error(db, household_id, name)
    if error:
        return _page(request, db, membership, error=error, status_code=400)
    top = db.query(func.max(Store.position)).filter_by(household_id=household_id).scalar()
    db.add(Store(household_id=household_id, name=name, position=0 if top is None else top + 1))
    db.commit()
    _changed(household_id)
    return RedirectResponse(f"/h/{household_id}/stores", status_code=303)


@router.post("/h/{household_id}/stores/reorder")
def reorder_stores(household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    stores = services.household_stores(db, household_id)
    by_id = {s.id: s for s in stores}
    ids = dict.fromkeys(services.parse_int(x) for x in form.getlist("store"))
    ordered = [by_id[i] for i in ids if i in by_id]
    ordered += [s for s in stores if s not in ordered]
    for pos, store in enumerate(ordered):
        store.position = pos
    db.commit()
    _changed(household_id)
    return HTMLResponse("")


@router.post("/h/{household_id}/stores/{store_id}/rename")
def rename_store(
    request: Request, household_id: int, store_id: int, name: str = Form(""),
    membership=Depends(household_member), db: Session = Depends(get_db),
):
    store = _get_store(db, household_id, store_id)
    name = name.strip()
    error = _name_error(db, household_id, name, exclude_id=store.id)
    if error:
        return _page(request, db, membership, error=error, status_code=400)
    store.name = name
    db.commit()
    _changed(household_id)
    return RedirectResponse(f"/h/{household_id}/stores", status_code=303)


@router.post("/h/{household_id}/stores/{store_id}/delete")
def delete_store(request: Request, household_id: int, store_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    store = _get_store(db, household_id, store_id)
    services.delete_store(db, store)
    db.commit()
    _changed(household_id)
    return RedirectResponse(f"/h/{household_id}/stores", status_code=303)
