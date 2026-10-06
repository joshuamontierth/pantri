from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import actions, config, security
from ..db import get_db
from ..deps import current_session, current_user
from ..templating import render

router = APIRouter()

def _safe_next(next_url):
    if next_url and next_url.startswith("/") and not next_url.startswith(("//", "/\\")):
        return next_url
    return "/"


def _logged_in(request, db):
    return security.load_session(db, request.cookies.get(config.SESSION_COOKIE)) is not None


@router.get("/login")
def login_form(request: Request, next: str = "/", db: Session = Depends(get_db)):
    if _logged_in(request, db):
        return RedirectResponse(_safe_next(next), status_code=303)
    return render(request, "auth/login.html", {"next": next})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    user = security.find_user(db, username)
    if not security.verify_password(user, password):
        return render(
            request,
            "auth/login.html",
            {"next": next, "username": username, "error": "Wrong username or password."},
            status_code=400,
        )
    token = security.create_session(db, user)
    response = RedirectResponse(_safe_next(next), status_code=303)
    security.set_session_cookie(response, token)
    return response


@router.get("/signup")
def signup_form(request: Request, db: Session = Depends(get_db)):
    if _logged_in(request, db):
        return RedirectResponse("/", status_code=303)
    return render(request, "auth/signup.html", {})


@router.post("/signup")
def signup(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    confirm: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        user = actions.signup(db, username, password, confirm)
    except actions.ActionError as e:
        return render(request, "auth/signup.html", {"username": username.strip(), "error": e.message}, status_code=400)
    token = security.create_session(db, user)
    response = RedirectResponse("/", status_code=303)
    security.set_session_cookie(response, token)
    return response


@router.post("/logout")
def logout(request: Request, _sess=Depends(current_session), db: Session = Depends(get_db)):
    security.delete_session(db, request.cookies.get(config.SESSION_COOKIE))
    response = RedirectResponse("/login", status_code=303)
    security.clear_session_cookie(response)
    # Forget the lists and pages saved for offline use on this device (app.js also does this on the login page).
    response.headers["Clear-Site-Data"] = '"cache", "storage"'
    return response


@router.get("/account")
def account(request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return render(request, "auth/account.html", {}, db=db)


@router.get("/account/password")
def password_form(request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return render(request, "auth/password.html", {"forced": user.must_change_password}, db=db)


@router.post("/account/password")
def change_password(
    request: Request,
    current: str = Form(""),
    password: str = Form(""),
    confirm: str = Form(""),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    forced = user.must_change_password
    try:
        actions.change_password(db, user, current, password, confirm, keep_token=request.cookies.get(config.SESSION_COOKIE))
    except actions.ActionError as e:
        return render(request, "auth/password.html", {"forced": forced, "error": e.message}, status_code=400, db=db)
    return RedirectResponse("/account?changed=1", status_code=303)
