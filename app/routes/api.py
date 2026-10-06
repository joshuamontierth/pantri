"""JSON API for the Android app.

The app keeps a copy of the household (GET /state) and works offline from it. Changes made
offline are queued and sent as a batch of ops (POST /ops). Each op has an op_id and is applied
at most once, so the app can safely resend a batch whose response it never got. Items the app
added offline are referred to by its own id ("ref") until it learns the server's id.

Auth is a bearer token from POST /api/v1/login (the same sessions the website uses, so logins
show up and expire the same way). The website's own pages use the session cookie instead
(the lists page syncs through here too); then changes must carry the CSRF token, as on the
rest of the site.
"""

import asyncio
import hashlib
import json
import secrets
from datetime import timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session, selectinload

from .. import actions, config, importer, quantities, scan, security, services
from ..db import get_db
from ..deps import form_data
from ..events import broker
from ..models import CatalogItem, Household, Invite, ListItem, Membership, Recipe, RecipeIngredient, Store, SyncOp, User, utcnow

router = APIRouter(prefix="/api/v1")

MAX_OPS = 500
SYNC_OP_DAYS = 60


# ---------- auth ----------

def _bearer(request: Request):
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header[:7].lower() == "bearer " else ""


def api_session(request: Request, db: Session = Depends(get_db)):
    token = _bearer(request)
    from_cookie = not token
    if from_cookie:
        token = request.cookies.get(config.SESSION_COOKIE, "")
    sess = security.load_session(db, token)
    if sess is None:
        raise HTTPException(401, "Log in again.")
    if from_cookie:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or not secrets.compare_digest(supplied, sess.csrf_token):
                raise HTTPException(403, "Invalid or missing CSRF token. Reload the page and try again.")
        if getattr(sess, "refreshed", False):
            request.state.refresh_session_token = token  # keep the browser's cookie sliding too
    if sess.user.must_change_password and request.url.path not in _PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(403, "Choose a new password first.")
    request.state.api_token = token
    return sess


_PASSWORD_CHANGE_ALLOWED = ("/api/v1/account/password", "/api/v1/logout", "/api/v1/me")


def api_member(household_id: int, sess=Depends(api_session), db: Session = Depends(get_db)):
    membership = db.query(Membership).filter_by(household_id=household_id, user_id=sess.user_id).one_or_none()
    if membership is None:
        raise HTTPException(404, "Household not found")
    return membership


def api_admin(membership=Depends(api_member)):
    if not membership.is_admin:
        raise HTTPException(403, "Only household admins can do that.")
    return membership


def _act(fn, *args):
    """Run a shared action (actions.py); a failed check comes back as JSON {"detail": message}."""
    try:
        return fn(*args)
    except actions.ActionError as e:
        raise HTTPException(e.status, e.message)


def _households(db, user_id):
    rows = (
        db.query(Household, Membership.role)
        .join(Membership, Membership.household_id == Household.id)
        .filter(Membership.user_id == user_id)
        .order_by(Household.name)
        .all()
    )
    return [{"id": h.id, "name": h.name, "role": role} for h, role in rows]


def _me(db, user):
    return {
        "user": {"id": user.id, "username": user.username},
        "must_change_password": bool(user.must_change_password),
        "households": _households(db, user.id),
        "invites": [
            {"id": inv.id, "household": inv.household.name, "invited_by": inv.invited_by.username if inv.invited_by else None}
            for inv in actions.pending_invites(db, user)
        ],
        "features": {"scan": scan.enabled()},  # reading recipes from photos
    }


@router.post("/login")
def login(body: dict = Body(...), db: Session = Depends(get_db)):
    user = security.find_user(db, str(body.get("username") or ""))
    if not security.verify_password(user, str(body.get("password") or "")):
        raise HTTPException(401, "Wrong username or password.")
    # After an admin reset, must_change_password is true and the app asks for a new one first.
    return {"token": security.create_session(db, user), **_me(db, user)}


