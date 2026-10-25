"""The meal calendar: a week of lunches and dinners, on the website and in the app."""

import re
from datetime import date, timedelta
from html import unescape
from urllib.parse import parse_qsl

from app import actions, db, models
from test_api import App, _api


def session():
    return db.SessionLocal()


def _recipe(user, hid, name, ingredient="Bread"):
    form = {"name": name, "ing_name": [ingredient], "ing_amount": ["1"], "ing_unit": [""], "ing_ranks": [""], "ing_ranks_dirty": ["0"]}
    assert user.post(f"/h/{hid}/recipes", form).status_code == 303
    with session() as s:
        return s.query(models.Recipe).filter_by(household_id=hid, name=name).one().id


def _meals(hid):
    with session() as s:
        return [(m.day.isoformat(), m.slot, m.recipe_id, m.title) for m in s.query(models.Meal).filter_by(household_id=hid).order_by(models.Meal.id)]


def test_week_page(make_user, monkeypatch):
    monkeypatch.setattr(actions, "today", lambda: date(2026, 10, 14))  # a Wednesday
    alice = make_user("alice")
    hid = alice.create_household()
    page = alice.get(f"/h/{hid}/meals").text
    assert 'aria-current="page">Meals</a>' in page
    # Saturday to Friday unless set otherwise, today marked; lunch and dinner each day.
    days = re.findall(r'<span class="day-name">(\w+)</span>', page)
    assert days == ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    assert 'id="day-2026-10-10"' in page and 'id="day-2026-10-16"' in page and "<strong>Oct 10 – 16</strong>" in page
    assert page.count('data-meal-add') == 14 and "This week" in page
    assert 'class="day is-today" id="day-2026-10-14"' in page
    nxt = alice.get(f"/h/{hid}/meals?week=2026-10-20").text  # any day picks its week
    assert "<strong>Oct 17 – 23</strong>" in nxt and "Next week" in nxt and f'href="/h/{hid}/meals">Today</a>' in nxt
    assert "<strong>Sep 26 – Oct 2</strong>" in alice.get(f"/h/{hid}/meals?week=2026-09-30").text
    assert "Oct 10 – 16" in alice.get(f"/h/{hid}/meals?week=nonsense").text  # back to this week

    # Weeks can start on another day, for the whole household.
    page = alice.get(f"/h/{hid}/settings").text
    assert "Weeks start on" in page and '<option value="5" selected>Saturday</option>' in page
    r = alice.post(f"/h/{hid}/week-start", {"weekday": "6"})
    assert r.status_code == 303 and "Weeks start on Sunday now." in alice.get(r.headers["location"]).text
    days = re.findall(r'<span class="day-name">(\w+)</span>', alice.get(f"/h/{hid}/meals").text)
    assert days[0] == "Sunday" and days[-1] == "Saturday"
    assert "<strong>Oct 18 – 24</strong>" in alice.get(f"/h/{hid}/meals?week=2026-10-20").text
    r = alice.post(f"/h/{hid}/week-start", {"weekday": "9"})
    assert r.status_code == 400 and "Pick a day of the week." in r.text


