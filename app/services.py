"""Shared household data operations: list items, catalog, stores."""

import json
import math

from sqlalchemy import func

from . import quantities
from .models import CatalogItem, ListItem, Recipe, RecipeIngredient, Store, StoreRank, utcnow

NO_STORE = "none"
# What the store-less list is called in the UI.
OTHER_LABEL = "Other"


def parse_int(text):
    """int(text) or None. Never raises (isdigit() accepts things like '²' that int() rejects)."""
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


# ---- store keys ("none" or the store id as a string) ----

def store_key(store_id):
    return NO_STORE if store_id is None else str(store_id)


def parse_store_key(db, household_id, key):
    """Return (ok, store_id). store_id None means the store-less "Other" list."""
    if key in (None, "", NO_STORE):
        return True, None
    sid = parse_int(key)
    if sid is None:
        return False, None
    store = db.get(Store, sid)
    if store is None or store.household_id != household_id:
        return False, None
    return True, sid


def household_stores(db, household_id):
    return db.query(Store).filter_by(household_id=household_id).order_by(Store.position, Store.id).all()


# ---- list items ----

def list_items(db, household_id, store_id):
    q = db.query(ListItem).filter(ListItem.household_id == household_id)
    q = q.filter(ListItem.store_id.is_(None)) if store_id is None else q.filter(ListItem.store_id == store_id)
    items = q.all()
    unchecked = sorted((i for i in items if not i.checked), key=lambda i: (i.position, i.id))
    checked = sorted((i for i in items if i.checked), key=lambda i: (i.checked_at or i.created_at, i.id))
    return unchecked, checked


def unchecked_counts(db, household_id):
    rows = (
        db.query(ListItem.store_id, func.count(ListItem.id))
        .filter(ListItem.household_id == household_id, ListItem.checked.is_(False))
        .group_by(ListItem.store_id)
        .all()
    )
    return {store_key(sid): n for sid, n in rows}


def _next_position(db, household_id, store_id):
    q = db.query(func.max(ListItem.position)).filter(ListItem.household_id == household_id)
    q = q.filter(ListItem.store_id.is_(None)) if store_id is None else q.filter(ListItem.store_id == store_id)
    current = q.scalar()
    return 0 if current is None else current + 1


def find_mergeable(db, household_id, store_id, name_lower, catalog_item_id, exclude_id=None):
    q = db.query(ListItem).filter(
        ListItem.household_id == household_id,
        ListItem.checked.is_(False),
    )
    q = q.filter(ListItem.store_id.is_(None)) if store_id is None else q.filter(ListItem.store_id == store_id)
    if exclude_id is not None:
        q = q.filter(ListItem.id != exclude_id)
    for item in q.all():
        if catalog_item_id is not None and item.catalog_item_id == catalog_item_id:
            return item
        if item.name_lower == name_lower:
            return item
    return None


def merge_into(target, qty, note, tags):
    target.quantities = quantities.combine(target.quantities or [], qty)
    merged_tags = list(target.recipe_tags or [])
    for tag in tags:
        if tag not in merged_tags:
            merged_tags.append(tag)
    target.recipe_tags = merged_tags
    note = (note or "").strip()
    if note and note.lower() not in (target.note or "").lower():
        target.note = f"{target.note}; {note}" if target.note else note


def add_to_list(db, household_id, store_id, name, qty=None, catalog_item=None, note="", tags=()):
    """Add an item to a store's list, merging into a matching unchecked line. Returns (item, merged)."""
    if catalog_item is not None:
        name = catalog_item.name
    name = name.strip()
    name_lower = name.lower()
    qty = qty or []
    cid = catalog_item.id if catalog_item is not None else None

    existing = find_mergeable(db, household_id, store_id, name_lower, cid)
    if existing is not None:
        merge_into(existing, qty, note, tags)
        if existing.catalog_item_id is None and cid is not None:
            existing.catalog_item_id = cid
        return existing, True

    item = ListItem(
        household_id=household_id,
        store_id=store_id,
        catalog_item_id=cid,
        name=name,
        name_lower=name_lower,
        quantities=quantities.combine([], qty),
        note=(note or "").strip(),
        recipe_tags=list(dict.fromkeys(tags)),
        position=_next_position(db, household_id, store_id),
    )
    db.add(item)
    db.flush()
    return item, False


def move_item(db, item, store_id):
    """Move an item to another list, merging if that list already has it (unchecked). Returns the surviving item."""
    if item.store_id == store_id:
        return item
    if not item.checked:
        target = find_mergeable(db, item.household_id, store_id, item.name_lower, item.catalog_item_id, item.id)
        if target is not None:
            merge_into(target, item.quantities or [], item.note, item.recipe_tags or [])
            db.delete(item)
            db.flush()
            return target
    item.store_id = store_id
    item.position = _next_position(db, item.household_id, store_id)
    db.flush()
    return item


def merge_duplicate(db, item):
    """If another unchecked line on the same list is the same item, fold `item` into it."""
    if item.checked:
        return item
    db.flush()
    twin = find_mergeable(db, item.household_id, item.store_id, item.name_lower, item.catalog_item_id, item.id)
    if twin is None:
        return item
    merge_into(twin, item.quantities or [], item.note, item.recipe_tags or [])
    db.delete(item)
    db.flush()
    return twin


def set_checked(item, checked):
    item.checked = checked
    item.checked_at = utcnow() if checked else None


# ---- undo: snapshots of deleted items, restored from the client ----

