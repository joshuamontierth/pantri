"""Merging catalog items, and going through possible duplicates, on the website and in the app."""

import json
import re
from html import unescape

from app import db, models, scan
from test_api import App, _api


def session():
    return db.SessionLocal()


def _ids(hid):
    with session() as s:
        return {c.name: c.id for c in s.query(models.CatalogItem).filter_by(household_id=hid)}


def _recipe(user, hid, name, rows):
    form = {"name": name, "ing_name": [r[0] for r in rows], "ing_amount": [r[1] for r in rows], "ing_unit": [r[2] for r in rows],
            "ing_ranks": [""] * len(rows), "ing_ranks_dirty": ["0"] * len(rows)}
    assert user.post(f"/h/{hid}/recipes", form).status_code == 303, name


def _setup(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    costco, smiths = alice.add_store(hid, "Costco"), alice.add_store(hid, "Smiths")
    alice.post(f"/h/{hid}/catalog", {"name": "Avocado", "ranks": str(costco)})
    alice.post(f"/h/{hid}/catalog", {"name": "Avocados", "ranks": str(smiths)})
    _recipe(alice, hid, "Guac", [("Avocado", "2", ""), ("Avocados", "1", ""), ("Lime", "1", "")])
    _recipe(alice, hid, "Toast", [("Avocados", "", ""), ("Bread", "2", "slice")])
    alice.post(f"/h/{hid}/items", {"name": "Avocado", "qty": "1", "target": str(costco)})
    alice.post(f"/h/{hid}/items", {"name": "Avocados", "qty": "2", "target": str(costco)})
    return alice, hid, costco, smiths


def test_merge_items(make_user):
    alice, hid, costco, smiths = _setup(make_user)
    ids = _ids(hid)
    page = alice.get(f"/h/{hid}/catalog/{ids['Avocado']}").text
    assert "Merge with another item" in page and f'<option value="{ids["Avocados"]}">Avocados</option>' in page

    # Keep "Avocados": Avocado goes, and everything that used it uses Avocados.
    r = alice.post(f"/h/{hid}/catalog/{ids['Avocado']}/merge", {"with": str(ids["Avocados"]), "keep": "other"})
    assert r.status_code == 303 and r.headers["location"] == f"/h/{hid}/catalog/{ids['Avocados']}?merged=1"
    assert "Merged. Recipes and lists that used the other item use this one now." in alice.get(r.headers["location"]).text
    with session() as s:
        assert s.get(models.CatalogItem, ids["Avocado"]) is None
        kept = s.get(models.CatalogItem, ids["Avocados"])
        assert kept.ranked_store_ids == [smiths, costco]  # its own stores first
        guac = s.query(models.Recipe).filter_by(name="Guac").one()
        assert [(i.catalog_item.name, i.amount) for i in guac.ingredients] == [("Avocados", 3.0), ("Lime", 1.0)]
        toast = s.query(models.Recipe).filter_by(name="Toast").one()
        assert [(i.catalog_item.name, i.amount) for i in toast.ingredients] == [("Avocados", None), ("Bread", 2.0)]
        lines = s.query(models.ListItem).filter_by(household_id=hid).all()
        assert [(li.name, li.store_id, li.quantities, li.catalog_item_id) for li in lines] == [("Avocados", costco, [[3.0, ""]], ids["Avocados"])]

    # Checks.
    lime = _ids(hid)["Lime"]
    r = alice.post(f"/h/{hid}/catalog/{lime}/merge", {"with": "", "keep": "this"})
    assert r.status_code == 400 and "Pick the item to merge with." in r.text
    r = alice.post(f"/h/{hid}/catalog/{lime}/merge", {"with": "99999", "keep": "this"})
    assert r.status_code == 404
    assert alice.client.post(f"/h/{hid}/catalog/{lime}/merge", data={"with": str(ids["Avocados"])}).status_code == 403  # CSRF


def test_merge_keeps_amounts_that_cant_add_up(make_user):
    alice = make_user("alice")
    hid = alice.create_household()
    _recipe(alice, hid, "Bread", [("Flour", "2", "cup"), ("Bread flour", "1", "lb")])
    ids = _ids(hid)
    alice.post(f"/h/{hid}/catalog/{ids['Bread flour']}/merge", {"with": str(ids["Flour"]), "keep": "other"})
    with session() as s:
        bread = s.query(models.Recipe).one()
        assert [(i.catalog_item.name, i.amount, i.unit) for i in bread.ingredients] == [("Flour", 2.0, "cup"), ("Flour", 1.0, "lb")]


def _queue(page):
    return json.loads(unescape(re.search(r'name="queue" value="([^"]*)"', page).group(1)))


def test_find_and_go_through_duplicates(make_user, monkeypatch):
    alice, hid, costco, smiths = _setup(make_user)
    for name in ("Scallions", "Green onions", "Green onion", "Cake flour", "Flour"):
        alice.post(f"/h/{hid}/catalog", {"name": name, "ranks": ""})
    seen = {}

    def model(prompt, images, schema, reader="recipe reader"):
        seen.update(prompt=prompt, reader=reader)
        return {"groups": [
            {"items": ["Scallions", "Green onions"], "reason": "Another name for it"},
            {"items": ["Nonsense", "Flour"], "reason": "made up"},  # only one real item: dropped
        ]}

    monkeypatch.setattr(scan, "_ask_model", model)
    page = alice.get(f"/h/{hid}/catalog").text
    assert f'action="/h/{hid}/catalog/duplicates"' in page and "Find duplicates" in page and "Looking for duplicates" in page

    r = alice.post(f"/h/{hid}/catalog/duplicates")
    assert r.status_code == 200, r.text[:300]
    assert "Avocado\nAvocados\n" in seen["prompt"] and "Cake flour is not Flour" in seen["prompt"]
    from app import actions
    assert actions._join_reasons("Plural", "plural, Another name") == "Plural, Another name"
    page = r.text
    ids = _ids(hid)
    # The plural pair always counts; the model's pair joins the plural one it overlaps.
    assert "1 of 2" in page and "plural" in page.lower()
    assert re.findall(r'<span class="row-title">([^<]+)</span>', page) == ["Avocado", "Avocados"]
    # The suggested keeper is the one more recipes use.
    assert f'value="{ids["Avocados"]}" checked' in page
    assert "in 2 recipes" in page and "on a list" in page

    form = {"queue": unescape(re.search(r'name="queue" value="([^"]*)"', page).group(1)), "total": "2", "merged": "0", "skipped": "0",
            "decision": "merge", "keep": str(ids["Avocados"]), "include": [str(ids["Avocado"]), str(ids["Avocados"])]}
    page = alice.post(f"/h/{hid}/catalog/duplicates/next", form).text
    assert "2 of 2" in page
    assert re.findall(r'<span class="row-title">([^<]+)</span>', page) == ["Green onion", "Green onions", "Scallions"]
    assert "plural, another name for it" in page and "Uncheck any that aren't the same." in page

    # Leave "Green onion" out; merge the other two.
    form = {"queue": json.dumps(_queue(page)), "total": "2", "merged": "1", "skipped": "0",
            "decision": "merge", "keep": str(ids["Green onions"]), "include": [str(ids["Green onions"]), str(ids["Scallions"])]}
    page = alice.post(f"/h/{hid}/catalog/duplicates/next", form).text
    assert "All done" in page and "Merged 2." in page
    assert set(_ids(hid)) == {"Avocados", "Lime", "Bread", "Green onions", "Green onion", "Cake flour", "Flour"}

    # Skipping, and a group whose items are gone meanwhile is passed over.
    r = alice.post(f"/h/{hid}/catalog/duplicates/next", {"queue": json.dumps([[[99998, 99999], "x"]]), "total": "3", "merged": "0", "skipped": "1", "decision": "skip"})
    assert "All done" in r.text and "kept 2 apart" in r.text

    # A model that can't be reached says so.
    def down(*a, **k):
        raise scan.ScanError("Couldn't reach the model.")

    monkeypatch.setattr(scan, "_ask_model", down)
    r = alice.post(f"/h/{hid}/catalog/duplicates")
    assert r.status_code == 400 and "Couldn&#39;t reach the model." in r.text

    # Without a model, only plurals: here that's Green onion and Green onions.
    monkeypatch.setattr("app.config.OLLAMA_URL", "")
    page = alice.post(f"/h/{hid}/catalog/duplicates").text
    assert "1 of 1" in page and re.findall(r'<span class="row-title">([^<]+)</span>', page) == ["Green onion", "Green onions"]


def test_merge_and_duplicates_in_the_app(make_user, monkeypatch):
    alice, hid, costco, smiths = _setup(make_user)
    phone = App("alice")
    monkeypatch.setattr("app.config.OLLAMA_URL", "")
    body = _api(phone, "post", f"/api/v1/h/{hid}/catalog/duplicates").json()
    assert body["uses_model"] is False and len(body["groups"]) == 1
    group = body["groups"][0]
    assert [(i["name"], i["stores"], i["recipes"], i["on_list"]) for i in group["items"]] == [
        ("Avocado", "Costco", 1, True), ("Avocados", "Smiths", 2, True)]
    ids = _ids(hid)
    assert group["keep"] == ids["Avocados"] and group["reason"] == "Plural"

    r = _api(phone, "post", f"/api/v1/h/{hid}/catalog/merge", json={"keep_id": ids["Avocados"], "merge_ids": [ids["Avocado"]]})
    assert r.status_code == 200, r.text
    state = r.json()["state"]
    assert [c["name"] for c in state["catalog"] if c["name"].startswith("Avocado")] == ["Avocados"]
    assert [(i["name"], i["qty"]) for i in state["items"]] == [("Avocados", "3")]
    # The website's messages.
    r = _api(phone, "post", f"/api/v1/h/{hid}/catalog/merge", json={"keep_id": ids["Avocados"], "merge_ids": []})
    assert r.status_code == 400 and r.json()["detail"] == "Pick another item to merge with."
    r = _api(phone, "post", f"/api/v1/h/{hid}/catalog/merge", json={"keep_id": ids["Avocados"], "merge_ids": [ids["Avocado"]]})
    assert r.status_code == 404
