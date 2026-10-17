from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import actions, config, services
from ..db import get_db
from ..deps import _session as logged_in
from ..deps import current_user, household_admin, household_member
from ..models import Household, Invite, Membership, User
from ..templating import render

router = APIRouter()

LAST_HOUSEHOLD_COOKIE = "last_household"


def _redirect(url):
    return RedirectResponse(url, status_code=303)


def _pending_invites(db, user):
    return actions.pending_invites(db, user)


def _memberships(db, user):
    return (
        db.query(Membership)
        .join(Household, Household.id == Membership.household_id)
        .filter(Membership.user_id == user.id)
        .order_by(Household.name)
        .all()
    )


@router.get("/")
def home(request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    memberships = _memberships(db, user)
    invites = _pending_invites(db, user)
    ids = {m.household_id for m in memberships}
    last = services.parse_int(request.cookies.get(LAST_HOUSEHOLD_COOKIE))
    if not invites:
        if last in ids:
            return _redirect(f"/h/{last}")
        if len(memberships) == 1:
            return _redirect(f"/h/{memberships[0].household_id}")
    return _households_page(request, db, memberships, invites)


@router.api_route("/share", methods=["GET", "POST"])
def share(request: Request, text: str = "", photos: int = 0, sess=Depends(logged_in), db: Session = Depends(get_db)):
    """Where things shared to the installed site land (see static/sw.js): on to your recipes page,
    which imports the link or photos. (A POST only happens without the service worker; it carries no
    photos.) It changes nothing, so it needs no CSRF token: the share sheet can't send one."""
    from urllib.parse import urlencode

    user = sess.user
    memberships = _memberships(db, user)
    ids = {m.household_id for m in memberships}
    last = services.parse_int(request.cookies.get(LAST_HOUSEHOLD_COOKIE))
    hid = last if last in ids else (memberships[0].household_id if len(memberships) == 1 else None)
    if hid is None:
        return _redirect("/households")
    return _redirect(f"/h/{hid}/recipes?" + urlencode({"shared": 1, "text": text[:2000], "photos": max(0, min(photos, 4))}))


@router.get("/households")
def households_page(request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return _households_page(request, db, _memberships(db, user), _pending_invites(db, user))


def _households_page(request, db, memberships, invites, error=None, status_code=200):
    return render(
        request,
        "households/index.html",
        {"memberships": memberships, "invites": invites, "error": error},
        db=db,
        status_code=status_code,
    )


@router.post("/households")
def create_household(
    request: Request, name: str = Form(""), user=Depends(current_user), db: Session = Depends(get_db)
):
    try:
        household = actions.create_household(db, user, name)
    except actions.ActionError as e:
        return _households_page(request, db, _memberships(db, user), _pending_invites(db, user), error=e.message, status_code=400)
    return _redirect(f"/h/{household.id}/stores?new=1")


def _act(fn, *args, page=None):
    """Run a shared action; its message goes on the page (or a 404)."""
    try:
        return fn(*args)
    except actions.ActionError as e:
        if e.status == 404 or page is None:
            raise HTTPException(e.status, e.message)
        return page(e.message)


@router.post("/invites/{invite_id}/accept")
def accept_invite(invite_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    hid = _act(actions.accept_invite, db, user, invite_id)
    return _redirect(f"/h/{hid}")


@router.post("/invites/{invite_id}/decline")
def decline_invite(invite_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    _act(actions.decline_invite, db, user, invite_id)
    return _redirect("/households")


# ---- household settings ----

def _settings_page(request, db, membership, error=None, notice=None, status_code=200):
    hid = membership.household_id
    members = (
        db.query(Membership)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.household_id == hid)
        .order_by(Membership.role, User.username_lower)
        .all()
    )
    invites = db.query(Invite).filter_by(household_id=hid).order_by(Invite.created_at).all()
    return render(
        request,
        "households/settings.html",
        {"members": members, "invites": invites, "error": error, "notice": notice, "android_apk": ANDROID_APK.exists()},
        db=db,
        membership=membership,
        status_code=status_code,
    )


# Put a built app here (see README, "Android app") to offer it on the settings page.
ANDROID_APK = config.DATA_DIR / "Pantri.apk"


@router.get("/android/Pantri.apk")
def android_apk(user=Depends(current_user)):
    if not ANDROID_APK.exists():
        raise HTTPException(404, "The Android app hasn't been put on this server.")
    return FileResponse(ANDROID_APK, media_type="application/vnd.android.package-archive", filename="Pantri.apk")


@router.get("/h/{household_id}/settings")
def settings(request: Request, notice: str = "", membership=Depends(household_member), db: Session = Depends(get_db)):
    return _settings_page(request, db, membership, notice=notice or None)


def _error_page(request, db, membership):
    return lambda message: _settings_page(request, db, membership, error=message, status_code=400)


@router.post("/h/{household_id}/rename")
def rename(
    request: Request, household_id: int, name: str = Form(""),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    failed = _act(actions.rename_household, db, membership, name, page=_error_page(request, db, membership))
    return failed or _redirect(f"/h/{household_id}/settings")


@router.post("/h/{household_id}/invite")
def invite(
    request: Request, household_id: int, username: str = Form(""),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    target = _act(actions.invite, db, membership, username, page=_error_page(request, db, membership))
    if not isinstance(target, User):
        return target
    return _redirect(f"/h/{household_id}/settings?notice=Invited+{target.username}")


@router.post("/h/{household_id}/invites/{invite_id}/cancel")
def cancel_invite(household_id: int, invite_id: int, membership=Depends(household_admin), db: Session = Depends(get_db)):
    _act(actions.cancel_invite, db, household_id, invite_id)
    return _redirect(f"/h/{household_id}/settings")


@router.post("/h/{household_id}/members/{member_id}/role")
def set_role(
    request: Request, household_id: int, member_id: int, role: str = Form(...),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    failed = _act(actions.set_role, db, household_id, member_id, role, page=_error_page(request, db, membership))
    return failed or _redirect(f"/h/{household_id}/settings")


@router.post("/h/{household_id}/members/{member_id}/remove")
def remove_member(
    request: Request, household_id: int, member_id: int,
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    failed = _act(actions.remove_member, db, membership, member_id, page=_error_page(request, db, membership))
    return failed or _redirect(f"/h/{household_id}/settings")


@router.post("/h/{household_id}/members/{member_id}/reset-password")
def reset_password(
    request: Request, household_id: int, member_id: int,
    temp_password: str = Form(""),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    target = _act(actions.reset_password, db, membership, member_id, temp_password, page=_error_page(request, db, membership))
    if not isinstance(target, User):
        return target
    return _redirect(
        f"/h/{household_id}/settings?notice=Password+reset+for+{target.username}.+They+must+choose+a+new+one+at+next+login."
    )


@router.post("/h/{household_id}/leave")
def leave(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    failed = _act(actions.leave, db, membership, page=_error_page(request, db, membership))
    if failed:
        return failed
    response = _redirect("/households")
    response.delete_cookie(LAST_HOUSEHOLD_COOKIE)
    return response


@router.post("/h/{household_id}/delete")
def delete_household(
    request: Request, household_id: int, confirm_name: str = Form(""),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    failed = _act(actions.delete_household, db, membership, confirm_name, page=_error_page(request, db, membership))
    if failed:
        return failed
    response = _redirect("/households")
    response.delete_cookie(LAST_HOUSEHOLD_COOKIE)
    return response
