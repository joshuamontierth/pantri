"""What people can do, shared by the website (routes/*.py) and the Android app's API (routes/api.py).

Both call these, so they behave the same: the same checks, the same messages, the same live
updates to other devices. A failed check raises ActionError with a message to show the person.
"""

import re

from sqlalchemy import func

from . import quantities, scan, security, services
from .events import broker
from .models import CatalogItem, Household, Invite, ListItem, Membership, Recipe, RecipeIngredient, Store, User

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class ActionError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _not_found(what):
    return ActionError(f"{what} not found", 404)


# ---------- account ----------

def signup(db, username, password, confirm):
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise ActionError("Username must be 3–32 characters: letters, numbers, dot, dash or underscore.")
    if security.find_user(db, username) is not None:
        raise ActionError("That username is taken.")
    error = security.validate_new_password(password, confirm)
    if error:
        raise ActionError(error)
    user = User(username=username, username_lower=username.lower(), password_hash=security.hash_password(password))
    db.add(user)
    db.commit()
    return user


def change_password(db, user, current, password, confirm, keep_token):
    """After an admin reset (must_change_password) the current password isn't asked for."""
    forced = user.must_change_password
    # After an admin reset, the user just logged in with the temporary password.
    if not forced and not security.verify_password(user, current):
        raise ActionError("Current password is wrong.")
    error = security.validate_new_password(password, confirm)
    if error:
        raise ActionError(error)
    if forced and security.verify_password(user, password):
        raise ActionError("Choose a password different from the temporary one.")
    user = db.merge(user)
    user.password_hash = security.hash_password(password)
    user.must_change_password = False
    db.commit()
    security.delete_other_sessions(db, user.id, keep_token=keep_token)


# ---------- households, invites, members ----------

def create_household(db, user, name):
    name = (name or "").strip()
    if not name or len(name) > 100:
        raise ActionError("Give the household a name (up to 100 characters).")
    household = Household(name=name)
    db.add(household)
    db.flush()
    db.add(Membership(household_id=household.id, user_id=user.id, role="admin"))
    db.commit()
    return household


def _own_invite(db, invite_id, user):
    invite = db.get(Invite, invite_id)
    if invite is None or invite.user_id != user.id:
        raise _not_found("Invite")
    return invite


def accept_invite(db, user, invite_id):
    invite = _own_invite(db, invite_id, user)
    hid = invite.household_id
    exists = db.query(Membership).filter_by(household_id=hid, user_id=user.id).one_or_none()
    if exists is None:
        db.add(Membership(household_id=hid, user_id=user.id, role="member"))
    db.delete(invite)
    db.commit()
    broker.publish(hid, "members")
    return hid


def decline_invite(db, user, invite_id):
    db.delete(_own_invite(db, invite_id, user))
    db.commit()


def pending_invites(db, user):
    return db.query(Invite).filter_by(user_id=user.id).order_by(Invite.created_at).all()


def rename_household(db, membership, name):
    name = (name or "").strip()
    if not name or len(name) > 100:
        raise ActionError("Name must be 1–100 characters.")
    membership.household.name = name
    db.commit()
    broker.publish(membership.household_id, "members")


def invite(db, membership, username):
    hid = membership.household_id
    target = security.find_user(db, username)
    if target is None:
        raise ActionError(f"No user named “{(username or '').strip()}”. They need to sign up first.")
    if db.query(Membership).filter_by(household_id=hid, user_id=target.id).one_or_none():
        raise ActionError(f"{target.username} is already a member.")
    if db.query(Invite).filter_by(household_id=hid, user_id=target.id).one_or_none():
        raise ActionError(f"{target.username} already has a pending invite.")
    db.add(Invite(household_id=hid, user_id=target.id, invited_by_id=membership.user_id))
    db.commit()
    return target


def cancel_invite(db, household_id, invite_id):
    invite = db.get(Invite, invite_id)
    if invite is None or invite.household_id != household_id:
        raise _not_found("Invite")
    db.delete(invite)
    db.commit()


def _target_member(db, household_id, member_id):
    target = db.get(Membership, member_id)
    if target is None or target.household_id != household_id:
        raise _not_found("Member")
    return target


def _admin_count(db, household_id):
    return db.query(Membership).filter_by(household_id=household_id, role="admin").count()


def set_role(db, household_id, member_id, role):
    if role not in ("admin", "member"):
        raise ActionError("Invalid role")
    target = _target_member(db, household_id, member_id)
    if target.role == "admin" and role == "member" and _admin_count(db, household_id) <= 1:
        raise ActionError("A household needs at least one admin. Make someone else an admin first.")
    target.role = role
    db.commit()
    broker.publish(household_id, "members")


def remove_member(db, membership, member_id):
    target = _target_member(db, membership.household_id, member_id)
    if target.user_id == membership.user_id:
        raise ActionError("To remove yourself, use “Leave household”.")
    db.delete(target)
    db.commit()
    broker.publish(membership.household_id, "members")


