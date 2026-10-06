from app import db, models


def session():
    return db.SessionLocal()


def items(hid, store_id="any"):
    with session() as s:
        q = s.query(models.ListItem).filter_by(household_id=hid)
        if store_id != "any":
            q = q.filter(models.ListItem.store_id.is_(None)) if store_id is None else q.filter_by(store_id=store_id)
        return q.order_by(models.ListItem.id).all()


def test_signup_login_logout(make_user):
    alice = make_user("alice")
    assert alice.get("/").status_code in (200, 303)
    r = alice.post("/logout")
    assert r.status_code == 303
    assert alice.get("/households").status_code == 303  # back to login

    r = alice.client.post("/login", data={"username": "ALICE", "password": "wrong-password"})
    assert r.status_code == 400
    r = alice.client.post("/login", data={"username": "ALICE", "password": "password123"})
    assert r.status_code == 303
    assert alice.get("/households").status_code == 200


def test_duplicate_username_rejected(make_user):
    make_user("bob")
    from fastapi.testclient import TestClient
    from app.main import app

    c = TestClient(app, follow_redirects=False)
    r = c.post("/signup", data={"username": "Bob", "password": "password123", "confirm": "password123"})
    assert r.status_code == 400 and "taken" in r.text


def test_csrf_required(make_user):
    alice = make_user("alice")
    r = alice.client.post("/households", data={"name": "Home"})
    assert r.status_code == 403