def test_add_recipes_and_custom_meals(make_user, monkeypatch):
    monkeypatch.setattr(actions, "today", lambda: date(2026, 10, 14))
    alice = make_user("alice")
    hid = alice.create_household()
    tacos, guac = _recipe(alice, hid, "Tacos", "Tortillas"), _recipe(alice, hid, "Guacamole", "Avocados")

    # Two recipes and a custom meal on one dinner; back to the week to plan the next meal.
    r = alice.post(f"/h/{hid}/meals", {"day": "2026-10-15", "slot": "dinner", "recipe_id": [str(tacos), str(guac)],
                                       "title": "Chips", "week": "2026-10-11"})
    assert r.status_code == 303 and r.headers["location"] == f"/h/{hid}/meals#day-2026-10-15"
    assert _meals(hid) == [("2026-10-15", "dinner", tacos, "Tacos"), ("2026-10-15", "dinner", guac, "Guacamole"),
                           ("2026-10-15", "dinner", None, "Chips")]

    # The same recipe on another meal (cooked again); on the same meal it isn't doubled up.
    r = alice.post(f"/h/{hid}/meals", {"day": "2026-10-16", "slot": "lunch", "recipe_id": str(tacos), "week": "2026-10-11"})
    assert r.status_code == 303 and r.headers["location"] == f"/h/{hid}/meals#day-2026-10-16"
    alice.post(f"/h/{hid}/meals", {"day": "2026-10-16", "slot": "lunch", "recipe_id": str(tacos), "week": "2026-10-11"})
    assert _meals(hid)[3:] == [("2026-10-16", "lunch", tacos, "Tacos")]

    # A custom meal alone, in another week: back to that week.
    r = alice.post(f"/h/{hid}/meals", {"day": "2026-10-20", "slot": "lunch", "title": "Eating out", "week": "2026-10-18"})
    assert r.headers["location"] == f"/h/{hid}/meals?week=2026-10-17#day-2026-10-20"
    # A past day this week.
    alice.post(f"/h/{hid}/meals", {"day": "2026-10-12", "slot": "dinner", "recipe_id": str(guac), "week": "2026-10-11"})

    page = alice.get(f"/h/{hid}/meals").text
    assert f'href="/h/{hid}/recipes/{tacos}">Tacos</a>' in page and '<span class="meal-name">Chips</span>' in page
    assert "Eating out" not in page  # next week's
    # Each recipe chip says which recipe and day, for choosing meals to shop for (meals.js).
    assert page.count(f'data-recipe="{tacos}"') == 2 and 'data-recipe="%d" data-day="2026-10-12"' % guac in page
    assert "Choose meals to shop for" in page and 'data-today="2026-10-14"' in page
    # Without JavaScript the button goes to the picker with the meals still ahead: Tacos twice, Guacamole once
    # (Monday's has been eaten), and back to this week.
    link = unescape(re.search(r'href="([^"]+)" data-shop-start', page).group(1))
    path, _, fragment = link.partition("#")
    assert path == f"/h/{hid}/plan"
    assert parse_qsl(fragment) == [("step", "pick"), ("r", str(tacos)), ("r", str(guac)), (f"m_{tacos}", "2"), ("back", f"/h/{hid}/meals")]

    # Checks, with the page shown again.
    for data, message in [
        ({"day": "2026-10-15", "slot": "dinner"}, "Pick a recipe or type a meal."),
        ({"day": "2026-10-15", "slot": "brunch", "title": "x"}, "Pick lunch or dinner."),
        ({"day": "someday", "slot": "lunch", "title": "x"}, "That&#39;s not a date."),
        ({"day": "2026-10-15", "slot": "lunch", "title": "x" * 151}, "up to 150 characters"),
        ({"day": "2026-10-15", "slot": "lunch", "recipe_id": "99999"}, "That recipe is gone."),
    ]:
        r = alice.post(f"/h/{hid}/meals", {**data, "week": "2026-10-11"})
        assert r.status_code in (400, 404) and message in r.text, (data, r.text[:300])

    # Remove one; a recipe deleted later leaves its meal with the name it had.
    first = _meal_ids(hid)[0]  # Thursday's Tacos
    assert alice.post(f"/h/{hid}/meals/{first}/delete", {"week": "2026-10-11"}).headers["location"] == f"/h/{hid}/meals"
    assert alice.post(f"/h/{hid}/meals/{first}/delete", {"week": "2026-10-11"}).status_code == 303  # already gone: fine
    assert alice.post(f"/h/{hid}/recipes/{guac}/delete").status_code == 303
    assert ("2026-10-15", "dinner", None, "Guacamole") in _meals(hid)
    assert "Choose meals to shop for" in alice.get(f"/h/{hid}/meals").text  # Friday's Tacos are still a recipe
    assert alice.client.post(f"/h/{hid}/meals", data={"day": "2026-10-15", "slot": "lunch", "title": "x"}).status_code == 403  # CSRF