@router.post("/signup")
def signup(body: dict = Body(...), db: Session = Depends(get_db)):
    user = _act(actions.signup, db, str(body.get("username") or ""), str(body.get("password") or ""), str(body.get("confirm") or ""))
    return {"token": security.create_session(db, user), **_me(db, user)}


@router.post("/account/password")
def change_password(request: Request, body: dict = Body(...), sess=Depends(api_session), db: Session = Depends(get_db)):
    _act(actions.change_password, db, sess.user, str(body.get("current") or ""), str(body.get("password") or ""),
         str(body.get("confirm") or ""), request.state.api_token)
    return _me(db, db.get(User, sess.user_id))


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    security.delete_session(db, _bearer(request))
    return {"ok": True}


@router.get("/me")
def me(sess=Depends(api_session), db: Session = Depends(get_db)):
    return _me(db, sess.user)


# ---------- the household snapshot ----------

def _item(i):
    parts = i.quantities or []
    return {
        "id": i.id,
        "store_id": i.store_id,
        "name": i.name,
        "catalog_id": i.catalog_item_id,
        "quantities": parts,
        "qty": quantities.format_quantity(parts),
        "qty_text": quantities.quantity_input_text(parts),
        "note": i.note or "",
        "tags": i.recipe_tags or [],
        "checked": bool(i.checked),
        # Checked items are listed in the order they were checked.
        "checked_at": (i.checked_at or i.created_at).isoformat() if i.checked else None,
        "position": i.position,
    }


def household_state(db, household_id):
    household = db.get(Household, household_id)
    stores = services.household_stores(db, household_id)
    items = db.query(ListItem).filter_by(household_id=household_id).all()
    catalog = (
        db.query(CatalogItem).filter_by(household_id=household_id)
        .options(selectinload(CatalogItem.ranks)).order_by(CatalogItem.name_lower).all()
    )
    recipes = (
        db.query(Recipe).filter_by(household_id=household_id)
        .options(selectinload(Recipe.ingredients).selectinload(RecipeIngredient.catalog_item))
        .order_by(Recipe.name).all()
    )
    return {
        "household": {"id": household.id, "name": household.name},
        "other_label": services.OTHER_LABEL,
        "stores": [{"id": s.id, "name": s.name} for s in stores],
        "items": [_item(i) for i in sorted(items, key=lambda i: i.id)],
        "catalog": [{"id": c.id, "name": c.name, "ranks": c.ranked_store_ids} for c in catalog],
        "recipes": [
            {
                "id": r.id,
                "name": r.name,
                "directions": r.directions or "",
                "source_url": r.source_url or "",
                "ingredients": [
                    {
                        "catalog_id": ing.catalog_item_id,
                        "name": ing.catalog_item.name,
                        "amount": ing.amount,
                        "unit": ing.unit or "",
                        "qty": "" if ing.amount is None else quantities.format_part(ing.amount, ing.unit or ""),
                    }
                    for ing in r.ingredients
                ],
            }
            for r in recipes
        ],
    }


def _state_response(request, state):
    body = json.dumps(state, separators=(",", ":"))
    etag = '"' + hashlib.sha1(body.encode()).hexdigest() + '"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(body, media_type="application/json", headers={"ETag": etag, "Cache-Control": "no-cache"})


@router.get("/h/{household_id}/state")
def state(request: Request, household_id: int, membership=Depends(api_member), db: Session = Depends(get_db)):
    return _state_response(request, household_state(db, household_id))


# ---------- applying queued changes ----------

class OpSkipped(Exception):
    """The op no longer applies (usually: someone else removed the item). Not an error."""


class OpInvalid(Exception):
    pass


