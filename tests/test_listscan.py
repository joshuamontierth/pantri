"""Adding from a photo of a shopping list (or one pasted in), on the website and in the app."""

import re
from html import unescape

from app import db, models, scan
from test_api import App, _api, _jpeg


def session():
    return db.SessionLocal()


def _setup(make_user):
    """alice's household: Costco and Smiths, Eggs (Costco), Bananas (Smiths, then Costco), Milk on the Costco list."""
    alice = make_user("alice")
    hid = alice.create_household()
    costco = alice.add_store(hid, "Costco")
    smiths = alice.add_store(hid, "Smiths")
    alice.post(f"/h/{hid}/catalog", {"name": "Eggs", "ranks": str(costco)})
    alice.post(f"/h/{hid}/catalog", {"name": "Banana", "ranks": f"{smiths},{costco}"})
    alice.post(f"/h/{hid}/catalog", {"name": "Milk", "ranks": str(costco)})
    alice.post(f"/h/{hid}/items", {"name": "Milk", "qty": "1 gal", "target": "auto"})
    return alice, hid, costco, smiths


_READ = {"items": [
    {"line": "eggs x2 dz", "item": "eggs", "amount": "2", "unit": "dozen"},
    {"line": "bananas", "item": "bananas", "amount": "", "unit": ""},
    {"line": "OJ", "item": "orange juice", "amount": "", "unit": ""},
    {"line": "milk", "item": "Milk", "amount": "", "unit": ""},
    {"line": "eggs", "item": "Eggs", "amount": "1", "unit": "dozen"},  # written twice: one row
    {"line": "ground beef 2-3 lb", "item": "ground beef", "amount": "2-3", "unit": "lb"},
]}


def _fake(seen):
    def model(prompt, images, schema, reader="recipe reader"):
        seen.update(prompt=prompt, images=images, schema=schema, reader=reader)
        return _READ
    return model


def _field(page, name):
    return [unescape(v) for v in re.findall(rf'name="{name}"[^>]*?value="([^"]*)"', page)]


def _selected(page, i):
    select = re.search(rf'name="store_{i}".*?</select>', page, re.S).group(0)
    return re.search(r'<option value="([^"]+)" selected', select).group(1)


def test_scan_list_on_the_website(make_user, monkeypatch):
    alice, hid, costco, smiths = _setup(make_user)
    page = alice.get(f"/h/{hid}").text
    assert 'class="qa-scan" form="import-photos" data-import-button' in page
    assert f'action="/h/{hid}/lists/scan"' in page and "Scan a shopping list" in page and "Paste a list" in page
    assert "Reading the list" in page and "Read list" in page

    seen = {}
    monkeypatch.setattr(scan, "_ask_model", _fake(seen))
    r = alice.client.post(f"/h/{hid}/lists/scan", data={"csrf_token": alice.csrf},
                          files=[("photos", ("list.jpg", _jpeg(), "image/jpeg"))])
    assert r.status_code == 200, r.text[:500]
    assert seen["reader"] == "list reader" and len(seen["images"]) == 1
    assert "shopping list" in seen["prompt"] and "Paprika): Banana, Eggs, Milk." in seen["prompt"]
    page = r.text
    assert "Read 5 items from your photo. 2 are new to your catalog." in page
    # Catalog spellings win, a plural matches, and eggs written twice add up.
    names = [_field(page, f"name_{i}")[0] for i in range(5)]
    assert names == ["Eggs", "Banana", "Orange juice", "Milk", "Ground beef"]
    assert [_field(page, f"qty_{i}")[0] for i in range(5)] == ["3 dozen", "", "", "", "3 lb"]
    # Their usual stores are picked; new things go to Other until you pick one.
    assert [_selected(page, i) for i in range(5)] == [str(costco), str(smiths), "none", str(costco), "none"]
    assert page.count('data-new hidden') == 3 and page.count('data-new>New') == 2
    assert "Written “OJ”" in page and "Already on Costco: 1 gal" in page
    # Nothing added yet.
    with session() as s:
        assert s.query(models.ListItem).count() == 1

    # Add all but the bananas, with the beef at Smiths.
    form = {"csrf_token": alice.csrf, "count": "5", "pick": ["0", "2", "3", "4"], "save_new": "1"}
    for i, name in enumerate(names):
        form[f"name_{i}"] = name
        form[f"qty_{i}"] = _field(page, f"qty_{i}")[0]
        form[f"store_{i}"] = [str(costco), str(smiths), "none", str(costco), str(smiths)][i]
    r = alice.client.post(f"/h/{hid}/lists/scan/add", data=form)
    assert r.status_code == 303 and r.headers["location"] == f"/h/{hid}#store-{costco}"
    with session() as s:
        items = {(i.name, i.store_id): i.quantities for i in s.query(models.ListItem).all()}
        assert items == {("Milk", costco): [[1.0, "gal"]], ("Eggs", costco): [[3.0, "dozen"]],
                         ("Orange juice", None): [], ("Ground beef", smiths): [[3.0, "lb"]]}
        # New things joined the catalog, at the store they went to.
        catalog = {c.name: c.ranked_store_ids for c in s.query(models.CatalogItem).all()}
        assert catalog["Ground beef"] == [smiths] and catalog["Orange juice"] == []
        assert s.query(models.ListItem).filter_by(name="Ground beef").one().catalog_item_id is not None


