"""Request dependencies: login, CSRF, household membership.

DB work happens in plain `def` dependencies so FastAPI runs it in the threadpool rather than
on the event loop (where a busy SQLite lock would stall every request and live stream).
"""

import secrets
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import config, security
from .db import get_db
from .models import Membership

# Paths a user who must change their password may still visit.
_PASSWORD_CHANGE_ALLOWED = ("/account/password", "/logout")


class LoginRequired(Exception):
    def __init__(self, next_url="/"):
        self.next_url = next_url


class RedirectTo(Exception):
    def __init__(self, url):
        self.url = url


async def form_data(request: Request):
    """The parsed form, for sync routes with dynamic field names (Starlette caches it)."""
    return await request.form()


def _session(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(config.SESSION_COOKIE)
    sess = security.load_session(db, token)
    if sess is None:
        next_url = request.url.path if request.method == "GET" else "/"
        raise LoginRequired(next_url)
    if getattr(sess, "refreshed", False):
        # Picked up by SessionCookieRefresh so the browser cookie slides along with the session.
        request.state.refresh_session_token = token
    request.state.user = sess.user
    request.state.csrf_token = sess.csrf_token
    if sess.user.must_change_password and request.url.path not in _PASSWORD_CHANGE_ALLOWED:
        raise RedirectTo("/account/password")
    return sess


async def current_session(request: Request, sess=Depends(_session)):
    """A logged-in session; unsafe methods must also carry the session's CSRF token."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        supplied = request.headers.get("X-CSRF-Token")
        if not supplied:
            supplied = (await request.form()).get("csrf_token")
        if not supplied or not secrets.compare_digest(str(supplied), sess.csrf_token):
            raise HTTPException(status_code=403, detail="Invalid or missing CSRF token. Reload the page and try again.")
    return sess


async def current_user(sess=Depends(current_session)):
    return sess.user


def household_member(household_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    membership = (
        db.query(Membership).filter_by(household_id=household_id, user_id=user.id).one_or_none()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Household not found")
    return membership


async def household_admin(membership: Membership = Depends(household_member)):
    if not membership.is_admin:
        raise HTTPException(status_code=403, detail="Only household admins can do that.")
    return membership


def login_url(next_url):
    return f"/login?next={quote(next_url)}" if next_url and next_url != "/" else "/login"
