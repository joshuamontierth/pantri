"""The JSON API used by the Android app."""

from fastapi.testclient import TestClient

from app import db, models
from app.main import app


def session():
    return db.SessionLocal()


class App:
    """The Android app: a bearer token, no cookies."""

    def __init__(self, username, password="password123"):
        self.client = TestClient(app, follow_redirects=False)
        r = self.client.post("/api/v1/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        self.login = r.json()
        self.headers = {"Authorization": f"Bearer {self.login['token']}", "X-Client-Id": "phone-1"}

    def get(self, url, **kw):
        return self.client.get(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def ops(self, hid, *ops):
        r = self.client.post(f"/api/v1/h/{hid}/ops", json={"ops": list(ops)}, headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()


def _items(state, store_id="any"):
    return [(i["name"], i["qty"], i["checked"]) for i in state["items"] if store_id == "any" or i["store_id"] == store_id]


def test_login_and_auth(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    c = TestClient(app)
    r = c.post("/api/v1/login", json={"username": "alice", "password": "nope"})
    assert r.status_code == 401 and r.json() == {"detail": "Wrong username or password."}
    phone = App("alice")
    assert phone.login["user"]["username"] == "alice"
    assert phone.login["households"] == [{"id": hid, "name": "Home", "role": "admin"}]
    assert phone.get("/api/v1/me").json()["households"][0]["id"] == hid

    # The website's pages can use the API with their cookie, but changes need the CSRF token.
    assert alice.get("/api/v1/me").json()["user"]["username"] == "alice"
    r = alice.client.post(f"/api/v1/h/{hid}/ops", json={"ops": []})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]
    r = alice.client.post(f"/api/v1/h/{hid}/ops", json={"ops": [{"op_id": "w1", "type": "add", "name": "Tea", "store": None}]},
                          headers={"X-CSRF-Token": alice.csrf})
    assert r.status_code == 200 and r.json()["results"][0]["status"] == "ok"
    # A bad token gets JSON, not a login page.
    r = c.get(f"/api/v1/h/{hid}/state", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["detail"] == "Log in again."
    assert c.get(f"/api/v1/h/{hid}/events").status_code == 401

    # Someone else's household is invisible.
    make_user("bob")
    bob = App("bob")
    assert bob.get(f"/api/v1/h/{hid}/state").status_code == 404
    assert bob.client.post(f"/api/v1/h/{hid}/ops", json={"ops": []}, headers=bob.headers).status_code == 404

    phone.client.post("/api/v1/logout", headers=phone.headers)
    assert phone.get("/api/v1/me").status_code == 401


def test_state_snapshot(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    costco = alice.add_store(hid, "Costco")
    alice.post(f"/h/{hid}/catalog", {"name": "Eggs", "ranks": str(costco)})
    alice.post(f"/h/{hid}/items", {"name": "eggs", "qty": "12", "target": "auto"}, htmx=True)
    alice.post(f"/h/{hid}/recipes", {"name": "Omelet", "ing_name": ["Eggs"], "ing_amount": ["3"], "ing_unit": [""],
                                     "ing_ranks": [str(costco)], "ing_ranks_dirty": ["0"], "directions": "Whisk.\n\nCook."})
    phone = App("alice")
    r = phone.get(f"/api/v1/h/{hid}/state")
    state = r.json()
    assert state["household"] == {"id": hid, "name": "Home"} and state["other_label"] == "Other"
    assert state["stores"] == [{"id": costco, "name": "Costco"}]
    item = state["items"][0]
    assert (item["name"], item["store_id"], item["qty"], item["qty_text"], item["checked"]) == ("Eggs", costco, "12", "12", False)
    assert state["catalog"] == [{"id": item["catalog_id"], "name": "Eggs", "ranks": [costco]}]
    recipe = state["recipes"][0]
    assert recipe["name"] == "Omelet" and recipe["directions"] == "Whisk.\n\nCook."
    assert recipe["ingredients"] == [{"catalog_id": item["catalog_id"], "name": "Eggs", "amount": 3.0, "unit": "", "qty": "3"}]
    # Unchanged state isn't sent twice.
    assert phone.get(f"/api/v1/h/{hid}/state", headers={"If-None-Match": r.headers["ETag"]}).status_code == 304


def test_offline_ops_with_refs_and_resends(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    costco = alice.add_store(hid, "Costco")
    alice.post(f"/h/{hid}/catalog", {"name": "Milk", "ranks": str(costco)})
    phone = App("alice")

    batch = [
        {"op_id": "op1", "type": "add", "ref": "local-1", "name": "milk", "qty": "1 cup", "store": "auto"},
        {"op_id": "op2", "type": "add", "ref": "local-2", "name": "Milk", "qty": "2 tbsp", "store": costco},  # merges
        {"op_id": "op3", "type": "add", "ref": "local-3", "name": "Batteries", "qty": "a few", "store": None},
        {"op_id": "op4", "type": "check", "item": "local-3", "checked": True},
    ]
    out = phone.ops(hid, *batch)
    assert [r["status"] for r in out["results"]] == ["ok", "ok", "ok", "ok"]
    assert out["results"][0]["item_id"] == out["results"][1]["item_id"]
    assert sorted(_items(out["state"])) == [("Batteries", "", True), ("Milk", "1⅛ cups", False)]
    batteries = next(i for i in out["state"]["items"] if i["name"] == "Batteries")
    assert batteries["note"] == "a few" and batteries["store_id"] is None

    # The response was lost and the phone sends everything again: nothing is applied twice.
    again = phone.ops(hid, *batch)
    assert [r["status"] for r in again["results"]] == ["duplicate"] * 4
    assert sorted(_items(again["state"])) == sorted(_items(out["state"]))

    # A later batch can still point at an item by the phone's ref.
    out = phone.ops(hid, {"op_id": "op5", "type": "update", "item": "local-1", "name": "Milk", "qty": "1 gallon",
                          "note": "2%", "store": None})
    milk = next(i for i in out["state"]["items"] if i["name"] == "Milk")
    assert (milk["qty"], milk["note"], milk["store_id"]) == ("1 gal", "2%", None)

    # Someone deleted it on the website meanwhile: the phone's change is skipped, the rest still apply.
    alice.post(f"/h/{hid}/items/{milk['id']}/delete", htmx=True)
    out = phone.ops(
        hid,
        {"op_id": "op6", "type": "check", "item": milk["id"], "checked": True},
        {"op_id": "op7", "type": "frobnicate"},
        {"op_id": "op8", "type": "add", "name": "Bread", "store": "auto"},
    )
    assert [r["status"] for r in out["results"]] == ["skipped", "error", "ok"]
    assert out["results"][0]["message"].startswith("That item is gone")
    assert ("Bread", "", False) in _items(out["state"])


def test_ops_reorder_delete_restore_and_recipe_parts(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    store = alice.add_store(hid, "Smith's")
    phone = App("alice")
    out = phone.ops(hid, *[{"op_id": f"a{n}", "type": "add", "ref": f"r{n}", "name": n, "store": store} for n in ("A", "B", "C")])
    out = phone.ops(hid, {"op_id": "re", "type": "reorder", "store": store, "items": ["rC", "rA", "rB"]})
    order = [i["name"] for i in sorted(out["state"]["items"], key=lambda i: i["position"])]
    assert order == ["C", "A", "B"]

    item = next(i for i in out["state"]["items"] if i["name"] == "A")
    out = phone.ops(hid, {"op_id": "del", "type": "delete", "item": item["id"]})
    assert "A" not in [i["name"] for i in out["state"]["items"]]
    snap = {"s": str(store), "n": "A", "q": [], "o": "", "t": [], "k": False, "p": item["position"]}
    out = phone.ops(hid, {"op_id": "undo", "type": "restore", "items": [snap]})
    assert "A" in [i["name"] for i in out["state"]["items"]]

    # Ingredients from a recipe come as exact parts, with the recipe as a tag.
    out = phone.ops(hid, {"op_id": "p1", "type": "add", "name": "Flour", "parts": [[1.5, "cup"], [2, "tbsp"]],
                          "tags": ["Pancakes"], "store": store})
    flour = next(i for i in out["state"]["items"] if i["name"] == "Flour")
    assert flour["qty"] == "1⅝ cups" and flour["tags"] == ["Pancakes"]

    # A store deleted while the phone was offline: its additions land on Other.
    alice.post(f"/h/{hid}/stores/{store}/delete")
    out = phone.ops(hid, {"op_id": "late", "type": "add", "name": "Jam", "store": store})
    assert next(i for i in out["state"]["items"] if i["name"] == "Jam")["store_id"] is None


def test_ops_tell_the_website(make_user):
    from app.events import broker

    alice = make_user("alice")
    hid = alice.create_household()
    sent = []
    original = broker.publish
    broker.publish = lambda household_id, kind, origin=None, **data: sent.append((household_id, kind, origin, data))
    try:
        App("alice").ops(hid, {"op_id": "x", "type": "add", "name": "Soap", "store": None})
        alice.post(f"/h/{hid}/recipes", {"name": "Toast", "ing_name": ["Bread"], "ing_amount": [""], "ing_unit": [""],
                                         "ing_ranks": [""], "ing_ranks_dirty": ["0"]})
    finally:
        broker.publish = original
    assert (hid, "lists", "phone-1", {"stores": ["none"]}) in sent
    assert (hid, "recipes", None, {}) in sent


def test_household_with_sync_records_can_be_deleted(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    App("alice").ops(hid, {"op_id": "x", "type": "add", "ref": "r", "name": "Soap", "store": None})
    r = alice.post(f"/h/{hid}/delete", {"confirm_name": "Home"})
    assert r.status_code == 303
    with session() as s:
        assert s.query(models.SyncOp).count() == 0


def test_forced_password_change_in_the_app(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    with session() as s:
        s.query(models.User).filter_by(username="alice").one().must_change_password = True
        s.commit()
    phone = App("alice")
    assert phone.login["must_change_password"] is True
    # Like the website: nothing else until a new password is chosen.
    r = phone.get(f"/api/v1/h/{hid}/state")
    assert r.status_code == 403 and r.json()["detail"] == "Choose a new password first."
    r = phone.client.post("/api/v1/account/password", json={"password": "password123", "confirm": "password123"}, headers=phone.headers)
    assert r.status_code == 400 and r.json()["detail"] == "Choose a password different from the temporary one."
    r = phone.client.post("/api/v1/account/password", json={"password": "brand-new-pw", "confirm": "brand-new-pw"}, headers=phone.headers)
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert phone.get(f"/api/v1/h/{hid}/state").status_code == 200


def test_android_app_download(make_user, tmp_path, monkeypatch):
    from app.routes import households

    alice = make_user("alice")
    hid = alice.create_household()
    apk = tmp_path / "Pantri.apk"
    monkeypatch.setattr(households, "ANDROID_APK", apk)
    assert "Android app" not in alice.get(f"/h/{hid}/settings").text
    assert alice.get("/android/Pantri.apk").status_code == 404
    apk.write_bytes(b"PK fake apk")
    assert "Download the app" in alice.get(f"/h/{hid}/settings").text
    r = alice.get("/android/Pantri.apk")
    assert r.status_code == 200 and r.content == b"PK fake apk"
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
    # Not for strangers.
    assert TestClient(app, follow_redirects=False).get("/android/Pantri.apk").status_code == 303


def test_offline_support_pieces(make_user):
    from app.templating import templates

    alice = make_user("alice")
    hid = alice.create_household()
    page = alice.get(f"/h/{hid}").text
    # The lists page carries the household for lists.js, and loads it.
    assert 'id="initial-state"' in page and "/static/js/lists.js?v=" in page and 'data-user="alice"' in page
    sw = TestClient(app).get("/sw.js")
    assert sw.status_code == 200 and sw.headers["content-type"].startswith("text/javascript")
    assert templates.env.globals["static_v"] in sw.text and "__VERSION__" not in sw.text
    off = TestClient(app).get("/offline")
    assert off.status_code == 200 and "You're offline" in off.text
    assert "data-anon" in TestClient(app).get("/login").text
    r = alice.post("/logout")
    assert r.headers["clear-site-data"] == '"cache", "storage"'


def _api(phone, method, url, **kw):
    return getattr(phone.client, method)(url, headers=phone.headers, **kw)


def test_account_and_households_match_the_website(make_user):
    c = TestClient(app)
    r = c.post("/api/v1/signup", json={"username": "x", "password": "password123", "confirm": "password123"})
    assert r.status_code == 400 and r.json()["detail"].startswith("Username must be 3–32 characters")
    r = c.post("/api/v1/signup", json={"username": "carol", "password": "password123", "confirm": "nope"})
    assert r.status_code == 400 and r.json()["detail"] == "Passwords don't match."
    r = c.post("/api/v1/signup", json={"username": "carol", "password": "password123", "confirm": "password123"})
    assert r.status_code == 200 and r.json()["token"] and r.json()["households"] == []
    assert c.post("/api/v1/signup", json={"username": "Carol", "password": "password123", "confirm": "password123"}).json()["detail"] == "That username is taken."
    make_user("bob")

    alice_web = make_user("alice")
    alice = App("alice")
    carol = App("carol")
    bob = App("bob")
    r = _api(alice, "post", "/api/v1/households", json={"name": ""})
    assert r.status_code == 400 and r.json()["detail"] == "Give the household a name (up to 100 characters)."
    hid = _api(alice, "post", "/api/v1/households", json={"name": "Home"}).json()["household_id"]

    # Invites: the website's checks and messages.
    assert _api(alice, "post", f"/api/v1/h/{hid}/invites", json={"username": "nobody"}).json()["detail"] == "No user named “nobody”. They need to sign up first."
    r = _api(alice, "post", f"/api/v1/h/{hid}/invites", json={"username": "carol"})
    assert r.json()["notice"] == "Invited carol" and [i["username"] for i in r.json()["invites"]] == ["carol"]
    assert _api(alice, "post", f"/api/v1/h/{hid}/invites", json={"username": "carol"}).json()["detail"] == "carol already has a pending invite."
    invite = carol.get("/api/v1/me").json()["invites"][0]
    assert invite["household"] == "Home" and invite["invited_by"] == "alice"
    r = _api(carol, "post", f"/api/v1/invites/{invite['id']}/accept")
    assert r.json()["household_id"] == hid and [h["name"] for h in r.json()["households"]] == ["Home"]
    # The website sees the same household and members.
    assert "carol" in alice_web.get(f"/h/{hid}/settings").text

    # Members: only admins manage, at least one admin, can't remove yourself.
    settings = carol.get(f"/api/v1/h/{hid}/settings").json()
    assert settings["role"] == "member" and settings["invites"] == []
    carol_member = next(m for m in settings["members"] if m["username"] == "carol")
    alice_member = next(m for m in settings["members"] if m["username"] == "alice")
    assert _api(carol, "post", f"/api/v1/h/{hid}/rename", json={"name": "Mine"}).status_code == 403
    assert _api(alice, "post", f"/api/v1/h/{hid}/members/{alice_member['id']}/role", json={"role": "member"}).json()["detail"] == \
        "A household needs at least one admin. Make someone else an admin first."
    assert _api(alice, "delete", f"/api/v1/h/{hid}/members/{alice_member['id']}").json()["detail"] == "To remove yourself, use “Leave household”."
    r = _api(alice, "post", f"/api/v1/h/{hid}/members/{carol_member['id']}/reset-password", json={"temp_password": "temp-pass-1"})
    assert r.json()["notice"] == "Password reset for carol. They must choose a new one at next login."
    assert carol.get("/api/v1/me").status_code == 401  # her sessions were ended
    assert _api(alice, "post", f"/api/v1/h/{hid}/leave").json()["detail"] == "You're the last admin. Make someone else an admin before leaving."
    assert _api(alice, "post", f"/api/v1/h/{hid}/rename", json={"name": "Our place"}).json()["household"]["name"] == "Our place"
    assert _api(alice, "post", f"/api/v1/h/{hid}/delete", json={"confirm_name": "Home"}).json()["detail"] == "Type the household name exactly to confirm deletion."
    assert bob.get(f"/api/v1/h/{hid}/settings").status_code == 404
    r = _api(alice, "post", f"/api/v1/h/{hid}/delete", json={"confirm_name": "Our place"})
    assert r.status_code == 200 and r.json()["households"] == []


def test_stores_catalog_and_recipes_match_the_website(make_user, monkeypatch):
    from test_app import _RECIPE_PAGE

    from app import importer, scan

    make_user("alice").create_household()
    alice = App("alice")
    hid = alice.login["households"][0]["id"]
    assert alice.login["features"] == {"scan": True}

    assert _api(alice, "post", f"/api/v1/h/{hid}/stores", json={"name": "Other"}).json()["detail"] == "“Other” is reserved for items without a store."
    costco = next(s["id"] for s in _api(alice, "post", f"/api/v1/h/{hid}/stores", json={"name": "Costco"}).json()["state"]["stores"])
    state = _api(alice, "post", f"/api/v1/h/{hid}/stores", json={"name": "Smith's"}).json()["state"]
    smiths = next(s["id"] for s in state["stores"] if s["name"] == "Smith's")
    assert _api(alice, "post", f"/api/v1/h/{hid}/stores", json={"name": "costco"}).json()["detail"] == "There's already a store called Costco."
    state = _api(alice, "post", f"/api/v1/h/{hid}/stores/reorder", json={"ids": [smiths, costco]}).json()["state"]
    assert [s["name"] for s in state["stores"]] == ["Smith's", "Costco"]
    state = _api(alice, "put", f"/api/v1/h/{hid}/stores/{smiths}", json={"name": "Smiths"}).json()["state"]
    assert [s["name"] for s in state["stores"]] == ["Smiths", "Costco"]

    # Catalog.
    r = _api(alice, "post", f"/api/v1/h/{hid}/catalog", json={"name": "Eggs", "ranks": [costco, 999, smiths]})
    eggs = r.json()["id"]
    assert next(c for c in r.json()["state"]["catalog"] if c["id"] == eggs)["ranks"] == [costco, smiths]
    assert _api(alice, "post", f"/api/v1/h/{hid}/catalog", json={"name": "eggs"}).json()["detail"] == "“Eggs” is already in the catalog."
    state = _api(alice, "put", f"/api/v1/h/{hid}/catalog/{eggs}", json={"name": "Large eggs", "ranks": [smiths]}).json()["state"]
    assert next(c for c in state["catalog"] if c["id"] == eggs) == {"id": eggs, "name": "Large eggs", "ranks": [smiths]}

    # Recipes: create (new items get the ranks sent; existing ones only when changed), errors, draft, update.
    body = {"name": "Omelet", "directions": "Whisk.\n\nCook.", "source_url": "example.com/omelet", "ingredients": [
        {"name": "Large eggs", "amount": "3", "unit": "", "ranks": [costco]},
        {"name": "Chives", "amount": "1", "unit": "tbsp", "ranks": [smiths]},
    ]}
    bad = dict(body, ingredients=[{"name": "Chives", "amount": "lots", "unit": ""}])
    r = _api(alice, "post", f"/api/v1/h/{hid}/recipes", json=bad)
    assert r.status_code == 400 and r.json()["errors"] == ["Couldn't read the amount for Chives: “lots ”. Use e.g. 2, 1/2, 1 1/2 or 0.75."]
    r = _api(alice, "post", f"/api/v1/h/{hid}/recipes", json=body)
    rid = r.json()["recipe_id"]
    catalog = {c["name"]: c["ranks"] for c in r.json()["state"]["catalog"]}
    assert catalog["Large eggs"] == [smiths] and catalog["Chives"] == [smiths]
    recipe = next(x for x in r.json()["state"]["recipes"] if x["id"] == rid)
    assert recipe["source_url"] == "https://example.com/omelet" and recipe["directions"] == "Whisk.\n\nCook."
    draft = alice.get(f"/api/v1/h/{hid}/recipes/{rid}/draft").json()
    assert [(i["name"], i["amount"], i["unit"]) for i in draft["ingredients"]] == [("Large eggs", "3", ""), ("Chives", "1", "tbsp")]
    body["ingredients"][0].update(ranks=[costco], ranks_changed=True)
    r = _api(alice, "put", f"/api/v1/h/{hid}/recipes/{rid}", json=body)
    assert {c["name"]: c["ranks"] for c in r.json()["state"]["catalog"]}["Large eggs"] == [costco]
    assert _api(alice, "delete", f"/api/v1/h/{hid}/catalog/{eggs}").json()["detail"] == "Can't delete: used by Omelet. Remove it from those recipes first."

    # Importing: a draft to review, or only the gaps for an existing recipe.
    monkeypatch.setattr(importer, "fetch_page", lambda url: (url, _RECIPE_PAGE))
    monkeypatch.setattr(scan, "_ask_model", lambda prompt, images, schema: {
        "name": "Chili", "ingredients": [{"item": "ground beef", "amount": "1", "unit": "lb"}], "directions": ["Brown it."]})
    draft = _api(alice, "post", f"/api/v1/h/{hid}/recipes/import", json={"url": "https://www.example.com/chili"}).json()
    assert draft["recipe_id"] is None and draft["name"] == "Best Chili & Cornbread" and draft["notice"].startswith("Read from example.com.")
    draft = _api(alice, "post", f"/api/v1/h/{hid}/recipes/scan", data={"recipe_id": str(rid)},
                 files=[("photos", ("card.jpg", _jpeg(), "image/jpeg"))]).json()
    assert draft["recipe_id"] == rid and draft["notice"] == "Added 1 ingredient from your photo. Check them, then save."
    assert draft["ingredients"][-1] == {"name": "Ground beef", "amount": "1", "unit": "lb", "ranks": [], "fresh": "Added"}
    assert draft["fresh"] == {"directions": False, "link": False}  # it already had both
    monkeypatch.setattr(scan, "_ask_model", lambda prompt, images, schema: {"name": "", "ingredients": [], "directions": ["Other."]})
    r = _api(alice, "post", f"/api/v1/h/{hid}/recipes/scan", data={"recipe_id": str(rid)}, files=[("photos", ("c.jpg", _jpeg(), "image/jpeg"))])
    assert r.json() == {"recipe_id": rid, "nothing_new": True, "notice": "Nothing to add from your photo. This recipe already has everything it found."}

    # Copy to another household, then delete.
    other = _api(alice, "post", "/api/v1/households", json={"name": "Cabin"}).json()["household_id"]
    r = _api(alice, "post", f"/api/v1/h/{hid}/recipes/{rid}/copy", json={"target_household_id": other})
    assert r.json()["household_id"] == other
    assert [x["name"] for x in alice.get(f"/api/v1/h/{other}/state").json()["recipes"]] == ["Omelet"]
    state = _api(alice, "delete", f"/api/v1/h/{hid}/recipes/{rid}").json()["state"]
    assert state["recipes"] == []
    state = _api(alice, "delete", f"/api/v1/h/{hid}/stores/{costco}").json()["state"]
    assert [s["name"] for s in state["stores"]] == ["Smiths"]


def _jpeg():
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), (200, 200, 200)).save(buf, "JPEG")
    return buf.getvalue()


def test_share_target_lands_on_recipes(make_user):
    import json

    alice = make_user("alice")
    assert alice.get("/share?text=x").headers["location"] == "/households"
    hid = alice.create_household()
    r = alice.get("/share?text=Look+https://example.com/pie&photos=2")
    assert r.status_code == 303 and r.headers["location"] == f"/h/{hid}/recipes?shared=1&text=Look+https%3A%2F%2Fexample.com%2Fpie&photos=2"
    assert alice.client.post("/share").status_code == 303  # without the service worker, still lands somewhere sensible
    assert TestClient(app, follow_redirects=False).get("/share").status_code == 303  # (to the login page)
    manifest = json.loads(TestClient(app).get("/static/manifest.json").text)
    assert manifest["share_target"]["action"] == "/share" and manifest["share_target"]["params"]["files"][0]["name"] == "photos"
    assert manifest["name"] == manifest["short_name"] == "Pantri"
    assert "<title>Log in · Pantri</title>" in TestClient(app).get("/login").text