def test_scan_list_website_errors_and_choices(make_user, monkeypatch):
    alice, hid, costco, smiths = _setup(make_user)

    def down(prompt, images, schema, reader="recipe reader"):
        raise scan.ScanError(f"Couldn't reach the {reader}.")

    monkeypatch.setattr(scan, "_ask_model", down)
    r = alice.client.post(f"/h/{hid}/lists/scan", data={"csrf_token": alice.csrf, "text": "milk\neggs"})
    assert r.status_code == 400 and "Couldn&#39;t reach the list reader." in r.text and "Try again" in r.text

    # Pasted text goes to the model as text; nothing found is an error.
    seen = {}
    monkeypatch.setattr(scan, "_ask_model", lambda prompt, images, schema, reader="": seen.update(prompt=prompt, images=images) or {"items": []})
    r = alice.client.post(f"/h/{hid}/lists/scan", data={"csrf_token": alice.csrf, "text": "milk\neggs x2"})
    assert r.status_code == 400 and "find anything to buy" in r.text
    assert seen["images"] is None and seen["prompt"].endswith("List:\nmilk\neggs x2")
    r = alice.client.post(f"/h/{hid}/lists/scan", data={"csrf_token": alice.csrf, "text": "  "})
    assert r.status_code == 400 and "Take or choose a photo of your list, or paste it in." in r.text
    assert alice.client.post(f"/h/{hid}/lists/scan", data={"text": "milk"}).status_code == 403  # CSRF

    # Without "Save new items to the catalog", new things go on the list only.
    form = {"csrf_token": alice.csrf, "count": "2", "pick": ["0", "1"],
            "name_0": "Kale", "qty_0": "2 bunches", "store_0": str(smiths),
            "name_1": "bananas", "qty_1": "a few", "store_1": "none"}
    r = alice.client.post(f"/h/{hid}/lists/scan/add", data=form)
    assert r.status_code == 303 and r.headers["location"] == f"/h/{hid}#store-{smiths}"
    with session() as s:
        assert s.query(models.CatalogItem).filter_by(name="Kale").count() == 0
        kale = s.query(models.ListItem).filter_by(name="Kale").one()
        assert kale.quantities == [[2.0, "bunch"]] and kale.catalog_item_id is None
        banana = s.query(models.ListItem).filter_by(name="Banana").one()  # matched to the catalog's name
        assert banana.store_id is None and banana.note == "a few" and banana.catalog_item_id is not None

    # Nothing checked: the page comes back with the message and the rows as they were.
    r = alice.client.post(f"/h/{hid}/lists/scan/add", data={"csrf_token": alice.csrf, "count": "1", "name_0": "Kale", "qty_0": "", "store_0": str(smiths)})
    assert r.status_code == 400 and "Check the items you want to add." in r.text and 'value="Kale"' in r.text

    # No model: no scan button.
    monkeypatch.setattr("app.config.OLLAMA_URL", "")
    page = alice.get(f"/h/{hid}").text
    assert "qa-scan" not in page and "import-photos" not in page
    assert alice.client.post(f"/h/{hid}/lists/scan", data={"csrf_token": alice.csrf, "text": "milk"}).status_code == 404


