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
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload

from .. import config, quantities, security, services
from ..db import get_db
from ..events import broker
from ..models import CatalogItem, Household, ListItem, Membership, Recipe, RecipeIngredient, Store, SyncOp, utcnow

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
    if sess.user.must_change_password:
        raise HTTPException(403, "Choose a new password on the website first, then log in here.")
    return sess


def api_member(household_id: int, sess=Depends(api_session), db: Session = Depends(get_db)):
    membership = db.query(Membership).filter_by(household_id=household_id, user_id=sess.user_id).one_or_none()
    if membership is None:
        raise HTTPException(404, "Household not found")
    return membership


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
    return {"user": {"id": user.id, "username": user.username}, "households": _households(db, user.id)}


@router.post("/login")
def login(body: dict = Body(...), db: Session = Depends(get_db)):
    user = security.find_user(db, str(body.get("username") or ""))
    if not security.verify_password(user, str(body.get("password") or "")):
        raise HTTPException(401, "Wrong username or password.")
    if user.must_change_password:
        raise HTTPException(403, "Choose a new password on the website first, then log in here.")
    return {"token": security.create_session(db, user), **_me(db, user)}


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