def reset_password(db, membership, member_id, temp_password):
    target = _target_member(db, membership.household_id, member_id)
    if target.user_id == membership.user_id:
        raise ActionError("Change your own password from your account page.")
    error = security.validate_new_password(temp_password, temp_password)
    if error:
        raise ActionError(f"Temporary password: {error}")
    target.user.password_hash = security.hash_password(temp_password)
    target.user.must_change_password = True
    db.commit()
    security.delete_other_sessions(db, target.user_id)
    return target.user


def leave(db, membership):
    hid = membership.household_id
    if db.query(Membership).filter_by(household_id=hid).count() == 1:
        raise ActionError("You're the only member. Delete the household instead.")
    if membership.is_admin and _admin_count(db, hid) <= 1:
        raise ActionError("You're the last admin. Make someone else an admin before leaving.")
    db.delete(membership)
    db.commit()
    broker.publish(hid, "members")


def delete_household(db, membership, confirm_name):
    household = membership.household
    if (confirm_name or "").strip() != household.name:
        raise ActionError("Type the household name exactly to confirm deletion.")
    hid = household.id
    db.delete(household)
    db.commit()
    broker.publish(hid, "deleted")


# ---------- stores ----------

def _store_name_error(db, household_id, name, exclude_id=None):
    if not name or len(name) > 100:
        return "Store name must be 1–100 characters."
    if name.lower() in (services.OTHER_LABEL.lower(), "no store"):
        return f"“{name}” is reserved for items without a store."
    for s in services.household_stores(db, household_id):
        if s.id != exclude_id and s.name.lower() == name.lower():
            return f"There's already a store called {s.name}."
    return None


def _get_store(db, household_id, store_id):
    store = db.get(Store, store_id)
    if store is None or store.household_id != household_id:
        raise _not_found("Store")
    return store


def add_store(db, household_id, name):
    name = (name or "").strip()
    error = _store_name_error(db, household_id, name)
    if error:
        raise ActionError(error)
    top = db.query(func.max(Store.position)).filter_by(household_id=household_id).scalar()
    store = Store(household_id=household_id, name=name, position=0 if top is None else top + 1)
    db.add(store)
    db.commit()
    broker.publish(household_id, "stores")
    return store


def rename_store(db, household_id, store_id, name):
    store = _get_store(db, household_id, store_id)
    name = (name or "").strip()
    error = _store_name_error(db, household_id, name, exclude_id=store.id)
    if error:
        raise ActionError(error)
    store.name = name
    db.commit()
    broker.publish(household_id, "stores")


def reorder_stores(db, household_id, ids):
    stores = services.household_stores(db, household_id)
    by_id = {s.id: s for s in stores}
    wanted = dict.fromkeys(services.parse_int(x) for x in ids)
    ordered = [by_id[i] for i in wanted if i in by_id]
    ordered += [s for s in stores if s not in ordered]
    for pos, store in enumerate(ordered):
        store.position = pos
    db.commit()
    broker.publish(household_id, "stores")


def delete_store(db, household_id, store_id):
    services.delete_store(db, _get_store(db, household_id, store_id))
    db.commit()
    broker.publish(household_id, "stores")


# ---------- catalog ----------

def _catalog_name_error(db, household_id, name, exclude_id=None):
    if not name or len(name) > 100:
        return "Name must be 1 to 100 characters."
    existing = services.find_catalog_item(db, household_id, name)
    if existing is not None and existing.id != exclude_id:
        return f"“{existing.name}” is already in the catalog."
    return None


def get_catalog_item(db, household_id, item_id):
    item = db.get(CatalogItem, item_id)
    if item is None or item.household_id != household_id:
        raise _not_found("Catalog item")
    return item


def rank_ids(db, household_id, ids):
    """Store ids in preference order, keeping only this household's stores."""
    return services.parse_rank_ids(db, household_id, ",".join(str(i) for i in ids or []))


def create_catalog_item(db, household_id, name, ranks):
    name = (name or "").strip()
    error = _catalog_name_error(db, household_id, name)
    if error:
        raise ActionError(error)
    item = services.create_catalog_item(db, household_id, name, rank_ids(db, household_id, ranks))
    db.commit()
    broker.publish(household_id, "catalog")
    return item


def update_catalog_item(db, household_id, item_id, name, ranks):
    item = get_catalog_item(db, household_id, item_id)
    name = (name or "").strip()
    error = _catalog_name_error(db, household_id, name, exclude_id=item.id)
    if error:
        raise ActionError(error)
    if name != item.name:
        services.rename_catalog_item(db, item, name)
    services.set_ranks(db, item, rank_ids(db, household_id, ranks))
    db.commit()
    broker.publish(household_id, "catalog")
    return item


def delete_catalog_item(db, household_id, item_id):
    item = get_catalog_item(db, household_id, item_id)
    used_by = services.recipes_using(db, item.id)
    if used_by:
        names = ", ".join(r.name for r in used_by)
        raise ActionError(f"Can't delete: used by {names}. Remove it from those recipes first.")
    db.delete(item)
    db.commit()
    broker.publish(household_id, "catalog")


# ---------- recipes ----------

