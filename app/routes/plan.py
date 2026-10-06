"""Add one or more recipes to the store lists.

The picker runs in the browser (static/js/plan.js) from the household copy that the lists page
keeps, so it works offline; the items it adds go through the same change queue (routes/api.py).
"""

import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import household_member
from ..routes.api import household_state
from ..templating import render

router = APIRouter()


@router.get("/h/{household_id}/plan")
def plan(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    return render(
        request,
        "plan/index.html",
        {"state": household_state(db, household_id), "generated_ms": int(time.time() * 1000)},
        db=db,
        membership=membership,
    )


@router.get("/h/{household_id}/plan/pick")
def pick(request: Request, household_id: int, membership=Depends(household_member)):
    """Old links (?r=3&m_3=2): the picker now keeps its selection after the #."""
    params = [(k, v) for k, v in request.query_params.multi_items() if k == "r" or k.startswith("m_")]
    return RedirectResponse(f"/h/{household_id}/plan#" + urlencode([("step", "pick")] + params), status_code=303)
