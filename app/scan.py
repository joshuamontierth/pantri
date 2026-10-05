"""Read a recipe from photos using a vision model served by Ollama."""

import base64
import io
import json
import urllib.error
import urllib.request

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config

MAX_PHOTOS = 4
MAX_PHOTO_BYTES = 25 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 60_000_000  # phone photos are ~12-50 MP; refuse anything absurd

_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "amount": {"type": "string"},
                    "unit": {"type": "string"},
                },
                "required": ["item", "amount", "unit"],
            },
        },
    },
    "required": ["name", "ingredients"],
}

_PROMPT = """These photos show one recipe (a handwritten card, a printed page, or the front and back of a card). \
Extract it for a shopping list.
- name: the recipe's title.
- ingredients: one entry per ingredient, in order.
  - item: what you'd buy at a store, in plain words, without prep words like chopped, minced, divided or softened.
  - amount: the number exactly as written, like 2, 1/2, 1 1/2 or 0.75. For a range like 4-5 use the larger number. \
Empty if there is no amount.
  - unit: like cup, tbsp, tsp, lb, oz, clove, can, stalk, loaf or pinch. Empty for a plain count like 3 avocados.
- Leave out water and ice. Ignore cooking directions.
"""


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


def _ask_model(photos_b64, catalog_names):
    prompt = _PROMPT
    if catalog_names:
        prompt += ("- If an ingredient is the same thing as one of these existing items, use that exact name: "
                   + ", ".join(catalog_names[:400]) + ".\n")
    body = {
        "model": config.OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "format": _SCHEMA,
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": prompt, "images": photos_b64}],
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
        return json.loads(payload["message"]["content"])
    except (KeyError, TypeError, ValueError):
        raise ScanError("The recipe reader's answer didn't make sense. Try a clearer photo.")


def read_recipe(photo_bytes, catalog_names):
    """Return {"name": str, "ingredients": [{"item", "amount", "unit"}]} read from the photos."""
    photos = [prepare_photo(b) for b in photo_bytes[:MAX_PHOTOS]]
    if not photos:
        raise ScanError("Take or choose a photo of the recipe first.")
    data = _ask_model(photos, catalog_names)
    if not isinstance(data, dict):
        raise ScanError("The recipe reader's answer didn't make sense. Try a clearer photo.")
    ingredients = []
    for ing in data.get("ingredients") or []:
        if not isinstance(ing, dict):
            continue
        item = str(ing.get("item") or "").strip()[:100]
        if item:
            ingredients.append({
                "item": item,
                "amount": str(ing.get("amount") or "").strip()[:30],
                "unit": str(ing.get("unit") or "").strip()[:30],
            })
    if not ingredients:
        raise ScanError("I couldn't find any ingredients in that photo. Try a closer, sharper shot of the ingredient list.")
    return {"name": str(data.get("name") or "").strip()[:150], "ingredients": ingredients}