def _resolve(db, household_id, refs, value):
    """An item id from an op: the server's id, or the app's ref for something it added offline."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value:
        if value in refs:
            return refs[value]
        row = db.query(SyncOp).filter_by(household_id=household_id, client_ref=value[:64]).first()
        return row.item_id if row else None
    return None


def _item_for(db, household_id, refs, value):
    item_id = _resolve(db, household_id, refs, value)
    item = db.get(ListItem, item_id) if item_id is not None else None
    if item is None or item.household_id != household_id:
        raise OpSkipped("That item is gone. Someone may have removed it.")
    return item


def _store_for(db, household_id, value, catalog_item=None):
    """A store id from an op: an id, None for Other, or "auto". A store deleted meanwhile means Other."""
    if value == "auto":
        return services.primary_store_id(catalog_item)
    if value is None or isinstance(value, bool):
        return None
    sid = services.parse_int(value)
    store = db.get(Store, sid) if sid is not None else None
    return sid if store is not None and store.household_id == household_id else None


def _text(op, key, limit):
    value = op.get(key)
    return str(value).strip()[:limit] if value is not None else ""


def _parse_qty(op, note):
    """Quantity parts from "parts" (exact, from recipes) or "qty" (typed). Text we can't read becomes a note."""
    if op.get("parts") is not None:
        return services.clean_qty(op.get("parts")), note
    text = _text(op, "qty", 100)
    try:
        return quantities.parse_quantity(text), note
    except ValueError:
        return [], (f"{note}; {text}" if note else text)[:300]


def _op_add(db, hid, op, refs, keys):
    name = _text(op, "name", 100)
    if not name:
        raise OpInvalid("An item needs a name.")
    parts, note = _parse_qty(op, _text(op, "note", 300))
    tags = op.get("tags") if isinstance(op.get("tags"), list) else []
    tags = [str(t)[:150] for t in tags if isinstance(t, str) and t.strip()][:20]
    catalog_item = services.find_catalog_item(db, hid, name)
    store_id = _store_for(db, hid, op.get("store", "auto"), catalog_item)
    item, _ = services.add_to_list(db, hid, store_id, name, parts, catalog_item=catalog_item, note=note, tags=tags)
    keys.add(services.store_key(store_id))
    return item.id


def _op_check(db, hid, op, refs, keys):
    item = _item_for(db, hid, refs, op.get("item"))
    want = bool(op.get("checked"))
    keys.add(services.store_key(item.store_id))
    if item.checked == want:
        return item.id
    services.set_checked(item, want)
    if not want:
        # Un-checking: if the same item was re-added meanwhile, fold back into that line.
        db.flush()
        twin = services.find_mergeable(db, hid, item.store_id, item.name_lower, item.catalog_item_id, item.id)
        if twin is not None:
            services.merge_into(twin, item.quantities or [], item.note, item.recipe_tags or [])
            db.delete(item)
            return twin.id
    return item.id


def _op_update(db, hid, op, refs, keys):
    item = _item_for(db, hid, refs, op.get("item"))
    keys.add(services.store_key(item.store_id))
    name = _text(op, "name", 100) or item.name
    if name.lower() != item.name_lower:
        item.name = name
        item.name_lower = name.lower()
        catalog_item = services.find_catalog_item(db, hid, name)
        item.catalog_item_id = catalog_item.id if catalog_item else None
    else:
        item.name = name
    note = _text(op, "note", 300) if op.get("note") is not None else (item.note or "")
    if op.get("qty") is not None or op.get("parts") is not None:
        item.quantities, note = _parse_qty(op, note)
    item.note = note
    store_id = _store_for(db, hid, op.get("store"), None) if "store" in op else item.store_id
    survivor = services.merge_duplicate(db, services.move_item(db, item, store_id))
    keys.add(services.store_key(store_id))
    return survivor.id


def _op_delete(db, hid, op, refs, keys):
    item = _item_for(db, hid, refs, op.get("item"))
    keys.add(services.store_key(item.store_id))
    db.delete(item)
    return None


def _op_reorder(db, hid, op, refs, keys):
    store_id = _store_for(db, hid, op.get("store"))
    if store_id is None and op.get("store") is not None:
        raise OpSkipped("That store is gone.")
    unchecked, _ = services.list_items(db, hid, store_id)
    by_id = {i.id: i for i in unchecked}
    wanted = op.get("items") if isinstance(op.get("items"), list) else []
    ids = dict.fromkeys(_resolve(db, hid, refs, v) for v in wanted[:1000])
    ordered = [by_id[i] for i in ids if i in by_id]
    ordered += [i for i in unchecked if i not in ordered]  # added meanwhile: keep them, at the end
    for pos, item in enumerate(ordered):
        item.position = pos
    keys.add(services.store_key(store_id))
    return None


