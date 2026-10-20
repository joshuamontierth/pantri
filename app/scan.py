"""Read a recipe or a shopping list from photos (or from text) using a model served by Ollama."""

import base64
import io
import json
import re
import urllib.error
import urllib.request

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, directions, quantities

MAX_PHOTOS = 4
MAX_PHOTO_BYTES = 25 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 60_000_000  # phone photos are ~12-50 MP; refuse anything absurd
_MAX_PAGE_TEXT = 12_000
MAX_LIST_TEXT = 6_000

_INGREDIENTS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        # Copying the line out first keeps the model from garbling amounts on some recipes.
        "properties": {
            "line": {"type": "string"},
            "item": {"type": "string"},
            "amount": {"type": "string"},
            "unit": {"type": "string"},
        },
        "required": ["line", "item", "amount", "unit"],
    },
}
_RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "ingredients": _INGREDIENTS_SCHEMA,
        "directions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "ingredients", "directions"],
}
_LINES_SCHEMA = {"type": "object", "properties": {"ingredients": _INGREDIENTS_SCHEMA}, "required": ["ingredients"]}
_LIST_SCHEMA = {"type": "object", "properties": {"items": _INGREDIENTS_SCHEMA}, "required": ["items"]}

_INGREDIENT_RULES = """- ingredients: one entry per ingredient, in order.
  - line: the ingredient's line exactly as written, before you split it up.
  - item: what you'd buy at a store, in plain words, without prep words like chopped, minced, divided or softened.
  - amount: the number exactly as written, like 2, 1/2, 1 1/2 or 0.75. For a range like 4-5 use the larger number. \
Empty if there is no amount.
  - unit: like cup, tbsp, tsp, lb, oz, clove, can, stalk or loaf. Empty for a plain count like 3 avocados. \
Never put a number or a package size in the unit: for "1 (16 ounce) package bacon" the amount is 1 and the unit \
is package; for "4 (6 ounce) chicken breasts" the amount is 4 and the unit is empty.
  - For a pinch, dash, splash, sprinkle or "to taste", leave both amount and unit empty.
  - For "juice of 1/2 lime" or "zest of 1 lemon", the item is the fruit itself (Lime, Lemon) with that count and an empty unit.
  - Two ingredients on one line, like "salt and pepper to taste", are two entries.
  - When an ingredient offers a choice ("lime or lemon", "French or GF bread"), list only the first option, once.
  - Leave out water and ice.
"""

_DIRECTIONS_RULE = """- directions: the method, in order. One entry per numbered step or paragraph, copied word for word \
without the step number. Keep a section heading like "For the sauce:" as its own entry. Leave out nutrition facts, \
servings and notes. An empty list if there are no directions.
"""

_PHOTO_PROMPT = """These photos show one recipe: a handwritten card, a printed page or a screenshot. Several photos can \
be different parts of the same recipe, like the ingredients in one and the directions in another, so combine them. \
If a page shows more than one recipe, read the one that is shown in full.
- name: the recipe's title.
""" + _INGREDIENT_RULES + _DIRECTIONS_RULE

_PAGE_PROMPT = """Below is the text of a web page with a recipe on it. Extract the recipe and ignore everything else, \
like ads, comments, reviews and other recipes.
- name: the recipe's title.
""" + _INGREDIENT_RULES + _DIRECTIONS_RULE

_LINES_PROMPT = """Below are the ingredient lines of a recipe, one per line. Turn them into shopping list entries.
""" + _INGREDIENT_RULES

_LIST_RULES = """- items: one entry per thing to buy, in the order written.
  - line: the line exactly as written, before you split it up.
  - item: what to buy, in plain words, with the spelling fixed and abbreviations written out (OJ is Orange juice). \
Keep words that pick a kind, like 2% milk, whole wheat bread or Greek yogurt.
  - amount: how many or how much, exactly as written, like 2, 1/2 or 1 1/2. "x2" or "(2)" after an item is 2. \
For a range like 4-5 use the larger number. Empty if there is no amount.
  - unit: like lb, oz, gal, bag, box, can, bunch, pack or dozen. Empty for a plain count like 6 apples. \
Never put a number in the unit.
  - Two things on one line, like "salt & pepper", are two entries.
  - Leave out anything crossed out or checked off, headings (like a store's name or "Produce"), dates, and notes \
that aren't something to buy.
"""

_LIST_PHOTO_PROMPT = """These photos show a shopping list: handwritten, printed, or a screenshot of a note or a message. \
Several photos can be parts of the same list, so combine them.
""" + _LIST_RULES

