"""Parsing, formatting, scaling and merging of shopping quantities.

A quantity is a list of parts: [[amount, unit], ...]. An empty list means "no quantity".
Units are canonical strings: standard units below, "" for a plain count ("each"),
or a lower-case singular custom unit such as "can" or "clove".
"""

import math
import re

# Conversion factors to a base unit (ml for volume, g for weight).
VOLUME = {
    "tsp": 4.92892159375,
    "tbsp": 14.78676478125,
    "fl oz": 29.5735295625,
    "cup": 236.5882365,
    "pt": 473.176473,
    "qt": 946.352946,
    "gal": 3785.411784,
    "ml": 1.0,
    "l": 1000.0,
}
WEIGHT = {
    "oz": 28.349523125,
    "lb": 453.59237,
    "g": 1.0,
    "kg": 1000.0,
}

MAX_AMOUNT = 1_000_000

# Shown in unit pickers, in this order. "each" maps to the "" count unit.
COMMON_UNITS = ["each", "tsp", "tbsp", "cup", "pt", "qt", "gal", "fl oz", "ml", "L", "oz", "lb", "g", "kg"]

_ALIASES = {
    "tsp": ["tsp", "tsps", "tsp.", "teaspoon", "teaspoons"],
    "tbsp": ["tbsp", "tbsps", "tbsp.", "tbs", "tbs.", "tbl", "tablespoon", "tablespoons"],
    "cup": ["cup", "cups", "c", "c."],
    "pt": ["pt", "pts", "pt.", "pint", "pints"],
    "qt": ["qt", "qts", "qt.", "quart", "quarts"],
    "gal": ["gal", "gals", "gal.", "gallon", "gallons"],
    "fl oz": ["fl oz", "fl. oz", "fl. oz.", "fl.oz", "fl.oz.", "floz", "fluid ounce", "fluid ounces"],
    "ml": ["ml", "ml.", "milliliter", "milliliters", "millilitre", "millilitres"],
    "l": ["l", "l.", "liter", "liters", "litre", "litres"],
    "oz": ["oz", "oz.", "ounce", "ounces"],
    "lb": ["lb", "lbs", "lb.", "lbs.", "pound", "pounds", "#"],
    "g": ["g", "g.", "gr", "gram", "grams", "gramme", "grammes"],
    "kg": ["kg", "kg.", "kgs", "kilogram", "kilograms", "kilo", "kilos"],
    "": ["", "each", "ea", "ea.", "ct", "count", "x"],
}
_ALIAS_MAP = {alias: canon for canon, aliases in _ALIASES.items() for alias in aliases}

_DISPLAY = {"l": "L"}
_PLURAL_STANDARD = {"cup": "cups"}

_UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6", "⅚": "5/6",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}
_FRACTION_SLASH = "⁄"

_NUM_RE = re.compile(
    r"^\s*(?P<num>\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+\.\d*|\.\d+|\d+)\s*(?P<rest>.*)$"
)

_UNIT_TEXT_RE = re.compile(r"^[^\W\d_][^\d]*$")

# Kitchen fractions used for display.
_DISPLAY_FRACTIONS = [
    (0.0, ""), (1 / 8, "⅛"), (1 / 4, "¼"), (1 / 3, "⅓"), (3 / 8, "⅜"), (1 / 2, "½"),
    (5 / 8, "⅝"), (2 / 3, "⅔"), (3 / 4, "¾"), (7 / 8, "⅞"), (1.0, ""),
]


def _family(unit):
    if unit in VOLUME:
        return VOLUME
    if unit in WEIGHT:
        return WEIGHT
    return None


def compatible(u1, u2):
    if u1 == u2:
        return True
    fam = _family(u1)
    return fam is not None and fam is _family(u2)


def convert(amount, from_unit, to_unit):
    if from_unit == to_unit:
        return amount
    fam = _family(from_unit)
    return amount * fam[from_unit] / fam[to_unit]


def _singularize(word):
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("sses", "ches", "shes", "xes", "zes"):
        if word.endswith(suffix):
            return word[:-2]
    if len(word) > 2 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def singularize(word):
    """'avocados' -> 'avocado', for matching ingredient names."""
    return _singularize(word)


def _pluralize(word):
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if len(word) > 1 and word.endswith("y") and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def normalize_unit(raw):
    """Map user-typed unit text to a canonical unit string."""
    raw = (raw or "").strip()
    # Case matters only for the classic T (tablespoon) / t (teaspoon) shorthand.
    if raw == "T":
        return "tbsp"
    if raw == "t":
        return "tsp"
    text = re.sub(r"\s+", " ", raw.lower())
    if text in _ALIAS_MAP:
        return _ALIAS_MAP[text]
    text = text.rstrip(".")
    if text in _ALIAS_MAP:
        return _ALIAS_MAP[text]
    return _singularize(text)[:30]


def _expand_unicode_fractions(text):
    text = text.replace(_FRACTION_SLASH, "/")
    for char, ascii_frac in _UNICODE_FRACTIONS.items():
        text = text.replace(char, f" {ascii_frac}")
    return text.strip()