def test_quick_add_merge_check_and_clear(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    costco = alice.add_store(hid, "Costco")

    r = alice.post(f"/h/{hid}/items", {"name": "Eggs", "qty": "12", "target": str(costco)}, htmx=True)
    assert r.status_code == 200 and "panel-%d" % costco in r.text
    alice.post(f"/h/{hid}/items", {"name": "eggs", "qty": "6", "target": str(costco)}, htmx=True)
    (eggs,) = items(hid, costco)
    assert eggs.quantities == [[18.0, ""]]

    # Unknown + auto -> Other, with an offer to save to the catalog.
    r = alice.post(f"/h/{hid}/items", {"name": "Paper towels", "qty": "", "target": "auto"}, htmx=True)
    assert "Save to catalog" in r.text
    assert [i.name for i in items(hid, None)] == ["Paper towels"]

    # Unparseable quantity becomes a note.
    alice.post(f"/h/{hid}/items", {"name": "Bananas", "qty": "a big bunch", "target": str(costco)}, htmx=True)
    bananas = [i for i in items(hid, costco) if i.name == "Bananas"][0]
    assert bananas.note == "a big bunch" and bananas.quantities == []

    alice.post(f"/h/{hid}/items/{eggs.id}/toggle", htmx=True)
    assert [i.checked for i in items(hid, costco) if i.name == "Eggs"] == [True]

    # Adding eggs while the old line is checked creates a new line.
    alice.post(f"/h/{hid}/items", {"name": "Eggs", "qty": "", "target": str(costco)}, htmx=True)
    assert len([i for i in items(hid, costco) if i.name_lower == "eggs"]) == 2

    alice.post(f"/h/{hid}/lists/{costco}/clear-checked", htmx=True)
    assert sorted(i.name for i in items(hid, costco)) == ["Bananas", "Eggs"]


def test_edit_move_reorder(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    a = alice.add_store(hid, "A")
    b = alice.add_store(hid, "B")
    for name in ("Milk", "Bread", "Jam"):
        alice.post(f"/h/{hid}/items", {"name": name, "target": str(a)}, htmx=True)
    alice.post(f"/h/{hid}/items", {"name": "Milk", "qty": "1 gal", "target": str(b)}, htmx=True)
    milk_a, bread, jam = items(hid, a)

    r = alice.post(f"/h/{hid}/lists/{a}/reorder", {"item": [str(jam.id), str(milk_a.id), str(bread.id)]}, htmx=True)
    assert r.status_code == 200
    assert [i.name for i in sorted(items(hid, a), key=lambda i: i.position)] == ["Jam", "Milk", "Bread"]

    # Moving Milk to B merges into B's Milk line.
    r = alice.post(f"/h/{hid}/items/{milk_a.id}", {"name": "Milk", "qty": "2 gal", "note": "2%", "store": str(b)}, htmx=True)
    assert r.status_code == 200, r.text
    (milk_b,) = items(hid, b)
    assert milk_b.quantities == [[3.0, "gal"]] and milk_b.note == "2%"

    r = alice.post(f"/h/{hid}/items/{bread.id}", {"name": "Bread", "qty": "lots of", "store": str(a)}, htmx=True)
    assert r.status_code == 400


def test_recipe_to_lists_flow(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    costco = alice.add_store(hid, "Costco")
    walmart = alice.add_store(hid, "Walmart")

    r = alice.post(f"/h/{hid}/recipes", {
        "name": "Pancakes", "ing_name": ["Flour", "Eggs", "Milk", ""],
        "ing_amount": ["2", "2", "1 1/2", ""],
        "ing_unit": ["cups", "", "cup", ""],
        "ing_ranks": [f"{costco},{walmart}", f"{costco}", "", ""],
        "ing_ranks_dirty": ["0", "0", "0", "0"],
    })
    assert r.status_code == 303, r.text
    pancakes = int(r.headers["location"].rsplit("/", 1)[1])

    r = alice.post(f"/h/{hid}/recipes", {
        "name": "Quiche", "ing_name": ["eggs", "Flour", "Cheese"],
        "ing_amount": ["4", "4 tbsp", "8"],
        "ing_unit": ["", "", "oz"],
        "ing_ranks": ["", "", f"{walmart}"],
        "ing_ranks_dirty": ["0", "0", "0"],
    })
    assert r.status_code == 303, r.text
    quiche = int(r.headers["location"].rsplit("/", 1)[1])

    with session() as s:
        assert s.query(models.CatalogItem).filter_by(household_id=hid).count() == 4
        flour = s.query(models.CatalogItem).filter_by(name_lower="flour").one()
        assert flour.ranked_store_ids == [costco, walmart]
        eggs_id = s.query(models.CatalogItem).filter_by(name_lower="eggs").one().id
        cheese_id = s.query(models.CatalogItem).filter_by(name_lower="cheese").one().id
        milk_id = s.query(models.CatalogItem).filter_by(name_lower="milk").one().id

    # The picker page carries the household for plan.js (which works offline): recipes with their
    # amounts, and each item's store ranking.
    import json
    import re
    page = alice.get(f"/h/{hid}/plan").text
    assert "/static/js/plan.js?v=" in page and "data-plan-page" in page
    state = json.loads(re.search(r'id="initial-state"[^>]*>(.*?)</script>', page, re.S).group(1))
    by_name = {r["name"]: r for r in state["recipes"]}
    assert [(i["name"], i["amount"], i["unit"]) for i in by_name["Quiche"]["ingredients"]] == [
        ("Eggs", 4.0, ""), ("Flour", 4.0, "tbsp"), ("Cheese", 8.0, "oz")]
    assert next(c for c in state["catalog"] if c["name"] == "Flour")["ranks"] == [costco, walmart]
    # Old links to the picker land on the new page with their selection.
    r = alice.get(f"/h/{hid}/plan/pick?r={pancakes}&r={quiche}&m_{pancakes}=2")
    assert r.status_code == 303 and r.headers["location"] == f"/h/{hid}/plan#step=pick&r={pancakes}&r={quiche}&m_{pancakes}=2"

    # Eggs already on the Costco list -> merge.
    alice.post(f"/h/{hid}/items", {"name": "Eggs", "qty": "12", "target": str(costco)}, htmx=True)

    # What plan.js queues for Pancakes x2 + Quiche, with Flour sent to its 2nd store and Milk left out.
    ops = [
        {"op_id": "p1", "type": "add", "ref": "a", "name": "Flour", "parts": [[4.25, "cup"]], "store": walmart, "tags": ["Pancakes", "Quiche"]},
        {"op_id": "p2", "type": "add", "ref": "b", "name": "Eggs", "parts": [[8, ""]], "store": costco, "tags": ["Pancakes", "Quiche"]},
        {"op_id": "p3", "type": "add", "ref": "c", "name": "Cheese", "parts": [[8, "oz"]], "store": walmart, "tags": ["Quiche"]},
    ]
    r = alice.client.post(f"/api/v1/h/{hid}/ops", json={"ops": ops}, headers={"X-CSRF-Token": alice.csrf})
    assert r.status_code == 200 and [x["status"] for x in r.json()["results"]] == ["ok"] * 3

    costco_items = {i.name: i for i in items(hid, costco)}
    walmart_items = {i.name: i for i in items(hid, walmart)}
    assert costco_items["Eggs"].quantities == [[12 + 4 + 4, ""]]  # 12 + 2x2 + 4
    assert costco_items["Eggs"].recipe_tags == ["Pancakes", "Quiche"]
    assert costco_items["Eggs"].catalog_item_id == eggs_id
    assert round(walmart_items["Flour"].quantities[0][0], 4) == 4.25
    assert walmart_items["Cheese"].quantities == [[8.0, "oz"]]
    assert "Milk" not in costco_items and not items(hid, None)
    assert milk_id and cheese_id


def test_recipe_validation_errors(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    r = alice.post(f"/h/{hid}/recipes", {
        "name": "Bad", "ing_name": ["Salt"], "ing_amount": ["pinch"], "ing_unit": ["oz"],
        "ing_ranks": [""], "ing_ranks_dirty": ["0"],
    })
    assert r.status_code == 400
    assert "Couldn" in r.text
    assert 'value="Salt"' in r.text  # form re-filled


def test_catalog_delete_blocked_when_used(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    alice.post(f"/h/{hid}/recipes", {
        "name": "Salad", "ing_name": ["Lettuce"], "ing_amount": [""], "ing_unit": [""],
        "ing_ranks": [""], "ing_ranks_dirty": ["0"],
    })
    with session() as s:
        cid = s.query(models.CatalogItem).one().id
    r = alice.post(f"/h/{hid}/catalog/{cid}/delete")
    assert r.status_code == 400 and "used by Salad" in r.text


def test_store_delete_moves_items_and_shifts_ranks(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    a = alice.add_store(hid, "A")
    b = alice.add_store(hid, "B")
    c = alice.add_store(hid, "C")
    r = alice.post(f"/h/{hid}/catalog", {"name": "Rice", "ranks": f"{a},{b},{c}"})
    assert r.status_code == 303
    alice.post(f"/h/{hid}/items", {"name": "Rice", "qty": "2 lb", "target": str(a)}, htmx=True)
    alice.post(f"/h/{hid}/items", {"name": "Rice", "qty": "1 lb", "target": "none"}, htmx=True)
    alice.post(f"/h/{hid}/items", {"name": "Old", "target": str(a)}, htmx=True)
    old = [i for i in items(hid, a) if i.name == "Old"][0]
    alice.post(f"/h/{hid}/items/{old.id}/toggle", htmx=True)

    r = alice.post(f"/h/{hid}/stores/{a}/delete")
    assert r.status_code == 303
    nostore = items(hid, None)
    assert [(i.name, i.quantities) for i in nostore] == [("Rice", [[3.0, "lb"]])]
    with session() as s:
        rice = s.query(models.CatalogItem).one()
        assert [(r.store_id, r.rank) for r in rice.ranks] == [(b, 0), (c, 1)]


def test_household_sharing_roles_and_reset(make_user):
    alice = make_user("alice")
    bob = make_user("bob")
    hid = alice.create_household("Shared")

    assert bob.get(f"/h/{hid}").status_code == 404

    alice.post(f"/h/{hid}/invite", {"username": "BOB"})
    with session() as s:
        invite = s.query(models.Invite).one()
    assert "Shared" in bob.get("/households").text
    assert bob.post(f"/invites/{invite.id}/accept").status_code == 303
    assert bob.get(f"/h/{hid}").status_code == 200

    with session() as s:
        bob_m = s.query(models.Membership).filter_by(household_id=hid, user_id=s.query(models.User).filter_by(username="bob").one().id).one()
        alice_m = s.query(models.Membership).filter_by(household_id=hid, role="admin").one()

    # Members can't do admin things.
    assert bob.post(f"/h/{hid}/invite", {"username": "alice"}).status_code == 403
    # Last admin can't leave or demote themselves.
    assert alice.post(f"/h/{hid}/leave").status_code == 400
    assert alice.post(f"/h/{hid}/members/{alice_m.id}/role", {"role": "member"}).status_code == 400
    # Promote bob -> two admins; now alice can leave... but first test the reset.
    assert alice.post(f"/h/{hid}/members/{bob_m.id}/role", {"role": "admin"}).status_code == 303

    r = alice.post(f"/h/{hid}/members/{bob_m.id}/reset-password", {"temp_password": "temp-pass-1"})
    assert r.status_code == 303
    # Bob's old sessions are gone; log in with the temp password and get forced to change it.
    assert bob.get("/households").status_code == 303
    r = bob.client.post("/login", data={"username": "bob", "password": "temp-pass-1"})
    assert r.status_code == 303
    bob.csrf = bob._csrf() if bob.get("/households").status_code == 200 else None
    assert bob.get(f"/h/{hid}").headers["location"] == "/account/password"
    page = bob.get("/account/password").text
    import re
    bob.csrf = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    r = bob.post("/account/password", {"password": "new-password-9", "confirm": "new-password-9"})
    assert r.status_code == 303
    assert bob.get(f"/h/{hid}").status_code == 200

    assert alice.post(f"/h/{hid}/leave").status_code == 303
    assert alice.get(f"/h/{hid}").status_code == 404


def test_copy_recipe_between_households(make_user):
    alice = make_user("alice")
    h1 = alice.create_household("One")
    h2 = alice.create_household("Two")
    s1 = alice.add_store(h1, "Store1")
    alice.post(f"/h/{h2}/catalog", {"name": "Butter", "ranks": ""})
    alice.post(f"/h/{h1}/recipes", {
        "name": "Cookies", "ing_name": ["Butter", "Sugar"], "ing_amount": ["1", "1"],
        "ing_unit": ["cup", "cup"], "ing_ranks": [str(s1), str(s1)], "ing_ranks_dirty": ["0", "0"],
    })
    with session() as s:
        rid = s.query(models.Recipe).one().id
    r = alice.post(f"/h/{h1}/recipes/{rid}/copy", {"target_household_id": str(h2)})
    assert r.status_code == 303 and r.headers["location"].startswith(f"/h/{h2}/recipes/")
    with session() as s:
        names = sorted(c.name for c in s.query(models.CatalogItem).filter_by(household_id=h2))
        assert names == ["Butter", "Sugar"]
        copy = s.query(models.Recipe).filter_by(household_id=h2).one()
        assert [i.catalog_item.name for i in copy.ingredients] == ["Butter", "Sugar"]


def test_delete_household(make_user):
    alice = make_user("alice")
    hid = alice.create_household("Temp")
    st = alice.add_store(hid, "S")
    alice.post(f"/h/{hid}/recipes", {
        "name": "R", "ing_name": ["X"], "ing_amount": ["1"], "ing_unit": [""],
        "ing_ranks": [str(st)], "ing_ranks_dirty": ["0"],
    })
    alice.post(f"/h/{hid}/items", {"name": "X", "target": "auto"}, htmx=True)
    assert alice.post(f"/h/{hid}/delete", {"confirm_name": "nope"}).status_code == 400
    assert alice.post(f"/h/{hid}/delete", {"confirm_name": "Temp"}).status_code == 303
    with session() as s:
        assert s.query(models.Household).count() == 0
        assert s.query(models.ListItem).count() == 0
        assert s.query(models.CatalogItem).count() == 0


def test_pages_render(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    st = alice.add_store(hid, "Costco")
    alice.post(f"/h/{hid}/recipes", {
        "name": "R", "ing_name": ["X"], "ing_amount": ["1"], "ing_unit": ["cup"],
        "ing_ranks": [str(st)], "ing_ranks_dirty": ["0"],
    })
    alice.post(f"/h/{hid}/items", {"name": "X", "qty": "1 cup", "note": "", "target": "auto"}, htmx=True)
    with session() as s:
        rid = s.query(models.Recipe).one().id
        cid = s.query(models.CatalogItem).one().id
        iid = s.query(models.ListItem).one().id
    for url in [
        f"/h/{hid}", f"/h/{hid}/stores", f"/h/{hid}/catalog", f"/h/{hid}/catalog/new?name=Y",
        f"/h/{hid}/catalog/{cid}", f"/h/{hid}/recipes", f"/h/{hid}/recipes/new", f"/h/{hid}/recipes/{rid}",
        f"/h/{hid}/recipes/{rid}/edit", f"/h/{hid}/plan", f"/h/{hid}/settings",
        f"/h/{hid}/items/{iid}/edit", f"/h/{hid}/lists/refresh?stores=all", "/account", "/account/password", "/households",
    ]:
        r = alice.get(url)
        assert r.status_code == 200, (url, r.status_code, r.text[:500])
    page = alice.get(f"/h/{hid}").text
    assert "1 cup" in page and "Costco" in page


# ---- regressions from code review ----

def test_catalog_next_is_sanitized(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    page = alice.get(f"/h/{hid}/catalog/new?next=javascript:alert(1)").text
    assert "javascript:" not in page
    page = alice.get(f"/h/{hid}/catalog/new?next=//evil.example/").text
    assert "evil.example" not in page
    page = alice.get(f"/h/{hid}/catalog/new?next=/h/{hid}/recipes/1").text
    assert f'href="/h/{hid}/recipes/1"' in page


def test_huge_and_odd_quantities_dont_break_lists(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    s = alice.add_store(hid, "S")
    for qty in ("9" * 400, "2-3", "1,5 kg", "2 x 400g"):
        r = alice.post(f"/h/{hid}/items", {"name": "Thing " + qty[:5], "qty": qty, "target": str(s)}, htmx=True)
        assert r.status_code == 200
    assert all(i.quantities == [] and i.note for i in items(hid, s))
    assert alice.get(f"/h/{hid}").status_code == 200
    r = alice.post(f"/h/{hid}/recipes", {
        "name": "Big", "ing_name": ["X"], "ing_amount": ["9" * 400], "ing_unit": [""],
        "ing_ranks": ["²"], "ing_ranks_dirty": ["0"],
    })
    assert r.status_code == 400
    for url, data in [
        (f"/h/{hid}/lists/{s}/reorder", {"item": "²"}),
        (f"/h/{hid}/stores/reorder", {"store": "²"}),
        (f"/h/{hid}/catalog", {"name": "Y", "ranks": "²,1"}),
    ]:
        assert alice.post(url, data, htmx=True).status_code in (200, 303), url
    assert alice.get(f"/h/{hid}/plan/pick?r=²").status_code in (200, 303)


def test_resaving_recipe_keeps_exact_amounts(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    names = ["A", "B", "C", "D", "E", "F"]
    amounts = ["0.05", "1.3", "2.25", "0.4", "15.4", "1/3"]
    units = ["lb", "cup", "g", "cup", "ml", "cup"]
    r = alice.post(f"/h/{hid}/recipes", {
        "name": "Exact", "ing_name": names, "ing_amount": amounts, "ing_unit": units,
        "ing_ranks": [""] * 6, "ing_ranks_dirty": ["0"] * 6,
    })
    rid = int(r.headers["location"].rsplit("/", 1)[1])
    import re
    page = alice.get(f"/h/{hid}/recipes/{rid}/edit").text
    shown = re.findall(r'name="ing_amount" class="ing-amount" value="([^"]*)"', page)
    alice.post(f"/h/{hid}/recipes/{rid}", {
        "name": "Exact", "ing_name": names, "ing_amount": shown, "ing_unit": units,
        "ing_ranks": [""] * 6, "ing_ranks_dirty": ["0"] * 6,
    })
    with session() as s:
        got = [round(i.amount, 9) for i in s.query(models.Recipe).one().ingredients]
    assert got == [0.05, 1.3, 2.25, 0.4, 15.4, round(1 / 3, 9)]


def test_store_delete_keeps_order(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    a = alice.add_store(hid, "A")
    for name in ("Eggs", "Jam", "Bread", "Milk"):
        alice.post(f"/h/{hid}/items", {"name": name, "target": str(a)}, htmx=True)
    alice.post(f"/h/{hid}/stores/{a}/delete")
    moved = sorted(items(hid, None), key=lambda i: (i.position, i.id))
    assert [i.name for i in moved] == ["Eggs", "Jam", "Bread", "Milk"]


def test_rename_merges_into_existing_line(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    s = alice.add_store(hid, "S")
    alice.post(f"/h/{hid}/items", {"name": "Rice", "qty": "1 lb", "target": str(s)}, htmx=True)
    alice.post(f"/h/{hid}/items", {"name": "Beans", "qty": "2 lb", "target": str(s)}, htmx=True)
    beans = [i for i in items(hid, s) if i.name == "Beans"][0]
    alice.post(f"/h/{hid}/items/{beans.id}", {"name": "rice", "qty": "2 lb", "note": "", "store": str(s)}, htmx=True)
    (rice,) = items(hid, s)
    assert rice.quantities == [[3.0, "lb"]]


def test_session_cookie_slides(make_user):
    from datetime import timedelta

    alice = make_user("alice")
    with session() as s:
        sess = s.query(models.AuthSession).one()
        sess.expires_at = sess.expires_at - timedelta(days=30)
        s.commit()
    r = alice.get("/households")
    assert "session=" in r.headers.get("set-cookie", "")
    r = alice.get("/households")
    assert "set-cookie" not in r.headers
    r = alice.post("/logout")
    assert r.headers["set-cookie"].count("session=") == 1


def test_undo_delete_and_clear_checked(make_user):
    import json
    import re
    from html import unescape

    alice = make_user("alice")
    hid = alice.create_household()
    s = alice.add_store(hid, "S")
    alice.post(f"/h/{hid}/items", {"name": "Milk", "qty": "1 gal", "target": str(s)}, htmx=True)
    alice.post(f"/h/{hid}/items", {"name": "Bread", "target": str(s)}, htmx=True)
    milk, bread = items(hid, s)
    alice.post(f"/h/{hid}/items/{milk.id}", {"name": "Milk", "qty": "1 gal", "note": "2%", "store": str(s)}, htmx=True)

    r = alice.post(f"/h/{hid}/items/{milk.id}/delete", htmx=True)
    assert "Deleted Milk" in r.text and "Undo" in r.text
    payload = json.loads(unescape(re.search(r"hx-vals='([^']+)'", r.text).group(1)))["data"]
    assert [i.name for i in items(hid, s)] == ["Bread"]
    r = alice.post(f"/h/{hid}/restore-items", {"data": payload}, htmx=True)
    assert r.status_code == 200
    restored = [i for i in items(hid, s) if i.name == "Milk"][0]
    assert restored.quantities == [[1.0, "gal"]] and restored.note == "2%" and not restored.checked

    alice.post(f"/h/{hid}/items/{bread.id}/toggle", htmx=True)
    r = alice.post(f"/h/{hid}/lists/{s}/clear-checked", htmx=True)
    assert "Cleared 1 item" in r.text
    payload = json.loads(unescape(re.search(r"hx-vals='([^']+)'", r.text).group(1)))["data"]
    alice.post(f"/h/{hid}/restore-items", {"data": payload}, htmx=True)
    bread2 = [i for i in items(hid, s) if i.name == "Bread"][0]
    assert bread2.checked

    # Garbage and other-household references are rejected or ignored.
    assert alice.post(f"/h/{hid}/restore-items", {"data": "not json"}, htmx=True).status_code == 400
    r = alice.post(f"/h/{hid}/restore-items", {"data": json.dumps([{"n": "X", "s": "99999", "c": 99999, "q": [["inf", "cup"], [2, "cup"]]}])}, htmx=True)
    assert r.status_code == 200
    x = [i for i in items(hid, None) if i.name == "X"][0]
    assert x.catalog_item_id is None and x.quantities == [[2.0, "cup"]]


def test_other_label_and_reserved_store_name(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    page = alice.get(f"/h/{hid}").text
    assert ">Other<" in page and ">No store<" not in page
    r = alice.post(f"/h/{hid}/stores", {"name": "other"})
    assert r.status_code == 400 and "reserved" in r.text


def test_catalog_store_filter_persists(make_user):
    import re

    alice = make_user("alice")
    hid = alice.create_household()
    a = alice.add_store(hid, "A")
    b = alice.add_store(hid, "B")
    for name, ranks in [("Apples", f"{a}"), ("Bread", f"{b},{a}"), ("Celery", ""), ("Dates", ""), ("Eggs", "")]:
        alice.post(f"/h/{hid}/catalog", {"name": name, "ranks": ranks})

    def names(page):
        return re.findall(r'<span class="row-title">([^<]+)</span>', page)

    assert names(alice.get(f"/h/{hid}/catalog").text) == ["Apples", "Bread", "Celery", "Dates", "Eggs"]
    assert names(alice.get(f"/h/{hid}/catalog?store={a}").text) == ["Apples", "Bread"]
    page = alice.get(f"/h/{hid}/catalog?store=none").text
    assert names(page) == ["Celery", "Dates", "Eggs"] and ">Other<span class=\"filter-count\">3</span>" in page.replace("\n", "").replace("  ", "")

    # Remembered: coming back without ?store= keeps "Other".
    assert names(alice.get(f"/h/{hid}/catalog").text) == ["Celery", "Dates", "Eggs"]

    with session() as s:
        ids = {c.name: c.id for c in s.query(models.CatalogItem)}
    # Saving an item returns to the list, still filtered to Other; the item drops off once it has a store.
    r = alice.post(f"/h/{hid}/catalog/{ids['Celery']}", {"name": "Celery", "ranks": f"{a}"})
    assert r.headers["location"] == f"/h/{hid}/catalog"
    assert names(alice.get(r.headers["location"]).text) == ["Dates", "Eggs"]
    for n in ("Dates", "Eggs"):
        alice.post(f"/h/{hid}/catalog/{ids[n]}", {"name": n, "ranks": f"{b}"})
    assert "Every item has a store" in alice.get(f"/h/{hid}/catalog").text

    # Bad filter values fall back to All; "All" is remembered too.
    assert len(names(alice.get(f"/h/{hid}/catalog?store=9999").text)) == 5
    assert len(names(alice.get(f"/h/{hid}/catalog").text)) == 5


def test_gear_menu_and_household_switching(make_user):
    alice = make_user("alice")
    home = alice.create_household("Home")
    cabin = alice.create_household("Cabin")
    page = alice.get(f"/h/{home}").text
    assert f'class="gear" href="/h/{home}/settings"' in page and "hh-name" not in page
    settings = alice.get(f"/h/{home}/settings").text
    assert f'href="/h/{cabin}"' in settings and f'href="/h/{home}" aria-current="page"' in settings
    assert "New household or invites" in settings and "Log out" in settings


def _jpeg_bytes(w=640, h=480):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (240, 230, 220)).save(buf, "JPEG")
    return buf.getvalue()


def test_scan_recipe_prefills_editor(make_user, monkeypatch):
    from app import scan

    alice = make_user("alice")
    hid = alice.create_household()
    costco = alice.add_store(hid, "Costco")
    alice.post(f"/h/{hid}/catalog", {"name": "Salt", "ranks": str(costco)})

    seen = {}

    def fake_model(prompt, photos, schema):
        seen["photos"], seen["prompt"] = photos, prompt
        return {"name": "Guacamole", "ingredients": [
            {"item": "avocados", "amount": "3", "unit": ""},
            {"item": "salt", "amount": "1", "unit": "tsp."},
            {"item": "garlic", "amount": "4-5", "unit": "cloves"},
            {"item": "cilantro", "amount": "", "unit": ""},
        ], "directions": ["Mash the avocados.", "Stir in   the rest."]}

    monkeypatch.setattr(scan, "_ask_model", fake_model)
    r = alice.client.post(
        f"/h/{hid}/recipes/scan", data={"csrf_token": alice.csrf},
        files=[("photos", ("front.jpg", _jpeg_bytes(4000, 3000), "image/jpeg")),
               ("photos", ("back.jpg", _jpeg_bytes(), "image/jpeg"))],
    )
    assert r.status_code == 200, r.text[:500]
    assert len(seen["photos"]) == 2 and "Paprika): Salt." in seen["prompt"]
    page = r.text
    assert 'value="Guacamole"' in page and "Read from your photos" in page
    assert "Mash the avocados.\n\nStir in the rest.</textarea>" in page
    assert 'value="Avocados"' in page and 'value="Salt"' in page  # catalog spelling wins
    assert 'value="5"' in page and 'value="clove"' in page and 'value="tsp"' in page
    # Nothing saved until the user presses Save.
    with session() as s:
        assert s.query(models.Recipe).count() == 0

    # The downscaled photo is a JPEG no bigger than 1600px.
    import base64
    import io

    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(seen["photos"][0])))
    assert max(img.size) == 1600


def test_scan_recipe_errors(make_user, monkeypatch):
    from app import scan

    alice = make_user("alice")
    hid = alice.create_household()

    def down(prompt, photos, schema):
        raise scan.ScanError("Couldn't reach the recipe reader.")

    monkeypatch.setattr(scan, "_ask_model", down)
    r = alice.client.post(f"/h/{hid}/recipes/scan", data={"csrf_token": alice.csrf},
                          files=[("photos", ("a.jpg", _jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 400 and "Couldn&#39;t reach the recipe reader" in r.text

    r = alice.client.post(f"/h/{hid}/recipes/scan", data={"csrf_token": alice.csrf},
                          files=[("photos", ("a.jpg", b"not an image", "image/jpeg"))])
    assert r.status_code == 400 and "isn&#39;t a photo" in r.text

    r = alice.client.post(f"/h/{hid}/recipes/scan", data={"csrf_token": alice.csrf},
                          files=[("photos", (f"{i}.jpg", _jpeg_bytes(), "image/jpeg")) for i in range(5)])
    assert r.status_code == 400 and "up to 4 photos" in r.text

    # Without the CSRF token the upload is refused.
    r = alice.client.post(f"/h/{hid}/recipes/scan", files=[("photos", ("a.jpg", _jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 403

    # Without a model there's no photo scanning, but links can still be imported.
    monkeypatch.setattr("app.config.OLLAMA_URL", "")
    page = alice.get(f"/h/{hid}/recipes").text
    assert "data-take-photo" not in page and "scan-library" not in page
    assert "data-link-form" in page and 'name="url"' in page


def test_scanned_pinches_are_blank_and_recipe_saves(make_user, monkeypatch):
    import re
    from html import unescape

    from app import scan

    alice = make_user("alice")
    hid = alice.create_household()
    monkeypatch.setattr(scan, "_ask_model", lambda prompt, photos, schema: {"name": "Guacamole", "ingredients": [
        {"item": "avocados", "amount": "3", "unit": ""},
        {"item": "cayenne pepper", "amount": "1", "unit": "pinch"},
        {"item": "salt", "amount": "a pinch", "unit": ""},
        {"item": "pepper", "amount": "", "unit": "to taste"},
        {"item": "lime juice", "amount": "some", "unit": ""},
    ]})
    r = alice.client.post(f"/h/{hid}/recipes/scan", data={"csrf_token": alice.csrf},
                          files=[("photos", ("card.jpg", _jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 200
    page = r.text.split('id="ing-row-template"')[0]  # ignore the blank template row

    def values(field):
        return [unescape(v) for v in re.findall(rf'name="{field}"[^>]*?value="([^"]*)"', page)]

    form = {f: values(f) for f in ("ing_name", "ing_amount", "ing_unit", "ing_ranks", "ing_ranks_dirty")}
    assert form["ing_amount"] == ["3", "", "", "", ""] and form["ing_unit"] == ["", "", "", "", ""]
    r = alice.post(f"/h/{hid}/recipes", {"name": "Guacamole", **form})
    assert r.status_code == 303, r.text[:400]
    with session() as s:
        recipe = s.query(models.Recipe).one()
        assert [(i.catalog_item.name, i.amount) for i in recipe.ingredients] == [
            ("Avocados", 3.0), ("Cayenne pepper", None), ("Salt", None), ("Pepper", None), ("Lime juice", None)]


def test_scan_offers_camera_and_library(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    page = alice.get(f"/h/{hid}/recipes").text
    assert 'capture="environment"' in page and "Take a photo" in page and "Choose photos" in page and "Paste a link" in page
    assert 'id="scan-library"' in page and 'for="scan-library"' in page
    # In-app camera (used over HTTPS), with the camera app as a fallback.
    assert "data-camera" in page and "data-camera-shutter" in page and "data-camera-native" in page


def test_directions_steps():
    from app.directions import steps

    assert steps("") == []
    # One paragraph that wraps stays one step.
    assert steps("In a bowl, use a mixer on low\nspeed to combine the milk") == [
        {"n": 1, "text": "In a bowl, use a mixer on low\nspeed to combine the milk"}]
    # Numbered steps, blank-line paragraphs, headings, and "1.5 cups" isn't a step marker.
    assert steps("1. Preheat oven.\n2) Mix 1.5 cups flour\nwith sugar\n\nFor the glaze:\n\nWhisk.\n\nStep 3: Drizzle.") == [
        {"n": 1, "text": "Preheat oven."},
        {"n": 2, "text": "Mix 1.5 cups flour\nwith sugar"},
        {"heading": "For the glaze"},
        {"n": 3, "text": "Whisk."},
        {"n": 4, "text": "Drizzle."},
    ]
    # Typed one per line, each a full sentence.
    assert [s["text"] for s in steps("Boil water.\nAdd pasta.\nDrain!")] == ["Boil water.", "Add pasta.", "Drain!"]


def test_recipe_directions_and_link_saved(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    form = {"name": "Toast", "ing_name": ["Bread"], "ing_amount": ["2"], "ing_unit": [""], "ing_ranks": [""],
            "ing_ranks_dirty": ["0"], "directions": "1. Toast the bread.\r\n2. Butter it.", "source_url": "javascript:alert(1)"}
    r = alice.post(f"/h/{hid}/recipes", form)
    assert r.status_code == 400 and "recipe link should be a web address" in r.text
    assert "1. Toast the bread.\n2. Butter it.</textarea>" in r.text  # kept while fixing the error

    form["source_url"] = "www.example.com/toast#comments"
    r = alice.post(f"/h/{hid}/recipes", form)
    assert r.status_code == 303
    with session() as s:
        recipe = s.query(models.Recipe).one()
        assert recipe.directions == "1. Toast the bread.\n2. Butter it."
        assert recipe.source_url == "https://www.example.com/toast"
        rid = recipe.id
    page = alice.get(f"/h/{hid}/recipes/{rid}").text
    assert 'class="step-n" aria-hidden="true">2</span><span class="step-text">Butter it.</span>' in page
    assert 'href="https://www.example.com/toast"' in page and ">example.com<" in page
    assert "Toast the bread." in alice.get(f"/h/{hid}/recipes/{rid}/edit").text

    # Clearing them works, and copies carry them along.
    other = alice.create_household("Cabin")
    alice.post(f"/h/{hid}/recipes/{rid}/copy", {"target_household_id": str(other)})
    form.update(directions="", source_url="")
    assert alice.post(f"/h/{hid}/recipes/{rid}", form).status_code == 303
    with session() as s:
        recipe = s.get(models.Recipe, rid)
        assert recipe.directions is None and recipe.source_url is None
        copy = s.query(models.Recipe).filter_by(household_id=other).one()
        assert copy.directions.startswith("1. Toast") and copy.source_url == "https://www.example.com/toast"
    page = alice.get(f"/h/{hid}/recipes/{rid}").text
    assert "No directions yet" in page and 'class="step"' not in page


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3

    from sqlalchemy import inspect

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE recipes (id INTEGER PRIMARY KEY, household_id INTEGER, name VARCHAR(150), created_at DATETIME)")
    con.execute("INSERT INTO recipes (household_id, name) VALUES (1, 'Old')")
    con.commit()
    con.close()
    engine = db.init_engine(path)
    cols = {c["name"] for c in inspect(engine).get_columns("recipes")}
    assert {"directions", "source_url"} <= cols
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT name, directions FROM recipes").all() == [("Old", None)]


_RECIPE_PAGE = """<html><head><title>Best Chili | Example</title>
<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
  {"@type": "WebPage", "name": "Best Chili"},
  {"@type": ["Recipe"], "name": "Best Chili &amp; Cornbread",
   "recipeIngredient": ["1 lb ground beef", "2 (15 ounce) cans kidney beans, drained", "Salt to taste"],
   "recipeInstructions": [
     {"@type": "HowToSection", "name": "Chili", "itemListElement": [
       {"@type": "HowToStep", "text": "Brown the <b>beef</b>."},
       {"@type": "HowToStep", "text": "Add beans and simmer."}]},
     {"@type": "HowToStep", "text": "Serve."}]}
]}</script></head><body>Ads</body></html>"""


def test_import_link_uses_recipe_data(make_user, monkeypatch):
    from app import importer, scan

    alice = make_user("alice")
    hid = alice.create_household()
    store = alice.add_store(hid, "Costco")
    alice.post(f"/h/{hid}/catalog", {"name": "Ground beef", "ranks": str(store)})
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return url, _RECIPE_PAGE

    seen = {}

    def fake_model(prompt, images, schema):
        seen["prompt"], seen["images"], seen["schema"] = prompt, images, schema
        return {"ingredients": [{"item": "ground beef", "amount": "1", "unit": "lb"},
                                {"item": "kidney beans", "amount": "2", "unit": "can"},
                                {"item": "salt", "amount": "", "unit": ""}]}

    monkeypatch.setattr(importer, "fetch_page", fake_fetch)
    monkeypatch.setattr(scan, "_ask_model", fake_model)
    r = alice.post(f"/h/{hid}/recipes/import", {"url": "Look at this! https://www.example.com/chili/#reviews"})
    assert r.status_code == 200, r.text[:400]
    assert fetched == ["https://www.example.com/chili/"]
    assert "\n2 cans kidney beans, drained\n" in seen["prompt"] and seen["images"] is None  # bare sizes dropped
    assert "directions" not in seen["schema"]["properties"]  # steps come straight from the page
    page = r.text
    assert "Read from example.com" in page and 'value="Best Chili &amp; Cornbread"' in page
    assert 'value="Ground beef"' in page and 'value="Kidney beans"' in page
    assert "Chili:\n\nBrown the beef.\n\nAdd beans and simmer.\n\nServe.</textarea>" in page
    assert 'value="https://www.example.com/chili/"' in page
    with session() as s:
        assert s.query(models.Recipe).count() == 0

    # If the model is down, the lines are split up here instead.
    def down(prompt, images, schema):
        raise scan.ScanError("down")

    monkeypatch.setattr(scan, "_ask_model", down)
    page = alice.post(f"/h/{hid}/recipes/import", {"url": "https://www.example.com/chili/"}).text
    assert 'value="Kidney beans"' in page and 'value="Salt"' in page and 'value="can"' in page


def test_import_link_errors(make_user, monkeypatch):
    from app import importer, scan

    alice = make_user("alice")
    hid = alice.create_household()
    r = alice.post(f"/h/{hid}/recipes/import", {"url": "not a link"})
    assert r.status_code == 400 and "Paste a link to a recipe page" in r.text
    # The server never fetches local or tailnet addresses.
    for url in ("http://127.0.0.1:8000/", "http://localhost/x", "http://10.0.0.5/", "http://100.101.102.103/", "http://[::1]/"):
        r = alice.post(f"/h/{hid}/recipes/import", {"url": url})
        assert r.status_code == 400 and "private address" in r.text, url
    for url in ("file:///etc/passwd", "ftp://example.com/x"):
        assert "Paste a link to a recipe page" in alice.post(f"/h/{hid}/recipes/import", {"url": url}).text

    # A page with no recipe data falls back to reading its text with the model.
    monkeypatch.setattr(importer, "fetch_page", lambda url: (url, "<title>Nana's Pie</title><nav>Menu</nav><p>Ingredients</p><ul><li>2 apples</li></ul><p>Bake it.</p>"))
    seen = {}

    def fake_model(prompt, images, schema):
        seen["prompt"] = prompt
        return {"name": "Nana's Pie", "ingredients": [{"item": "apples", "amount": "2", "unit": ""}], "directions": ["Bake it."]}

    monkeypatch.setattr(scan, "_ask_model", fake_model)
    page = alice.post(f"/h/{hid}/recipes/import", {"url": "https://pie.example/"}).text
    assert "Page title: Nana's Pie" in seen["prompt"] and "2 apples" in seen["prompt"] and "Menu" not in seen["prompt"]
    assert "Bake it.</textarea>" in page and 'value="Apples"' in page

    monkeypatch.setattr("app.config.OLLAMA_URL", "")
    r = alice.post(f"/h/{hid}/recipes/import", {"url": "https://pie.example/"})
    assert r.status_code == 400 and "couldn&#39;t find a recipe" in r.text


def _editor_values(page, field):
    import re
    from html import unescape
    page = page.split('id="ing-row-template"')[0]
    return [unescape(v) for v in re.findall(rf'name="{field}"[^>]*?value="([^"]*)"', page)]


def test_add_details_from_photo_fills_only_gaps(make_user, monkeypatch):
    from app import scan

    alice = make_user("alice")
    hid = alice.create_household()
    form = {"name": "Guacamole", "ing_name": ["Avocados", "Lime", "Salt"], "ing_amount": ["3", "", "1"],
            "ing_unit": ["", "", "tsp"], "ing_ranks": ["", "", ""], "ing_ranks_dirty": ["0", "0", "0"]}
    assert alice.post(f"/h/{hid}/recipes", form).status_code == 303
    with session() as s:
        rid = s.query(models.Recipe).one().id
    page = alice.get(f"/h/{hid}/recipes/{rid}").text
    assert f'action="/h/{hid}/recipes/{rid}/scan"' in page and f'action="/h/{hid}/recipes/{rid}/import"' in page
    assert "Add details" in page and "No directions yet" in page

    seen = {}

    def fake_model(prompt, photos, schema):
        seen["prompt"] = prompt
        return {"name": "Best Guac Ever", "ingredients": [
            {"item": "avocado", "amount": "4", "unit": ""},   # already there with an amount: kept as 3
            {"item": "lime", "amount": "1", "unit": ""},      # there without an amount: filled in
            {"item": "red onion", "amount": "1/2", "unit": ""},
            {"item": "cilantro", "amount": "", "unit": ""},
        ], "directions": ["Mash the avocados.", "Stir in the rest."]}

    monkeypatch.setattr(scan, "_ask_model", fake_model)
    r = alice.client.post(f"/h/{hid}/recipes/{rid}/scan", data={"csrf_token": alice.csrf},
                          files=[("photos", ("card.jpg", _jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 200, r.text[:400]
    assert 'This is the recipe "Guacamole"' in seen["prompt"]
    assert "existing items" in seen["prompt"] and "Paprika): Avocados, Lime, Salt" in seen["prompt"]
    page = r.text
    assert "Added directions, 2 ingredients and 1 amount from your photo." in page
    assert _editor_values(page, "name") == ["Guacamole"]  # the name isn't touched
    assert _editor_values(page, "ing_name") == ["Avocados", "Lime", "Salt", "Red onion", "Cilantro"]
    assert _editor_values(page, "ing_amount") == ["3", "1", "1", "1/2", ""]
    assert page.count('class="fresh-tag">Added</span>') == 3  # two rows and the directions
    assert 'class="fresh-tag">Amount added</span>' in page
    assert "Mash the avocados.\n\nStir in the rest.</textarea>" in page
    with session() as s:  # nothing saved yet
        assert s.get(models.Recipe, rid).directions is None and len(s.get(models.Recipe, rid).ingredients) == 3

    # Saving the editor keeps it all.
    values = {f: _editor_values(page, f) for f in ("ing_name", "ing_amount", "ing_unit", "ing_ranks", "ing_ranks_dirty")}
    assert alice.post(f"/h/{hid}/recipes/{rid}", {"name": "Guacamole", **values,
                                                   "directions": "Mash the avocados.\n\nStir in the rest."}).status_code == 303

    # A photo of just the directions is fine here, but existing directions are never replaced.
    monkeypatch.setattr(scan, "_ask_model", lambda prompt, photos, schema: {
        "name": "", "ingredients": [], "directions": ["Something else entirely."]})
    r = alice.client.post(f"/h/{hid}/recipes/{rid}/scan", data={"csrf_token": alice.csrf},
                          files=[("photos", ("back.jpg", _jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 200 and "Nothing to add from your photo" in r.text and "Mash the avocados." in r.text

    # Errors show on the recipe's page.
    monkeypatch.setattr(scan, "_ask_model", lambda prompt, photos, schema: {"name": "", "ingredients": [], "directions": []})
    r = alice.client.post(f"/h/{hid}/recipes/{rid}/scan", data={"csrf_token": alice.csrf},
                          files=[("photos", ("blurry.jpg", _jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 400 and "find ingredients or directions" in r.text and "<h1 class=\"page-title\">Guacamole</h1>" in r.text


def test_add_details_from_link(make_user, monkeypatch):
    from app import importer, scan

    alice = make_user("alice")
    hid = alice.create_household()
    form = {"name": "Chili", "ing_name": ["Ground beef"], "ing_amount": ["1"], "ing_unit": ["lb"],
            "ing_ranks": [""], "ing_ranks_dirty": ["0"], "directions": "Cook it all."}
    alice.post(f"/h/{hid}/recipes", form)
    with session() as s:
        rid = s.query(models.Recipe).one().id
    r = alice.post(f"/h/{hid}/recipes/{rid}/import", {"url": "http://localhost/"})
    assert r.status_code == 400 and "private address" in r.text and "Chili</h1>" in r.text

    monkeypatch.setattr(importer, "fetch_page", lambda url: (url, _RECIPE_PAGE))
    monkeypatch.setattr(scan, "_ask_model", lambda prompt, images, schema: {"ingredients": [
        {"item": "ground beef", "amount": "2", "unit": "lb"}, {"item": "kidney beans", "amount": "2", "unit": "can"}]})
    page = alice.post(f"/h/{hid}/recipes/{rid}/import", {"url": "https://www.example.com/chili"}).text
    assert "Added 1 ingredient and the link from example.com." in page
    assert _editor_values(page, "ing_amount")[:1] == ["1"]  # kept
    assert 'value="https://www.example.com/chili"' in page and "Cook it all.</textarea>" in page

    # Another household's recipe can't be touched.
    bob = make_user("bob")
    bob.create_household()
    assert bob.post(f"/h/{hid}/recipes/{rid}/import", {"url": "https://www.example.com/chili"}).status_code in (403, 404)