_LIST_TEXT_PROMPT = """Below is a shopping list someone typed or pasted. Turn it into shopping list entries.
""" + _LIST_RULES


class ScanError(Exception):
    """Something the user should see, worded for them."""


def enabled():
    return bool(config.OLLAMA_URL and config.OLLAMA_MODEL)


def prepare_photo(data):
    """Upright, shrunk JPEG as base64. Phones store rotation in EXIF and shoot 4000px+ images."""
    if len(data) > MAX_PHOTO_BYTES:
        raise ScanError("That photo is too large. Try one under 25 MB.")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise ScanError("That file isn't a photo I can read. Use a JPEG or PNG.")
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _with_catalog(prompt, catalog_names, noun="ingredient"):
    if catalog_names:
        prompt += (f"- If an {noun} is the same product as one of these existing items, just worded differently, "
                   "use that exact name. Keep different kinds apart (cake flour is not Flour, smoked paprika is not "
                   "Paprika): " + ", ".join(catalog_names[:400]) + ".\n")
    return prompt


def _with_name(prompt, recipe_name):
    """When adding to an existing recipe: which recipe to read, and that a part of it is enough."""
    if recipe_name:
        prompt += (f'- This is the recipe "{recipe_name}". If there are several recipes, read that one. '
                   "It's fine if only part of it is shown, like just the directions.\n")
    return prompt


def _ask_model(prompt, images, schema, reader="recipe reader"):
    message = {"role": "user", "content": prompt}
    if images:
        message["images"] = images
    body = {
        "model": config.OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0, "num_ctx": config.OLLAMA_NUM_CTX},
        "messages": [message],
    }
    req = urllib.request.Request(
        config.OLLAMA_URL.rstrip("/") + "/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=config.OLLAMA_TIMEOUT) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        raise ScanError(f"The {reader} returned an error ({e.code}). Try again in a minute.")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ScanError(f"Couldn't reach the {reader}. Check that this server can reach the model server (OLLAMA_URL).")
    try:
        data = json.loads(payload["message"]["content"])
    except (KeyError, TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise ScanError(f"The {reader}'s answer didn't make sense. Try again.")
    return data


def _ingredients(data, key="ingredients"):
    out = []
    for ing in data.get(key) or []:
        if not isinstance(ing, dict):
            continue
        item = str(ing.get("item") or "").strip()[:100]
        if item:
            out.append({
                "item": item,
                "amount": str(ing.get("amount") or "").strip()[:30],
                "unit": str(ing.get("unit") or "").strip()[:30],
                "line": str(ing.get("line") or "").strip()[:200],
            })
    return out


# Seasoning-sized measures don't belong on a shopping list; these become a blank amount.
_VAGUE_RE = re.compile(r"\b(pinch|pinches|dash|dashes|smidgen|splash|sprinkle|drizzle|to taste|as needed|as desired|optional)\b", re.I)


def clean_amount(amount_text, unit_text):
    """Tidy what the model read ("1-2", "Tbsp.", "cloves") into (amount, unit) text an editor accepts, or blanks."""
    amount_text, unit_text = amount_text.strip(), unit_text.strip()
    if _VAGUE_RE.search(amount_text) or _VAGUE_RE.search(unit_text):
        return "", ""
    # A package size that ended up in the unit: "4" + "4 ounce" is 4, "1" + "16 ounce package" is 1 package.
    unit_text = re.sub(r"^\(?\s*[\d./]+\s*-?\s*[a-z]+\.?\s*\)?\s*", "", unit_text, flags=re.I) if amount_text else unit_text
    rng = re.match(r"^(.+?)\s*(?:-|–|to)\s*(.+)$", amount_text)
    if rng:
        amount_text = rng.group(2)  # ranges: buy enough for the larger amount
    if not amount_text:
        return "", ""
    try:
        value = quantities.parse_amount(amount_text)
        unit = quantities.normalize_unit(unit_text)
    except ValueError:
        try:
            # e.g. amount "2 cups" with the unit folded in
            value, unit = quantities.parse_part(f"{amount_text} {unit_text}")
        except ValueError:
            return "", ""  # "some", "a few": leave it blank so the recipe still saves
    if not value or value <= 0:
        return "", ""
    return quantities.amount_input_text(value), quantities.unit_label(unit)


def _recipe(data, missing_message, partial=False):
    """The model's answer, cleaned up. A partial read (adding to a recipe) may have directions but no ingredients."""
    ingredients = _ingredients(data)
    steps = data.get("directions") or []
    if isinstance(steps, str):
        steps = [steps]
    text = directions.join_steps(str(s) for s in steps if s)
    if not ingredients and not (partial and text):
        raise ScanError(missing_message)
    return {"name": str(data.get("name") or "").strip()[:150], "ingredients": ingredients, "directions": text}


def read_recipe(photo_bytes, catalog_names, recipe_name=None):
    """{"name", "ingredients": [{"item", "amount", "unit"}], "directions"} read from the photos.

    With recipe_name (adding to an existing recipe), photos of just the directions are fine.
    """
    photos = [prepare_photo(b) for b in photo_bytes[:MAX_PHOTOS]]
    if not photos:
        raise ScanError("Take or choose a photo of the recipe first.")
    prompt = _with_name(_with_catalog(_PHOTO_PROMPT, catalog_names), recipe_name)
    missing = ("I couldn't find ingredients or directions in that photo. Try a closer, sharper shot." if recipe_name else
               "I couldn't find any ingredients in that photo. Try a closer, sharper shot of the ingredient list.")
    return _recipe(_ask_model(prompt, photos, _RECIPE_SCHEMA), missing, partial=bool(recipe_name))


def read_page_text(title, text, catalog_names, recipe_name=None):
    """Like read_recipe, from the visible text of a web page."""
    prompt = (_with_name(_with_catalog(_PAGE_PROMPT, catalog_names), recipe_name)
              + f"\nPage title: {title}\n\nPage text:\n{text[:_MAX_PAGE_TEXT]}")
    return _recipe(_ask_model(prompt, None, _RECIPE_SCHEMA), "I couldn't find a recipe on that page.",
                   partial=bool(recipe_name))


def read_ingredient_lines(lines, catalog_names):
    """Turn lines like "2 cups chopped onion" into [{"item", "amount", "unit"}]."""
    prompt = _with_catalog(_LINES_PROMPT, catalog_names) + "\nIngredient lines:\n" + "\n".join(lines)
    return _ingredients(_ask_model(prompt, None, _LINES_SCHEMA))


def read_shopping_list(photo_bytes, text, catalog_names):
    """[{"item", "amount", "unit", "line"}] read from photos of a shopping list, or from its typed text."""
    if photo_bytes:
        images = [prepare_photo(b) for b in photo_bytes[:MAX_PHOTOS]]
        prompt = _with_catalog(_LIST_PHOTO_PROMPT, catalog_names, "item")
        missing = "I couldn't find a shopping list in that photo. Try a closer, sharper shot."
    else:
        text = (text or "").strip()
        if not text:
            raise ScanError("Take or choose a photo of your list, or paste it in.")
        if len(text) > MAX_LIST_TEXT:
            raise ScanError(f"That list is too long. Paste up to {MAX_LIST_TEXT:,} characters at a time.")
        images = None
        prompt = _with_catalog(_LIST_TEXT_PROMPT, catalog_names, "item") + "\nList:\n" + text
        missing = "I couldn't find anything to buy in that list."
    items = _ingredients(_ask_model(prompt, images, _LIST_SCHEMA, reader="list reader"), key="items")
    if not items:
        raise ScanError(missing)
    return items


_DUPLICATES_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"items": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}},
                "required": ["items", "reason"],
            },
        },
    },
    "required": ["groups"],
}

