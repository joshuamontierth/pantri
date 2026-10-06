import pytest

from app.quantities import combine, format_quantity, normalize_unit, parse_amount, parse_quantity, scale


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", []),
        ("2", [[2.0, ""]]),
        ("2 cups", [[2.0, "cup"]]),
        ("1 1/2 cup", [[1.5, "cup"]]),
        ("1½ cups", [[1.5, "cup"]]),
        ("½ tsp", [[0.5, "tsp"]]),
        ("2 T", [[2.0, "tbsp"]]),
        ("1 t", [[1.0, "tsp"]]),
        ("3 cans", [[3.0, "can"]]),
        ("2 bunches", [[2.0, "bunch"]]),
        ("6 each", [[6.0, ""]]),
        ("2 cups + 1 lb", [[2.0, "cup"], [1.0, "lb"]]),
        ("1 cup + 4 tbsp", [[1.25, "cup"]]),
    ],
)
def test_parse_quantity(text, expected):
    got = parse_quantity(text)
    assert [[round(a, 6), u] for a, u in got] == [[round(a, 6), u] for a, u in expected]


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_quantity("a few")
    with pytest.raises(ValueError):
        parse_amount("two")


def test_units():
    assert normalize_unit("Tablespoons") == "tbsp"
    assert normalize_unit("lbs") == "lb"
    assert normalize_unit("L") == "l"
    assert normalize_unit("Cloves") == "clove"


def test_combine_converts_within_family_and_keeps_others():
    q = combine([[2, "cup"]], [[1, "lb"], [8, "tbsp"]])
    assert format_quantity(q) == "2½ cups + 1 lb"
    assert format_quantity(combine([[1, "lb"]], [[8, "oz"]])) == "1½ lb"
    assert format_quantity(combine([[2, "can"]], [[1, "can"], [1, "jar"]])) == "3 cans + 1 jar"


def test_format_fractions_and_metric():
    assert format_quantity(scale([[0.75, "cup"]], 2)) == "1½ cups"
    assert format_quantity([[1 / 3, "cup"]]) == "⅓ cup"
    assert format_quantity([[0.01, "tsp"]]) == "⅛ tsp"
    assert format_quantity([[250.4, "g"]]) == "250 g"
    assert format_quantity([[1.02, "cup"]]) == "1 cup"
    assert format_quantity([[12, ""]]) == "12"


def test_pints_quarts_gallons():
    from app import quantities as q

    assert q.parse_part("1 gallon") == [1.0, "gal"]
    assert q.parse_part("2 quarts") == [2.0, "qt"]
    assert q.parse_part("1 pt") == [1.0, "pt"]
    assert q.format_part(2, "gal") == "2 gal"
    # A gallon of milk plus 4 cups from a recipe is 1¼ gallons.
    assert q.format_quantity(q.combine([[1, "gal"]], [[4, "cup"]])) == "1¼ gal"
    assert q.format_quantity(q.combine([[1, "qt"]], [[1, "pt"]])) == "1½ qt"


def test_old_gallon_units_are_upgraded(tmp_path):
    import sqlite3

    from app import db, models

    db.init_engine(tmp_path / "t.db")
    with db.SessionLocal() as s:
        h = models.Household(name="H")
        s.add(h)
        s.flush()
        s.add(models.ListItem(household_id=h.id, name="Milk", name_lower="milk", quantities=[[1.0, "gallon"], [2.0, "cup"]]))
        cat = models.CatalogItem(household_id=h.id, name="Cream", name_lower="cream")
        s.add(cat)
        s.flush()
        r = models.Recipe(household_id=h.id, name="R")
        s.add(r)
        s.flush()
        s.add(models.RecipeIngredient(recipe_id=r.id, catalog_item_id=cat.id, amount=1, unit="quart"))
        s.commit()
    db.init_engine(tmp_path / "t.db")  # restart
    with db.SessionLocal() as s:
        assert s.query(models.ListItem).one().quantities == [[1.125, "gal"]]  # now they merge
        assert s.query(models.RecipeIngredient).one().unit == "qt"
