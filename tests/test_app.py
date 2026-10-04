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
        "name": "Pancakes", "base_servings": "4",
        "ing_name": ["Flour", "Eggs", "Milk", ""],
        "ing_amount": ["2", "2", "1 1/2", ""],
        "ing_unit": ["cups", "", "cup", ""],
        "ing_ranks": [f"{costco},{walmart}", f"{costco}", "", ""],
        "ing_ranks_dirty": ["0", "0", "0", "0"],
    })
    assert r.status_code == 303, r.text
    pancakes = int(r.headers["location"].rsplit("/", 1)[1])

    r = alice.post(f"/h/{hid}/recipes", {
        "name": "Quiche", "base_servings": "",
        "ing_name": ["eggs", "Flour", "Cheese"],
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

    # Picker page: everything unchecked, primary store preselected.
    page = alice.get(f"/h/{hid}/plan/pick?r={pancakes}&r={quiche}&m_{pancakes}=2").text
    assert "checked" not in page.split('id="plan-rows"')[1].split("sticky-actions")[0].replace("checked=", "")
    assert "Costco · 1st" in page and "Walmart · 2nd" in page

    # Eggs already on the Costco list -> merge.
    alice.post(f"/h/{hid}/items", {"name": "Eggs", "qty": "12", "target": str(costco)}, htmx=True)

    r = alice.post(f"/h/{hid}/plan/apply", {
        "r": [str(pancakes), str(quiche)], f"m_{pancakes}": "2", f"m_{quiche}": "1",
        "include": [str(flour.id), str(eggs_id), str(cheese_id)],
        f"store_{flour.id}": str(walmart),  # pick the secondary store
        f"store_{eggs_id}": str(costco),
        f"store_{cheese_id}": str(walmart),
        f"store_{milk_id}": "none",  # not included -> ignored
    })
    assert r.status_code == 303 and "added=3" in r.headers["location"]

    costco_items = {i.name: i for i in items(hid, costco)}
    walmart_items = {i.name: i for i in items(hid, walmart)}
    assert costco_items["Eggs"].quantities == [[12 + 4 + 4, ""]]  # 12 + 2x2 + 4
    assert costco_items["Eggs"].recipe_tags == ["Pancakes", "Quiche"]
    # 2x2 cups + 4 tbsp = 4.25 cups
    assert round(walmart_items["Flour"].quantities[0][0], 4) == 4.25
    assert walmart_items["Cheese"].quantities == [[8.0, "oz"]]
    assert "Milk" not in costco_items and not items(hid, None)


def test_plan_rows_fragment_preserves_choices(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    s1 = alice.add_store(hid, "S1")
    alice.post(f"/h/{hid}/recipes", {
        "name": "Toast", "base_servings": "2", "ing_name": ["Bread"], "ing_amount": ["2"], "ing_unit": ["slices"],
        "ing_ranks": [str(s1)], "ing_ranks_dirty": ["0"],
    })
    with session() as s:
        rid = s.query(models.Recipe).one().id
        bid = s.query(models.CatalogItem).one().id
    r = alice.post(f"/h/{hid}/plan/rows", {"r": str(rid), f"m_{rid}": "3", "include": str(bid), f"store_{bid}": "none"}, htmx=True)
    assert "6 slices" in r.text
    assert 'value="%d" checked' % bid in r.text
    assert '<option value="none" data-name="Other" selected>' in r.text


def test_recipe_validation_errors(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    r = alice.post(f"/h/{hid}/recipes", {
        "name": "Bad", "base_servings": "x",
        "ing_name": ["Salt"], "ing_amount": ["pinch"], "ing_unit": ["oz"],
        "ing_ranks": [""], "ing_ranks_dirty": ["0"],
    })
    assert r.status_code == 400
    assert "Servings must be a whole number" in r.text and "Couldn" in r.text
    assert 'value="Salt"' in r.text  # form re-filled


def test_catalog_delete_blocked_when_used(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    alice.post(f"/h/{hid}/recipes", {
        "name": "Salad", "base_servings": "", "ing_name": ["Lettuce"], "ing_amount": [""], "ing_unit": [""],
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
        "name": "Cookies", "base_servings": "24", "ing_name": ["Butter", "Sugar"], "ing_amount": ["1", "1"],
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
        "name": "R", "base_servings": "", "ing_name": ["X"], "ing_amount": ["1"], "ing_unit": [""],
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
        "name": "R", "base_servings": "2", "ing_name": ["X"], "ing_amount": ["1"], "ing_unit": ["cup"],
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
        f"/h/{hid}/recipes/{rid}/edit", f"/h/{hid}/plan", f"/h/{hid}/plan/pick?r={rid}", f"/h/{hid}/settings",
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
        "name": "Big", "base_servings": "²", "ing_name": ["X"], "ing_amount": ["9" * 400], "ing_unit": [""],
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
        "name": "Exact", "base_servings": "", "ing_name": names, "ing_amount": amounts, "ing_unit": units,
        "ing_ranks": [""] * 6, "ing_ranks_dirty": ["0"] * 6,
    })
    rid = int(r.headers["location"].rsplit("/", 1)[1])
    import re
    page = alice.get(f"/h/{hid}/recipes/{rid}/edit").text
    shown = re.findall(r'name="ing_amount" class="ing-amount" value="([^"]*)"', page)
    alice.post(f"/h/{hid}/recipes/{rid}", {
        "name": "Exact", "base_servings": "", "ing_name": names, "ing_amount": shown, "ing_unit": units,
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
