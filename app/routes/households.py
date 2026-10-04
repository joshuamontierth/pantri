from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import security, services
from ..db import get_db
from ..deps import current_user, household_admin, household_member
from ..events import broker
from ..models import Household, Invite, Membership, User
from ..templating import render

router = APIRouter()

LAST_HOUSEHOLD_COOKIE = "last_household"


def _redirect(url):
    return RedirectResponse(url, status_code=303)


def _pending_invites(db, user):
    return db.query(Invite).filter_by(user_id=user.id).order_by(Invite.created_at).all()


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
    name = name.strip()
    if not name or len(name) > 100:
        return _households_page(
            request, db, _memberships(db, user), _pending_invites(db, user),
            error="Give the household a name (up to 100 characters).", status_code=400,
        )
    household = Household(name=name)
    db.add(household)
    db.flush()
    db.add(Membership(household_id=household.id, user_id=user.id, role="admin"))
    db.commit()
    return _redirect(f"/h/{household.id}/stores?new=1")


def _own_invite(db, invite_id, user):
    invite = db.get(Invite, invite_id)
    if invite is None or invite.user_id != user.id:
        raise HTTPException(404, "Invite not found")
    return invite


@router.post("/invites/{invite_id}/accept")
def accept_invite(invite_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    invite = _own_invite(db, invite_id, user)
    hid = invite.household_id
    exists = db.query(Membership).filter_by(household_id=hid, user_id=user.id).one_or_none()
    if exists is None:
        db.add(Membership(household_id=hid, user_id=user.id, role="member"))
    db.delete(invite)
    db.commit()
    broker.publish(hid, "members")
    return _redirect(f"/h/{hid}")


@router.post("/invites/{invite_id}/decline")
def decline_invite(invite_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own_invite(db, invite_id, user))
    db.commit()
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
        {"members": members, "invites": invites, "error": error, "notice": notice},
        db=db,
        membership=membership,
        status_code=status_code,
    )


@router.get("/h/{household_id}/settings")
def settings(request: Request, notice: str = "", membership=Depends(household_member), db: Session = Depends(get_db)):
    return _settings_page(request, db, membership, notice=notice or None)


@router.post("/h/{household_id}/rename")
def rename(
    request: Request, household_id: int, name: str = Form(""),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    name = name.strip()
    if not name or len(name) > 100:
        return _settings_page(request, db, membership, error="Name must be 1–100 characters.", status_code=400)
    membership.household.name = name
    db.commit()
    return _redirect(f"/h/{household_id}/settings")


@router.post("/h/{household_id}/invite")
def invite(
    request: Request, household_id: int, username: str = Form(""),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    target = security.find_user(db, username)
    error = None
    if target is None:
        error = f"No user named “{username.strip()}”. They need to sign up first."
    elif db.query(Membership).filter_by(household_id=household_id, user_id=target.id).one_or_none():
        error = f"{target.username} is already a member."
    elif db.query(Invite).filter_by(household_id=household_id, user_id=target.id).one_or_none():
        error = f"{target.username} already has a pending invite."
    if error:
        return _settings_page(request, db, membership, error=error, status_code=400)
    db.add(Invite(household_id=household_id, user_id=target.id, invited_by_id=membership.user_id))
    db.commit()
    return _redirect(f"/h/{household_id}/settings?notice=Invited+{target.username}")


@router.post("/h/{household_id}/invites/{invite_id}/cancel")
def cancel_invite(household_id: int, invite_id: int, membership=Depends(household_admin), db: Session = Depends(get_db)):
    invite = db.get(Invite, invite_id)
    if invite is None or invite.household_id != household_id:
        raise HTTPException(404, "Invite not found")
    db.delete(invite)
    db.commit()
    return _redirect(f"/h/{household_id}/settings")


def _target_member(db, household_id, member_id):
    target = db.get(Membership, member_id)
    if target is None or target.household_id != household_id:
        raise HTTPException(404, "Member not found")
    return target


def _admin_count(db, household_id):
    return db.query(Membership).filter_by(household_id=household_id, role="admin").count()


@router.post("/h/{household_id}/members/{member_id}/role")
def set_role(
    request: Request, household_id: int, member_id: int, role: str = Form(...),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    if role not in ("admin", "member"):
        raise HTTPException(400, "Invalid role")
    target = _target_member(db, household_id, member_id)
    if target.role == "admin" and role == "member" and _admin_count(db, household_id) <= 1:
        return _settings_page(request, db, membership, error="A household needs at least one admin. Make someone else an admin first.", status_code=400)
    target.role = role
    db.commit()
    return _redirect(f"/h/{household_id}/settings")


@router.post("/h/{household_id}/members/{member_id}/remove")
def remove_member(
    request: Request, household_id: int, member_id: int,
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    target = _target_member(db, household_id, member_id)
    if target.user_id == membership.user_id:
        return _settings_page(request, db, membership, error="To remove yourself, use “Leave household”.", status_code=400)
    db.delete(target)
    db.commit()
    broker.publish(household_id, "members")
    return _redirect(f"/h/{household_id}/settings")


@router.post("/h/{household_id}/members/{member_id}/reset-password")
def reset_password(
    request: Request, household_id: int, member_id: int,
    temp_password: str = Form(""),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    target = _target_member(db, household_id, member_id)
    if target.user_id == membership.user_id:
        return _settings_page(request, db, membership, error="Change your own password from your account page.", status_code=400)
    error = security.validate_new_password(temp_password, temp_password)
    if error:
        return _settings_page(request, db, membership, error=f"Temporary password: {error}", status_code=400)
    target.user.password_hash = security.hash_password(temp_password)
    target.user.must_change_password = True
    db.commit()
    security.delete_other_sessions(db, target.user_id)
    return _redirect(
        f"/h/{household_id}/settings?notice=Password+reset+for+{target.user.username}.+They+must+choose+a+new+one+at+next+login."
    )


@router.post("/h/{household_id}/leave")
def leave(request: Request, household_id: int, membership=Depends(household_member), db: Session = Depends(get_db)):
    member_count = db.query(Membership).filter_by(household_id=household_id).count()
    if member_count == 1:
        return _settings_page(request, db, membership, error="You're the only member. Delete the household instead.", status_code=400)
    if membership.is_admin and _admin_count(db, household_id) <= 1:
        return _settings_page(request, db, membership, error="You're the last admin. Make someone else an admin before leaving.", status_code=400)
    db.delete(membership)
    db.commit()
    broker.publish(household_id, "members")
    response = _redirect("/households")
    response.delete_cookie(LAST_HOUSEHOLD_COOKIE)
    return response


@router.post("/h/{household_id}/delete")
def delete_household(
    request: Request, household_id: int, confirm_name: str = Form(""),
    membership=Depends(household_admin), db: Session = Depends(get_db),
):
    household = membership.household
    if confirm_name.strip() != household.name:
        return _settings_page(request, db, membership, error="Type the household name exactly to confirm deletion.", status_code=400)
    db.delete(household)
    db.commit()
    broker.publish(household_id, "deleted")
    response = _redirect("/households")
    response.delete_cookie(LAST_HOUSEHOLD_COOKIE)
    return response