def copy_recipe(db, membership, recipe_id, target_household_id):
    """Copy into another household you're in. Ingredients match that household's catalog by name."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.household_id != membership.household_id:
        raise _not_found("Recipe")
    target = db.query(Membership).filter_by(household_id=target_household_id, user_id=membership.user_id).one_or_none()
    if target is None or target_household_id == membership.household_id:
        raise _not_found("Household")
    copy = Recipe(household_id=target_household_id, name=recipe.name, directions=recipe.directions, source_url=recipe.source_url)
    db.add(copy)
    db.flush()
    for ing in recipe.ingredients:
        item = services.find_catalog_item(db, target_household_id, ing.catalog_item.name)
        if item is None:
            item = services.create_catalog_item(db, target_household_id, ing.catalog_item.name)
        db.add(RecipeIngredient(recipe_id=copy.id, catalog_item_id=item.id, amount=ing.amount, unit=ing.unit, position=ing.position))
    db.commit()
    broker.publish(target_household_id, "recipes")
    return copy


# ---------- a shopping list read from photos or pasted text ----------

def scanned_list(db, household_id, found):
    """What the list reader found, as rows to check before adding:
    [{name, qty, read_as, catalog_id, ranks, store, on_list}].

    Items in the catalog take its name, and their usual store is suggested (or else the list
    they're already on). Something written twice becomes one row. read_as is how it was written,
    when that doesn't show the name.
    """
    stores = {s.id: s.name for s in services.household_stores(db, household_id)}
    match = services.catalog_matcher(services.catalog_items(db, household_id))
    unchecked = db.query(ListItem).filter_by(household_id=household_id, checked=False).all()
    rows = {}
    for ing in found:
        amount, unit = scan.clean_amount(ing["amount"], ing["unit"])
        try:
            parts = quantities.parse_quantity(f"{amount} {unit}") if amount else []
        except ValueError:
            parts = []
        known = match(ing["item"])
        name = known.name if known else ing["item"][:1].upper() + ing["item"][1:]
        key = ("c", known.id) if known else ("n", services.name_key(name))
        if key in rows:
            rows[key]["parts"] = quantities.combine(rows[key]["parts"], parts)
            continue
        line = ing.get("line") or ""
        ranks = [sid for sid in (known.ranked_store_ids if known else []) if sid in stores]
        on_list = [
            i for i in unchecked
            if (known is not None and i.catalog_item_id == known.id) or services.name_key(i.name) == services.name_key(name)
        ]
        rows[key] = {
            "name": name,
            "parts": parts,
            "read_as": line if line and name.lower() not in line.lower() else "",
            "catalog_id": known.id if known else None,
            "ranks": ranks,
            # Its usual store; failing that, the list it's already on.
            "store": ranks[0] if ranks else next((i.store_id for i in on_list if i.store_id in stores), None),
            "on_list": [
                stores.get(i.store_id, services.OTHER_LABEL)
                + (f": {quantities.format_quantity(i.quantities)}" if i.quantities else "")
                for i in on_list
            ],
        }
    out = list(rows.values())
    for row in out:
        row["qty"] = quantities.quantity_input_text(row.pop("parts"))
    return out


def scanned_notice(rows, source):
    n = len(rows)
    new = sum(1 for r in rows if r["catalog_id"] is None)
    text = f"Read {n} item{'s' if n != 1 else ''} from {source}."
    if new:
        text += f" {new} {'is' if new == 1 else 'are'} new to your catalog."
    return text + " Check the stores, then add them."


def add_scanned(db, household_id, rows, save_new):
    """Add the rows someone kept ([{name, qty, store}]) to the lists.

    With save_new, things that aren't in the catalog yet join it, at the store they went to.
    Returns (how many, the first one's store id).
    """
    rows = [dict(r, name=(r.get("name") or "").strip(), qty=(r.get("qty") or "").strip()) for r in rows]
    rows = [r for r in rows if r["name"]]
    if not rows:
        raise ActionError("Check the items you want to add.")
    for r in rows:
        if len(r["name"]) > 100:
            raise ActionError(f"Item names can be up to 100 characters: {r['name'][:30]}…")
        if len(r["qty"]) > 100:
            raise ActionError(f"The amount for {r['name']} is too long.")
    stores = {s.id for s in services.household_stores(db, household_id)}
    match = services.catalog_matcher(services.catalog_items(db, household_id))
    created = {}
    keys = []
    for r in rows:
        store_id = r.get("store") if r.get("store") in stores else None
        item = match(r["name"]) or created.get(services.name_key(r["name"]))
        if item is None and save_new:
            item = services.create_catalog_item(db, household_id, r["name"], [store_id] if store_id else [])
            created[services.name_key(r["name"])] = item
        try:
            parts, note = quantities.parse_quantity(r["qty"]), ""
        except ValueError:
            parts, note = [], r["qty"]  # like the lists: an amount we can't read is kept as a note
        services.add_to_list(db, household_id, store_id, r["name"], parts, catalog_item=item, note=note)
        keys.append(services.store_key(store_id))
    db.commit()
    broker.publish(household_id, "lists", stores=list(dict.fromkeys(keys)))
    if created:
        broker.publish(household_id, "catalog")
    first = keys[0]
    return len(rows), None if first == services.NO_STORE else int(first)