def _op_restore(db, hid, op, refs, keys):
    """Undo of a delete or clear that already reached the server. Items use services.snapshot()'s format."""
    snaps = op.get("items") if isinstance(op.get("items"), list) else []
    for snap in snaps[:500]:
        item = services.restore_snapshot(db, hid, snap)
        if item is not None:
            keys.add(services.store_key(item.store_id))
    return None


_HANDLERS = {
    "add": _op_add,
    "check": _op_check,
    "update": _op_update,
    "delete": _op_delete,
    "reorder": _op_reorder,
    "restore": _op_restore,
}


@router.post("/h/{household_id}/ops")
def apply_ops(request: Request, household_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    ops = body.get("ops")
    if not isinstance(ops, list) or len(ops) > MAX_OPS:
        raise HTTPException(400, f"Send a list of up to {MAX_OPS} changes.")
    refs, keys, results = {}, set(), []
    for op in ops:
        if not isinstance(op, dict) or not isinstance(op.get("op_id"), str) or not op["op_id"].strip():
            results.append({"op_id": None, "status": "error", "message": "Not a change I understand."})
            continue
        op_id = op["op_id"].strip()[:64]
        ref = op.get("ref")[:64] if isinstance(op.get("ref"), str) and op.get("ref") else None
        done = db.query(SyncOp).filter_by(household_id=household_id, op_id=op_id).one_or_none()
        if done is not None:
            if done.client_ref and done.item_id:
                refs[done.client_ref] = done.item_id
            results.append({"op_id": op_id, "status": "duplicate", "item_id": done.item_id})
            continue

        status, message, item_id = "ok", None, None
        handler = _HANDLERS.get(op.get("type"))
        try:
            if handler is None:
                raise OpInvalid("Not a change I understand.")
            item_id = handler(db, household_id, op, refs, keys)
        except OpSkipped as e:
            db.rollback()
            status, message = "skipped", str(e)
        except OpInvalid as e:
            db.rollback()
            status, message = "error", str(e)
        except Exception:  # noqa: BLE001  (one bad op mustn't block the rest of the queue forever)
            db.rollback()
            status, message = "error", "That change couldn't be applied."
        if ref and item_id:
            refs[ref] = item_id
        # Each op commits on its own, together with the record that it was applied.
        db.add(SyncOp(household_id=household_id, op_id=op_id, client_ref=ref, item_id=item_id, status=status))
        db.commit()
        result = {"op_id": op_id, "status": status, "item_id": item_id}
        if message:
            result["message"] = message
        results.append(result)

    db.query(SyncOp).filter(SyncOp.created_at < utcnow() - timedelta(days=SYNC_OP_DAYS)).delete(synchronize_session=False)
    db.commit()
    if keys:
        broker.publish(household_id, "lists", origin=request.headers.get("X-Client-Id"), stores=sorted(keys))
    return {"results": results, "state": household_state(db, household_id)}


# ---------- live updates ----------

@router.get("/h/{household_id}/events")
async def events(request: Request, household_id: int, membership=Depends(api_member), db: Session = Depends(get_db)):
    db.close()  # don't hold a DB connection for the life of the stream
    queue = broker.subscribe(household_id)

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
        finally:
            broker.unsubscribe(household_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- recipes: import, edit, delete (these need a connection) ----------

def _recipe_routes():
    from . import recipes  # (imported late: it's a sibling router module)

    return recipes


def _draft(name, rows, directions_text, source_url, notice, recipe_id=None, fresh=None):
    """A recipe for the app's editor to show; nothing is saved until it sends it back."""
    return {
        "recipe_id": recipe_id,
        "name": name,
        "ingredients": [
            {"name": r["name"], "amount": r["amount"], "unit": r["unit"], "ranks": r["ranks"], "fresh": r.get("fresh")}
            for r in rows
        ],
        "directions": directions_text,
        "source_url": source_url,
        "notice": notice,
        "fresh": fresh or {"directions": False, "link": False},
    }


def _get_recipe(db, household_id, recipe_id):
    recipe = db.get(Recipe, recipe_id) if recipe_id is not None else None
    if recipe is None or recipe.household_id != household_id:
        raise HTTPException(404, "That recipe is gone. Someone may have deleted it.")
    return recipe


def _read_draft(recipes, db, household_id, recipe, data, source, catalog):
    """Draft from what an import read: a new recipe, or (recipe given) only the gaps filled in."""
    if recipe is None:
        return _draft(data["name"], recipes._rows_from_import(catalog, data["ingredients"]), data.get("directions", ""),
                      data.get("source_url", ""), f"Read from {source}. Check the ingredients and stores, then save.")
    merged = recipes.augment(recipe, catalog, data)
    if not merged["found"]:
        return {"recipe_id": recipe.id, "nothing_new": True, "notice": recipes.nothing_new_notice(source)}
    return _draft(recipe.name, merged["rows"], merged["directions"], merged["source_url"],
                  recipes.added_notice(merged["found"], source), recipe_id=recipe.id, fresh=merged["fresh"])


@router.post("/h/{household_id}/recipes/scan")
def scan_recipe(household_id: int, form=Depends(form_data), membership=Depends(api_member), db: Session = Depends(get_db)):
    """Read a recipe from photos (field "photos", up to 4). With "recipe_id", only fill that recipe's gaps."""
    recipes = _recipe_routes()
    if not scan.enabled():
        raise HTTPException(404, "Reading recipes from photos isn't set up on this server.")
    rid = services.parse_int(form.get("recipe_id")) if form.get("recipe_id") else None
    recipe = _get_recipe(db, household_id, rid) if rid is not None else None
    catalog = services.catalog_items(db, household_id)
    try:
        photos = recipes._photo_bytes(form)
        names = recipes._names_for_model(recipe, catalog) if recipe else [c.name for c in catalog]
        data = scan.read_recipe(photos, names, recipe_name=recipe.name if recipe else None)
    except scan.ScanError as e:
        raise HTTPException(400, str(e))
    return _read_draft(recipes, db, household_id, recipe, data, recipes._your_photos(photos), catalog)


@router.post("/h/{household_id}/recipes/import")
def import_recipe(household_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    """Read a recipe from a link ({"url", "recipe_id"?})."""
    recipes = _recipe_routes()
    rid = services.parse_int(body.get("recipe_id")) if body.get("recipe_id") is not None else None
    recipe = _get_recipe(db, household_id, rid) if rid is not None else None
    catalog = services.catalog_items(db, household_id)
    try:
        names = recipes._names_for_model(recipe, catalog) if recipe else [c.name for c in catalog]
        data = importer.import_link(str(body.get("url") or ""), names, recipe_name=recipe.name if recipe else None)
    except scan.ScanError as e:
        raise HTTPException(400, str(e))
    return _read_draft(recipes, db, household_id, recipe, data, recipes._site(data["source_url"]) or "the link", catalog)


@router.get("/h/{household_id}/recipes/{recipe_id}/draft")
def recipe_draft(household_id: int, recipe_id: int, membership=Depends(api_member), db: Session = Depends(get_db)):
    """An existing recipe in editor form (exact amounts, as typed)."""
    recipes = _recipe_routes()
    recipe = _get_recipe(db, household_id, recipe_id)
    return _draft(recipe.name, recipes._rows_from_recipe(recipe), recipe.directions or "", recipe.source_url or "", None, recipe_id=recipe.id)


def _save(household_id, recipe, body, db):
    recipes = _recipe_routes()
    raw_rows = []
    for ing in body.get("ingredients") if isinstance(body.get("ingredients"), list) else []:
        if not isinstance(ing, dict):
            continue
        ranks = ing.get("ranks")
        raw_rows.append({
            "name": str(ing.get("name") or "").strip(),
            "amount": str(ing.get("amount") or "").strip(),
            "unit": str(ing.get("unit") or "").strip(),
            "ranks_text": ",".join(str(r) for r in ranks) if isinstance(ranks, list) else "",
            # Rankings for items already in the catalog change only when the app sends them.
            "dirty": isinstance(ranks, list) and bool(ing.get("ranks_changed")),
        })
    name = str(body.get("name") or "").strip()
    directions_text, source_url, extra_errors = recipes._read_extras(
        {"directions": str(body.get("directions") or ""), "source_url": str(body.get("source_url") or "")})
    errors, _, parsed = recipes._validate(db, household_id, name, raw_rows)
    errors += extra_errors
    if errors:
        return JSONResponse({"detail": errors[0], "errors": errors}, status_code=400)
    recipe = recipes.save_recipe(db, household_id, recipe, name, parsed, directions_text, source_url)
    return {"recipe_id": recipe.id, "state": household_state(db, household_id)}


@router.post("/h/{household_id}/recipes")
def create_recipe(household_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    return _save(household_id, None, body, db)


@router.put("/h/{household_id}/recipes/{recipe_id}")
def update_recipe(household_id: int, recipe_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    return _save(household_id, _get_recipe(db, household_id, recipe_id), body, db)


@router.delete("/h/{household_id}/recipes/{recipe_id}")
def delete_recipe(household_id: int, recipe_id: int, membership=Depends(api_member), db: Session = Depends(get_db)):
    db.delete(_get_recipe(db, household_id, recipe_id))
    db.commit()
    broker.publish(household_id, "recipes")
    return {"state": household_state(db, household_id)}


# ---------- households, invites, members (same rules as the website's settings page) ----------

@router.post("/households")
def create_household(body: dict = Body(...), sess=Depends(api_session), db: Session = Depends(get_db)):
    household = _act(actions.create_household, db, sess.user, str(body.get("name") or ""))
    return {"household_id": household.id, **_me(db, sess.user)}


@router.post("/invites/{invite_id}/accept")
def accept_invite(invite_id: int, sess=Depends(api_session), db: Session = Depends(get_db)):
    hid = _act(actions.accept_invite, db, sess.user, invite_id)
    return {"household_id": hid, **_me(db, sess.user)}


@router.post("/invites/{invite_id}/decline")
def decline_invite(invite_id: int, sess=Depends(api_session), db: Session = Depends(get_db)):
    _act(actions.decline_invite, db, sess.user, invite_id)
    return _me(db, sess.user)


def _settings(db, membership):
    hid = membership.household_id
    members = (
        db.query(Membership).join(User, User.id == Membership.user_id)
        .filter(Membership.household_id == hid).order_by(Membership.role, User.username_lower).all()
    )
    invites = db.query(Invite).filter_by(household_id=hid).order_by(Invite.created_at).all() if membership.is_admin else []
    return {
        "household": {"id": hid, "name": membership.household.name},
        "role": membership.role,
        "members": [
            {"id": m.id, "user_id": m.user_id, "username": m.user.username, "role": m.role, "is_me": m.user_id == membership.user_id}
            for m in members
        ],
        "invites": [{"id": inv.id, "username": inv.user.username} for inv in invites],
    }


@router.get("/h/{household_id}/settings")
def settings(membership=Depends(api_member), db: Session = Depends(get_db)):
    return _settings(db, membership)


@router.post("/h/{household_id}/rename")
def rename_household(body: dict = Body(...), membership=Depends(api_admin), db: Session = Depends(get_db)):
    _act(actions.rename_household, db, membership, str(body.get("name") or ""))
    return _settings(db, membership)


@router.post("/h/{household_id}/invites")
def invite(body: dict = Body(...), membership=Depends(api_admin), db: Session = Depends(get_db)):
    target = _act(actions.invite, db, membership, str(body.get("username") or ""))
    return {"notice": f"Invited {target.username}", **_settings(db, membership)}


@router.delete("/h/{household_id}/invites/{invite_id}")
def cancel_invite(household_id: int, invite_id: int, membership=Depends(api_admin), db: Session = Depends(get_db)):
    _act(actions.cancel_invite, db, household_id, invite_id)
    return _settings(db, membership)


@router.post("/h/{household_id}/members/{member_id}/role")
def set_role(household_id: int, member_id: int, body: dict = Body(...), membership=Depends(api_admin), db: Session = Depends(get_db)):
    _act(actions.set_role, db, household_id, member_id, str(body.get("role") or ""))
    return _settings(db, membership)


@router.delete("/h/{household_id}/members/{member_id}")
def remove_member(member_id: int, membership=Depends(api_admin), db: Session = Depends(get_db)):
    _act(actions.remove_member, db, membership, member_id)
    return _settings(db, membership)


@router.post("/h/{household_id}/members/{member_id}/reset-password")
def reset_password(member_id: int, body: dict = Body(...), membership=Depends(api_admin), db: Session = Depends(get_db)):
    target = _act(actions.reset_password, db, membership, member_id, str(body.get("temp_password") or ""))
    return {"notice": f"Password reset for {target.username}. They must choose a new one at next login.", **_settings(db, membership)}


@router.post("/h/{household_id}/leave")
def leave(membership=Depends(api_member), db: Session = Depends(get_db)):
    user = membership.user
    _act(actions.leave, db, membership)
    return _me(db, user)


@router.post("/h/{household_id}/delete")
def delete_household(body: dict = Body(...), membership=Depends(api_admin), db: Session = Depends(get_db)):
    user = membership.user
    _act(actions.delete_household, db, membership, str(body.get("confirm_name") or ""))
    return _me(db, user)


# ---------- stores and catalog (answers carry the fresh household) ----------

@router.post("/h/{household_id}/stores")
def add_store(household_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    _act(actions.add_store, db, household_id, str(body.get("name") or ""))
    return {"state": household_state(db, household_id)}


@router.put("/h/{household_id}/stores/{store_id}")
def rename_store(household_id: int, store_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    _act(actions.rename_store, db, household_id, store_id, str(body.get("name") or ""))
    return {"state": household_state(db, household_id)}


@router.post("/h/{household_id}/stores/reorder")
def reorder_stores(household_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    ids = body.get("ids") if isinstance(body.get("ids"), list) else []
    actions.reorder_stores(db, household_id, ids)
    return {"state": household_state(db, household_id)}


@router.delete("/h/{household_id}/stores/{store_id}")
def delete_store(household_id: int, store_id: int, membership=Depends(api_member), db: Session = Depends(get_db)):
    _act(actions.delete_store, db, household_id, store_id)
    return {"state": household_state(db, household_id)}


def _ranks(body):
    ranks = body.get("ranks")
    return [r for r in ranks if isinstance(r, int) and not isinstance(r, bool)] if isinstance(ranks, list) else []


@router.post("/h/{household_id}/catalog")
def create_catalog_item(household_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    item = _act(actions.create_catalog_item, db, household_id, str(body.get("name") or ""), _ranks(body))
    return {"id": item.id, "state": household_state(db, household_id)}


@router.put("/h/{household_id}/catalog/{item_id}")
def update_catalog_item(household_id: int, item_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    _act(actions.update_catalog_item, db, household_id, item_id, str(body.get("name") or ""), _ranks(body))
    return {"state": household_state(db, household_id)}


@router.delete("/h/{household_id}/catalog/{item_id}")
def delete_catalog_item(household_id: int, item_id: int, membership=Depends(api_member), db: Session = Depends(get_db)):
    _act(actions.delete_catalog_item, db, household_id, item_id)
    return {"state": household_state(db, household_id)}


@router.post("/h/{household_id}/recipes/{recipe_id}/copy")
def copy_recipe(recipe_id: int, body: dict = Body(...), membership=Depends(api_member), db: Session = Depends(get_db)):
    target = services.parse_int(body.get("target_household_id"))
    copy = _act(actions.copy_recipe, db, membership, recipe_id, target)
    return {"household_id": copy.household_id, "recipe_id": copy.id}