_DUPLICATES_PROMPT = """Below is a household's catalog of grocery items, one per line. Find items that are the same \
product written differently, so they can be merged into one:
- plurals and misspellings, like Avocado and Avocados, or Tomatoe and Tomato
- other names or abbreviations for the same thing, like Scallions and Green onions, or OJ and Orange juice
- extra words that don't change what you'd buy, like Garlic and Garlic cloves
Keep different kinds apart: Cake flour is not Flour, Smoked paprika is not Paprika, Red onion is not Onion, \
Almond milk is not Milk, Chicken breast is not Chicken thighs.
- groups: each group is two or more names copied exactly from the list that are the same product. A name is in \
at most one group. An empty list if there are none.
- reason: a few words, like "plural", "misspelling" or "another name for it".

Catalog:
"""


def find_duplicates(names):
    """[{"names": [...], "reason"}]: catalog items the model thinks are the same product."""
    if len(names) < 2:
        return []
    data = _ask_model(_DUPLICATES_PROMPT + "\n".join(names[:600]), None, _DUPLICATES_SCHEMA, reader="model")
    out = []
    for g in data.get("groups") or []:
        if not isinstance(g, dict) or not isinstance(g.get("items"), list):
            continue
        group = [str(n).strip() for n in g["items"] if str(n).strip()]
        if len(group) >= 2:
            out.append({"names": group, "reason": str(g.get("reason") or "").strip()[:80]})
    return out