def test_scan_list_in_the_app(make_user, monkeypatch):
    alice, hid, costco, smiths = _setup(make_user)
    phone = App("alice")
    alice.post(f"/h/{hid}/items", {"name": "orange juice", "qty": "", "target": str(smiths)})  # not in the catalog
    monkeypatch.setattr(scan, "_ask_model", _fake({}))
    r = _api(phone, "post", f"/api/v1/h/{hid}/lists/scan", files=[("photos", ("list.jpg", _jpeg(), "image/jpeg"))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["notice"] == "Read 5 items from your photo. 2 are new to your catalog. Check the stores, then add them."
    rows = body["items"]
    assert [(x["name"], x["qty"], x["store"], x["catalog_id"] is None) for x in rows] == [
        ("Eggs", "3 dozen", costco, False), ("Banana", "", smiths, False), ("Orange juice", "", smiths, True),
        ("Milk", "", costco, False), ("Ground beef", "3 lb", None, True)]
    assert rows[1]["ranks"] == [smiths, costco] and rows[2]["read_as"] == "OJ" and rows[3]["on_list"] == ["Costco: 1 gal"]
    assert rows[2]["on_list"] == ["Smiths"]  # not in the catalog, but already on Smiths' list: that's the suggestion

    # Pasted text works the same way.
    r = _api(phone, "post", f"/api/v1/h/{hid}/lists/scan", data={"text": "eggs\nbananas"})
    assert r.status_code == 200 and r.json()["notice"].startswith("Read 5 items from your list.")

    r = _api(phone, "post", f"/api/v1/h/{hid}/lists/add", json={"items": [
        {"name": "Eggs", "qty": "3 dozen", "store": costco},
        {"name": "Ground beef", "qty": "3 lb", "store": smiths},
        {"name": "Orange juice", "qty": "2", "store": smiths},
    ], "save_new": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == 3 and body["store_id"] == costco
    assert sorted((i["name"], i["qty"], i["store_id"]) for i in body["state"]["items"]) == [
        ("Eggs", "3 dozen", costco), ("Ground beef", "3 lb", smiths), ("Milk", "1 gal", costco), ("orange juice", "2", smiths)]
    catalog = {c["name"]: c["ranks"] for c in body["state"]["catalog"]}
    assert catalog["Ground beef"] == [smiths] and catalog["Orange juice"] == [smiths]
    # The list's free-text "orange juice" merged with it and now points at the new catalog entry.
    oj = [i for i in body["state"]["items"] if i["name"].lower() == "orange juice"]
    assert len(oj) == 1 and oj[0]["catalog_id"] is not None

    # The website's messages.
    r = _api(phone, "post", f"/api/v1/h/{hid}/lists/add", json={"items": [], "save_new": True})
    assert r.status_code == 400 and r.json()["detail"] == "Check the items you want to add."
    r = _api(phone, "post", f"/api/v1/h/{hid}/lists/add", json={"items": [{"name": "x" * 101}]})
    assert r.status_code == 400 and r.json()["detail"].startswith("Item names can be up to 100 characters")
    monkeypatch.setattr(scan, "_ask_model", lambda *a, **k: (_ for _ in ()).throw(scan.ScanError("Couldn't reach the list reader.")))
    r = _api(phone, "post", f"/api/v1/h/{hid}/lists/scan", data={"text": "milk"})
    assert r.status_code == 400 and r.json()["detail"] == "Couldn't reach the list reader."


def test_recipe_page_has_one_way_to_add_details(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    form = {"name": "Toast", "ing_name": ["Bread"], "ing_amount": ["2"], "ing_unit": ["slice"], "ing_ranks": [""], "ing_ranks_dirty": ["0"]}
    assert alice.post(f"/h/{hid}/recipes", form).status_code == 303
    with session() as s:
        rid = s.query(models.Recipe).one().id
    page = alice.get(f"/h/{hid}/recipes/{rid}").text
    assert "No directions yet. Use Add details" in page and "Add directions" not in page
    assert page.count("data-import-button") == 1