def _meal_ids(hid):
    with session() as s:
        return [m.id for m in s.query(models.Meal).filter_by(household_id=hid).order_by(models.Meal.id)]


def test_meals_stay_in_their_household(make_user):
    alice, bob = make_user("alice"), make_user("bob")
    hid, other = alice.create_household(), bob.create_household()
    bobs = _recipe(bob, other, "Bob's soup")
    r = alice.post(f"/h/{hid}/meals", {"day": "2026-10-15", "slot": "lunch", "recipe_id": str(bobs)})
    assert r.status_code == 404 and _meals(hid) == []
    bob.post(f"/h/{other}/meals", {"day": "2026-10-15", "slot": "lunch", "title": "Soup"})
    assert alice.post(f"/h/{hid}/meals/{_meal_ids(other)[0]}/delete", {}).status_code == 303
    assert len(_meals(other)) == 1  # not alice's to remove
    assert alice.get(f"/h/{other}/meals").status_code == 404


def test_meals_in_the_app(make_user, monkeypatch):
    alice = make_user("alice")
    hid = alice.create_household()
    soup = _recipe(alice, hid, "Soup")
    phone = App("alice")
    today = actions.today()
    r = _api(phone, "post", f"/api/v1/h/{hid}/meals", json={"day": today.isoformat(), "slot": "dinner", "recipe_ids": [soup], "title": "Salad"})
    assert r.status_code == 200, r.text
    assert r.json()["state"]["household"]["week_start"] == 5  # Saturday until set
    r2 = _api(phone, "post", f"/api/v1/h/{hid}/week-start", json={"weekday": 0})
    assert r2.status_code == 200 and r2.json()["state"]["household"]["week_start"] == 0
    r2 = _api(phone, "post", f"/api/v1/h/{hid}/week-start", json={"weekday": "Monday"})
    assert r2.status_code == 400 and r2.json()["detail"] == "Pick a day of the week."
    meals = r.json()["state"]["meals"]
    assert [(m["day"], m["slot"], m["recipe_id"], m["title"]) for m in meals] == [
        (today.isoformat(), "dinner", soup, "Soup"), (today.isoformat(), "dinner", None, "Salad")]
    # The website's messages.
    r = _api(phone, "post", f"/api/v1/h/{hid}/meals", json={"day": today.isoformat(), "slot": "dinner"})
    assert r.status_code == 400 and r.json()["detail"] == "Pick a recipe or type a meal."
    r = _api(phone, "delete", f"/api/v1/h/{hid}/meals/{meals[1]['id']}")
    assert [m["title"] for m in r.json()["state"]["meals"]] == ["Soup"]
    assert _api(phone, "delete", f"/api/v1/h/{hid}/meals/{meals[1]['id']}").status_code == 404
    # The state carries a year back and everything ahead.
    old = (today - timedelta(days=400)).isoformat()
    _api(phone, "post", f"/api/v1/h/{hid}/meals", json={"day": old, "slot": "lunch", "title": "Long ago"})
    later = (today + timedelta(days=200)).isoformat()
    state = _api(phone, "post", f"/api/v1/h/{hid}/meals", json={"day": later, "slot": "lunch", "title": "Later"}).json()["state"]
    assert [m["title"] for m in state["meals"]] == ["Soup", "Later"]


def test_week_start_and_timezone(monkeypatch):
    assert actions.week_start(date(2026, 10, 17)) == date(2026, 10, 17)  # a Saturday starts its own week
    assert actions.week_start(date(2026, 10, 16)) == date(2026, 10, 10)  # Friday ends it
    assert actions.week_start(date(2026, 10, 17), first=6) == date(2026, 10, 11)  # Sunday weeks
    assert actions.week_start(date(2026, 10, 18), first=6) == date(2026, 10, 18)
    assert actions.week_start(date(2026, 10, 18), first=0) == date(2026, 10, 12)  # Monday weeks
    monkeypatch.setattr("app.config.TIMEZONE", "Not/AZone")
    assert isinstance(actions.today(), date)  # a bad setting falls back to the server's clock
