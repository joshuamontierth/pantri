import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import config, security
from ..db import get_db
from ..deps import current_session, current_user
from ..models import User
from ..templating import render

router = APIRouter()

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


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
    username = username.strip()
    error = None
    if not USERNAME_RE.match(username):
        error = "Username must be 3–32 characters: letters, numbers, dot, dash or underscore."
    elif security.find_user(db, username) is not None:
        error = "That username is taken."
    else:
        error = security.validate_new_password(password, confirm)
    if error:
        return render(request, "auth/signup.html", {"username": username, "error": error}, status_code=400)

    user = User(username=username, username_lower=username.lower(), password_hash=security.hash_password(password))
    db.add(user)
    db.commit()
    token = security.create_session(db, user)
    response = RedirectResponse("/", status_code=303)
    security.set_session_cookie(response, token)
    return response


@router.post("/logout")
def logout(request: Request, _sess=Depends(current_session), db: Session = Depends(get_db)):
    security.delete_session(db, request.cookies.get(config.SESSION_COOKIE))
    response = RedirectResponse("/login", status_code=303)
    security.clear_session_cookie(response)
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
    error = None
    # After an admin reset, the user just logged in with the temporary password.
    if not forced and not security.verify_password(user, current):
        error = "Current password is wrong."
    if not error:
        error = security.validate_new_password(password, confirm)
    if not error and forced and security.verify_password(user, password):
        error = "Choose a password different from the temporary one."
    if error:
        return render(request, "auth/password.html", {"forced": forced, "error": error}, status_code=400, db=db)

    user = db.merge(user)
    user.password_hash = security.hash_password(password)
    user.must_change_password = False
    db.commit()
    security.delete_other_sessions(db, user.id, keep_token=request.cookies.get(config.SESSION_COOKIE))
    return RedirectResponse("/account?changed=1", status_code=303)