def _number_value(num_text):
    num_text = re.sub(r"\s*/\s*", "/", num_text.strip())
    parts = num_text.split()
    total = 0.0
    for part in parts:
        if "/" in part:
            n, d = part.split("/")
            if float(d) == 0:
                raise ValueError("Division by zero in quantity")
            total += float(n) / float(d)
        else:
            total += float(part)
    if not math.isfinite(total) or total > MAX_AMOUNT:
        raise ValueError("Number too large")
    return total


def parse_amount(text):
    """Parse a bare number like '2', '1.5', '1 1/2', '1½'. Returns None for blank input."""
    text = _expand_unicode_fractions((text or "").strip())
    if not text:
        return None
    m = _NUM_RE.match(text)
    if not m or m.group("rest").strip():
        raise ValueError(f"Not a number: {text!r}")
    return _number_value(m.group("num"))


def parse_part(text):
    """Parse '1 1/2 cups' -> [1.5, 'cup']. A unit with no number ('can') is not allowed."""
    text = _expand_unicode_fractions(text.strip())
    m = _NUM_RE.match(text)
    if not m:
        raise ValueError(f"Quantity must start with a number: {text!r}")
    amount = _number_value(m.group("num"))
    rest = m.group("rest").strip()
    # "2-3", "1,5 kg", "2 x 400g" aren't quantities we understand; callers fall back to a note.
    if rest and rest != "#" and not _UNIT_TEXT_RE.match(rest):
        raise ValueError(f"Not a unit: {rest!r}")
    return [amount, normalize_unit(rest)]


def parse_quantity(text):
    """Parse '2 cups + 1 lb' into parts. Blank -> []. Raises ValueError if unparseable."""
    text = (text or "").strip()
    if not text:
        return []
    parts = [p for p in text.split("+") if p.strip()]
    return combine([], [parse_part(p) for p in parts])


def combine(a, b):
    """Merge quantity b into quantity a. Compatible units are converted to a's unit."""
    result = [[float(amount), unit] for amount, unit in a]
    for amount, unit in b:
        for part in result:
            if compatible(part[1], unit):
                part[0] += convert(float(amount), unit, part[1])
                break
        else:
            result.append([float(amount), unit])
    return result


def scale(parts, multiplier):
    return [[amount * multiplier, unit] for amount, unit in parts]


def _round_fraction(x):
    """Return (whole, fraction_symbol) for x rounded to the nearest kitchen fraction."""
    whole = math.floor(x)
    frac = x - whole
    value, symbol = min(_DISPLAY_FRACTIONS, key=lambda f: abs(f[0] - frac))
    if value == 1.0:
        whole += 1
    return whole, symbol


def format_amount(amount, unit=""):
    if unit in ("g", "ml"):
        if amount >= 10:
            return str(int(round(amount)))
        return f"{amount:.1f}".rstrip("0").rstrip(".") or "0"
    whole, symbol = _round_fraction(amount)
    if whole == 0 and not symbol:
        return "⅛" if amount > 0 else "0"
    if whole == 0:
        return symbol
    return f"{whole}{symbol}"


def _rounded(amount, unit):
    if unit in ("g", "ml"):
        return amount
    whole, symbol = _round_fraction(amount)
    frac = next(v for v, s in _DISPLAY_FRACTIONS if s == symbol) if symbol else 0.0
    return whole + frac


def display_unit(unit, amount):
    if unit == "":
        return ""
    plural = _rounded(amount, unit) > 1.0 + 1e-9
    if unit in _family_units():
        if plural and unit in _PLURAL_STANDARD:
            return _PLURAL_STANDARD[unit]
        return _DISPLAY.get(unit, unit)
    return _pluralize(unit) if plural else unit


def _family_units():
    return VOLUME.keys() | WEIGHT.keys()


def format_part(amount, unit):
    unit_text = display_unit(unit, amount)
    num = format_amount(amount, unit)
    return f"{num} {unit_text}" if unit_text else num


def format_quantity(parts):
    return " + ".join(format_part(amount, unit) for amount, unit in parts)


def unit_label(unit):
    """Unit as shown in an input box (canonical -> friendly)."""
    if unit == "":
        return ""
    return _DISPLAY.get(unit, unit)


_EXACT_DENOMINATORS = (1, 2, 3, 4, 8)


def amount_input_text(amount):
    """Amount for an edit box: exact (unlike format_amount), so re-saving doesn't change it."""
    for d in _EXACT_DENOMINATORS:
        n = round(amount * d)
        if n and abs(amount * d - n) < 1e-6:
            whole, rem = divmod(n, d)
            if rem == 0:
                return str(whole)
            return f"{whole} {rem}/{d}" if whole else f"{rem}/{d}"
    return f"{round(amount, 6):f}".rstrip("0").rstrip(".")


def quantity_input_text(parts):
    return " + ".join(
        f"{amount_input_text(amount)} {unit_label(unit)}".strip() for amount, unit in parts
    )


# Units that were free text before they became standard ones (US pints, quarts, gallons).
LEGACY_UNITS = {"pint": "pt", "quart": "qt", "gallon": "gal"}