def snapshot(items):
    """A compact JSON description of list items, enough to recreate them for Undo."""
    return json.dumps([
        {
            "s": store_key(i.store_id), "n": i.name, "c": i.catalog_item_id, "q": i.quantities or [],
            "o": i.note or "", "t": i.recipe_tags or [], "k": bool(i.checked), "p": i.position,
        }
        for i in items
    ], separators=(",", ":"))


def clean_qty(value):
    parts = []
    for part in value if isinstance(value, list) else []:
        if not (isinstance(part, list) and len(part) == 2 and isinstance(part[1], str)):
            continue
        try:
            amount = float(part[0])
        except (TypeError, ValueError):
            continue
        if math.isfinite(amount) and 0 < amount <= quantities.MAX_AMOUNT:
            parts.append([amount, part[1][:30]])
    return parts[:10]


def restore_snapshot(db, household_id, snap):
    """Recreate one item from snapshot(). Everything is re-validated: it came back from the browser."""
    if not isinstance(snap, dict):
        return None
    name = str(snap.get("n") or "").strip()[:100]
    if not name:
        return None
    ok, store_id = parse_store_key(db, household_id, str(snap.get("s") or NO_STORE))
    if not ok:
        store_id = None
    catalog_item = None
    cid = parse_int(snap.get("c"))
    if cid is not None:
        catalog_item = db.get(CatalogItem, cid)
        if catalog_item is None or catalog_item.household_id != household_id:
            catalog_item = None
    qty = clean_qty(snap.get("q"))
    note = str(snap.get("o") or "")[:300]
    tags = [str(t)[:150] for t in (snap.get("t") if isinstance(snap.get("t"), list) else [])][:20]
    position = parse_int(snap.get("p"))
    if not snap.get("k"):
        item, merged = add_to_list(db, household_id, store_id, name, qty, catalog_item=catalog_item, note=note, tags=tags)
        if not merged and position is not None:
            item.position = position
        return item
    item = ListItem(
        household_id=household_id, store_id=store_id,
        catalog_item_id=catalog_item.id if catalog_item else None,
        name=catalog_item.name if catalog_item else name,
        name_lower=(catalog_item.name if catalog_item else name).lower(),
        quantities=qty, note=note, recipe_tags=tags, checked=True, checked_at=utcnow(),
        position=position or 0,
    )
    db.add(item)
    db.flush()
    return item


# ---- catalog ----

def find_catalog_item(db, household_id, name):
    return (
        db.query(CatalogItem)
        .filter_by(household_id=household_id, name_lower=name.strip().lower())
        .one_or_none()
    )


def catalog_items(db, household_id):
    return (
        db.query(CatalogItem)
        .filter_by(household_id=household_id)
        .order_by(CatalogItem.name_lower)
        .all()
    )


def primary_store_id(catalog_item):
    return catalog_item.ranks[0].store_id if catalog_item and catalog_item.ranks else None


def parse_rank_ids(db, household_id, text):
    """Parse '5,2,7' into a list of store ids that belong to the household (dupes dropped)."""
    valid = {s.id for s in household_stores(db, household_id)}
    out = []
    for part in (text or "").split(","):
        sid = parse_int(part)
        if sid in valid and sid not in out:
            out.append(sid)
    return out


def set_ranks(db, catalog_item, store_ids):
    db.query(StoreRank).filter_by(catalog_item_id=catalog_item.id).delete(synchronize_session=False)
    db.flush()
    for rank, sid in enumerate(store_ids):
        db.add(StoreRank(catalog_item_id=catalog_item.id, store_id=sid, rank=rank))
    db.flush()
    db.expire(catalog_item, ["ranks"])


def create_catalog_item(db, household_id, name, store_ids=()):
    item = CatalogItem(household_id=household_id, name=name.strip(), name_lower=name.strip().lower())
    db.add(item)
    db.flush()
    if store_ids:
        set_ranks(db, item, list(store_ids))
    # Link matching free-text list items to the new catalog entry.
    for li in unlinked_list_items(db, household_id, item.name_lower):
        li.catalog_item_id = item.id
    return item


def rename_catalog_item(db, catalog_item, new_name):
    catalog_item.name = new_name
    catalog_item.name_lower = new_name.lower()
    for li in db.query(ListItem).filter_by(catalog_item_id=catalog_item.id).all():
        li.name = new_name
        li.name_lower = new_name.lower()


def unlinked_list_items(db, household_id, name_lower):
    return (
        db.query(ListItem)
        .filter_by(household_id=household_id, name_lower=name_lower, catalog_item_id=None)
        .all()
    )


def recipes_using(db, catalog_item_id):
    return (
        db.query(Recipe)
        .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
        .filter(RecipeIngredient.catalog_item_id == catalog_item_id)
        .distinct()
        .order_by(Recipe.name)
        .all()
    )


# ---- stores ----

def delete_store(db, store):
    """Unchecked items move to "Other" (merging), checked items go, rankings close up."""
    hid = store.household_id
    unchecked, checked = list_items(db, hid, store.id)
    for item in checked:
        db.delete(item)
    for item in unchecked:
        move_item(db, item, None)
    db.flush()

    affected = [r.catalog_item_id for r in db.query(StoreRank).filter_by(store_id=store.id).all()]
    db.query(StoreRank).filter_by(store_id=store.id).delete(synchronize_session=False)
    db.flush()
    for cid in affected:
        remaining = db.query(StoreRank).filter_by(catalog_item_id=cid).order_by(StoreRank.rank).all()
        for i, r in enumerate(remaining):
            r.rank = i
    db.delete(store)
    db.flush()
