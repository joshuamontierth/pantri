"""Read a recipe from photos (or from a web page's text) using a model served by Ollama."""

import base64
import io
import json
import urllib.error
import urllib.request

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, directions

MAX_PHOTOS = 4
MAX_PHOTO_BYTES = 25 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 60_000_000  # phone photos are ~12-50 MP; refuse anything absurd
_MAX_PAGE_TEXT = 12_000

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


def _with_catalog(prompt, catalog_names):
    if catalog_names:
        prompt += ("- If an ingredient is the same product as one of these existing items, just worded differently, "
                   "use that exact name. Keep different kinds apart (cake flour is not Flour, smoked paprika is not "
                   "Paprika): " + ", ".join(catalog_names[:400]) + ".\n")
    return prompt


def _with_name(prompt, recipe_name):
    """When adding to an existing recipe: which recipe to read, and that a part of it is enough."""
    if recipe_name:
        prompt += (f'- This is the recipe "{recipe_name}". If there are several recipes, read that one. '
                   "It's fine if only part of it is shown, like just the directions.\n")
    return prompt


def _ask_model(prompt, images, schema):
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
        raise ScanError(f"The recipe reader returned an error ({e.code}). Try again in a minute.")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ScanError("Couldn't reach the recipe reader. Check that this server can reach the model server (OLLAMA_URL).")
    try:
        data = json.loads(payload["message"]["content"])
    except (KeyError, TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise ScanError("The recipe reader's answer didn't make sense. Try again.")
    return data


def _ingredients(data):
    out = []
    for ing in data.get("ingredients") or []:
        if not isinstance(ing, dict):
            continue
        item = str(ing.get("item") or "").strip()[:100]
        if item:
            out.append({
                "item": item,
                "amount": str(ing.get("amount") or "").strip()[:30],
                "unit": str(ing.get("unit") or "").strip()[:30],
            })
    return out


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
