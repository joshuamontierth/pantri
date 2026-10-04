"""Fill a database with demo data for trying the app locally.

    DATA_DIR=./demo-data python -m dev.seed_demo

Creates users `demo` and `demo2` (password below) sharing a household with stores,
catalog items, recipes and a few list items. Don't run this against real data.
"""

from app import db, quantities, security, services
from app.models import Household, Membership, Recipe, RecipeIngredient, Store, User

DEMO_PASSWORD = "demo-password"


def main():
    db.init_engine()
    s = db.SessionLocal()
    if s.query(User).filter_by(username_lower="demo").first():
        print("Demo data already present.")
        return

    users = []
    for name in ("demo", "demo2"):
        u = User(username=name, username_lower=name, password_hash=security.hash_password(DEMO_PASSWORD))
        s.add(u)
        users.append(u)
    s.flush()

    home = Household(name="Demo Home")
    s.add(home)
    s.flush()
    s.add(Membership(household_id=home.id, user_id=users[0].id, role="admin"))
    s.add(Membership(household_id=home.id, user_id=users[1].id, role="member"))

    stores = {}
    for pos, name in enumerate(["Costco", "Walmart", "Smith's"]):
        st = Store(household_id=home.id, name=name, position=pos)
        s.add(st)
        s.flush()
        stores[name] = st.id

    catalog = {
        "Flour": ["Costco", "Walmart"],
        "Eggs": ["Costco", "Smith's", "Walmart"],
        "Milk": ["Smith's", "Walmart"],
        "Butter": ["Costco"],
        "Sugar": ["Walmart"],
        "Baking powder": ["Walmart", "Smith's"],
        "Cheddar cheese": ["Costco", "Smith's"],
        "Spinach": ["Smith's"],
        "Salt": [],
    }
    items = {}
    for name, ranks in catalog.items():
        items[name] = services.create_catalog_item(s, home.id, name, [stores[r] for r in ranks])

    recipes = {
        "Pancakes": [("Flour", 1.5, "cup"), ("Eggs", 1, ""), ("Milk", 1.25, "cup"), ("Butter", 3, "tbsp"),
                          ("Sugar", 1, "tbsp"), ("Baking powder", 3.5, "tsp"), ("Salt", 0.25, "tsp")],
        "Spinach quiche": [("Eggs", 4, ""), ("Milk", 1, "cup"), ("Cheddar cheese", 8, "oz"),
                                ("Spinach", 10, "oz"), ("Flour", 0.25, "cup"), ("Butter", 2, "tbsp")],
    }
    for name, ings in recipes.items():
        r = Recipe(household_id=home.id, name=name)
        s.add(r)
        s.flush()
        for pos, (ing, amount, unit) in enumerate(ings):
            s.add(RecipeIngredient(recipe_id=r.id, catalog_item_id=items[ing].id, amount=amount, unit=unit, position=pos))

    services.add_to_list(s, home.id, stores["Costco"], "Paper towels", [])
    services.add_to_list(s, home.id, stores["Costco"], "Eggs", quantities.parse_quantity("24"), catalog_item=items["Eggs"])
    services.add_to_list(s, home.id, stores["Smith's"], "Bananas", quantities.parse_quantity("6"), note="not too ripe")
    s.commit()
    print("Created users demo / demo2 with household 'Demo Home'.")


if __name__ == "__main__":
    main()
