from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import actions, services
from ..db import get_db
from ..deps import form_data, household_member
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


@router.get("/h/{household_id}/stores")
def stores_page(request: Request, new: int = 0, membership=Depends(household_member), db: Session = Depends(get_db)):
    return _page(request, db, membership, is_new=bool(new))


def _act(request, db, membership, fn, *args):
    try:
        fn(db, membership.household_id, *args)
    except actions.ActionError as e:
        if e.status == 404:
            raise HTTPException(404, e.message)
        return _page(request, db, membership, error=e.message, status_code=400)
    return RedirectResponse(f"/h/{membership.household_id}/stores", status_code=303)


@router.post("/h/{household_id}/stores")
def add_store(request: Request, household_id: int, name: str = Form(""), membership=Depends(household_member), db: Session = Depends(get_db)):
    return _act(request, db, membership, actions.add_store, name)


@router.post("/h/{household_id}/stores/reorder")
def reorder_stores(household_id: int, form=Depends(form_data), membership=Depends(household_member), db: Session = Depends(get_db)):
    actions.reorder_stores(db, household_id, form.getlist("store"))
    return HTMLResponse("")


@router.post("/h/{household_id}/stores/{store_id}/rename")
def rename_store(
    request: Request, household_id: int, store_id: int, name: str = Form(""),
    membership=Depends(household_member), db: Session = Depends(get_db),
):
    return _act(request, db, membership, actions.rename_store, store_id, name)


@router.post("/h/{household_id}/stores/{store_id}/delete")
def delete_store(request: Request, household_id: int, store_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    return _act(request, db, membership, actions.delete_store, store_id)
