"""Import a recipe from a link to a recipe web page.

Most recipe sites publish the recipe as schema.org JSON-LD, which gives the exact
ingredient lines and steps. The model then only tidies the ingredient lines into
shopping list entries. Pages without it have their visible text read by the model.
"""

import html
import http.client
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser

from . import directions, quantities, scan
from .scan import ScanError

MAX_PAGE_BYTES = 4 * 1024 * 1024
TIMEOUT = 15
# Some sites refuse requests that don't look like a browser.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/140.0.0.0 Safari/537.36",
    "Accept": "text/html",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # some sites compress even when not asked; keep it to kinds we can undo
}


# ---------- fetching (public addresses only) ----------

class _PrivateAddress(OSError):
    pass


def _public_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *args, **kwargs):
    """socket.create_connection that refuses localhost, LAN and tailnet addresses.

    The checked addresses are the ones connected to, so a second DNS answer can't sneak past.
    """
    host, port = address
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for *_, sockaddr in infos:
        if not ipaddress.ip_address(sockaddr[0].split("%")[0]).is_global:
            raise _PrivateAddress(host)
    error = None
    for family, type_, proto, _, sockaddr in infos:
        sock = socket.socket(family, type_, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            sock.close()
            error = e
    raise error or OSError(f"no address for {host}")


class _HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _public_connection


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _public_connection


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


def _opener():
    # Built by hand so only http(s) is possible, redirects included, and no proxy settings apply.
    opener = urllib.request.OpenerDirector()
    for handler in (_HTTPHandler(), _HTTPSHandler(), urllib.request.HTTPRedirectHandler(),
                    urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener


def normalize_link(text):
    """A clean http(s) URL from what was pasted (which may be share text around a link). ValueError if none."""
    text = (text or "").strip()
    m = re.search(r"https?://\S+", text, re.I)
    if m:
        url = m.group(0)
    elif re.fullmatch(r"(?:[\w-]+\.)+[a-z]{2,}(?:[/?#]\S*)?", text, re.I):
        url = "https://" + text
    else:
        raise ValueError("not a link")
    url = url.rstrip(".,;!'\"”’")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("not a web link")
    url = urllib.parse.urlunsplit(parts._replace(fragment=""))
    if len(url) > 500:
        raise ValueError("too long")
    return url


def _blocked_message():
    if scan.enabled():
        return "That site doesn't let servers read its recipes. Take screenshots of the recipe and use Choose photos instead."
    return "That site doesn't let servers read its recipes."


def _read_body(resp):
    raw = resp.read(MAX_PAGE_BYTES)
    encoding = (resp.headers.get("Content-Encoding") or "").strip().lower()
    if encoding in ("", "identity"):
        return raw
    if encoding not in ("gzip", "x-gzip", "deflate"):
        raise ScanError("Couldn't read that page. Try again, or use screenshots instead.")
    for wbits in ((16 + zlib.MAX_WBITS,) if "gzip" in encoding else (zlib.MAX_WBITS, -zlib.MAX_WBITS)):
        try:
            return zlib.decompressobj(wbits).decompress(raw, MAX_PAGE_BYTES)
        except zlib.error:
            continue
    raise ScanError("Couldn't read that page. Try again, or use screenshots instead.")


def fetch_page(url):
    """(final url, html) of a public web page."""
    opener = _opener()
    for attempt in range(3):
        try:
            with opener.open(urllib.request.Request(url, headers=_HEADERS), timeout=TIMEOUT) as resp:
                if resp.headers.get_content_type() not in ("text/html", "application/xhtml+xml"):
                    raise ScanError("That link isn't a web page. Paste the link to the recipe's page.")
                body = _read_body(resp)
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    page = body.decode(charset, errors="replace")
                except LookupError:
                    page = body.decode("utf-8", errors="replace")
                return resp.geturl(), page
        except urllib.error.HTTPError as e:
            # Bot checks on some big recipe sites turn away a share of requests at random; try again.
            if e.code in (403, 429, 503) and attempt < 2:
                time.sleep(0.8 * (attempt + 1))
                continue
            if e.code in (401, 403, 429, 503):
                raise ScanError(_blocked_message())
            if e.code in (404, 410):
                raise ScanError("That page wasn't found. Check the link.")
            raise ScanError(f"That site returned an error ({e.code}). Try again later.")
        except urllib.error.URLError as e:
            if isinstance(e.reason, _PrivateAddress):
                raise ScanError("That link points to a private address, so it can't be imported.")
            if isinstance(e.reason, socket.gaierror):
                raise ScanError("Couldn't find that website. Check the link.")
            raise ScanError("Couldn't load that page. Check the link and try again.")
        except (http.client.HTTPException, OSError, ValueError, UnicodeError):
            raise ScanError("Couldn't load that page. Check the link and try again.")
    raise ScanError(_blocked_message())


# ---------- schema.org recipe data ----------

_LD_RE = re.compile(r"<script\b[^>]*\btype\s*=\s*[\"']?application/ld\+json[^>]*>(.*?)</script\s*>", re.I | re.S)


def _plain(value):
    """Text from a JSON-LD string, which may carry HTML tags and entities. Keeps line breaks."""
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", str(value), flags=re.I)
    text = html.unescape(html.unescape(re.sub(r"<[^>]+>", " ", text)))
    text = re.sub(r"[ \t]+([.,;:!?)])", r"\1", text)  # "<b>beef</b>." left a space before the period
    return "\n".join(" ".join(line.split()) for line in text.split("\n")).strip()


def _one_line(value):
    return " ".join(_plain(value).split())


def _nodes(node, depth=0):
    if depth > 8:
        return
    if isinstance(node, list):
        for x in node:
            yield from _nodes(x, depth + 1)
    elif isinstance(node, dict):
        yield node
        for v in node.values():
            if isinstance(v, (list, dict)):
                yield from _nodes(v, depth + 1)


def _is_recipe(node):
    types = node.get("@type")
    types = types if isinstance(types, list) else [types]
    return any(isinstance(t, str) and t.rsplit("/", 1)[-1].lower() == "recipe" for t in types)


def _instruction_steps(node, depth=0):
    """Flatten recipeInstructions (text, steps, or sections of steps) into step strings."""
    if depth > 6 or node is None:
        return []
    if isinstance(node, str):
        return [line for line in _plain(node).split("\n") if line]
    if isinstance(node, list):
        return [s for x in node for s in _instruction_steps(x, depth + 1)]
    if isinstance(node, dict):
        if "itemListElement" in node:  # HowToSection
            name = _one_line(node.get("name") or "")
            heading = [name.rstrip(":") + ":"] if name else []
            return heading + _instruction_steps(node["itemListElement"], depth + 1)
        text = node.get("text") or node.get("name") or ""
        return [_one_line(text)] if isinstance(text, str) and text.strip() else []
    return []


def find_recipe(page):
    """{"name", "lines": [ingredient line], "directions"} from a page's JSON-LD, or None."""
    for m in _LD_RE.finditer(page):
        raw = m.group(1).strip()
        raw = re.sub(r"^<!--|-->$", "", raw).strip()
        try:
            data = json.loads(raw, strict=False)
        except ValueError:
            continue
        for node in _nodes(data):
            if not _is_recipe(node):
                continue
            lines = node.get("recipeIngredient") or node.get("ingredients") or []
            if isinstance(lines, str):
                lines = [lines]
            lines = [_one_line(x) for x in lines if isinstance(x, str)]
            lines = [x for x in lines if x][:100]
            if not lines:
                continue
            name = node.get("name") or node.get("headline") or ""
            if isinstance(name, list):
                name = name[0] if name else ""
            return {
                "name": _one_line(name)[:150],
                "lines": lines,
                "directions": directions.join_steps(_instruction_steps(node.get("recipeInstructions"))),
            }
    return None


# ---------- pages without recipe data ----------

class _TextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "head", "nav", "footer", "form", "iframe", "button", "select"}
    BLOCK = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "ul", "ol", "table", "header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_title = False
        self.title = ""
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def page_text(page):
    """(title, visible text) of a page, starting a little before its ingredient list."""
    parser = _TextParser()
    try:
        parser.feed(page)
        parser.close()
    except Exception:  # noqa: BLE001  (html.parser can choke on very broken markup)
        pass
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    text = "\n".join(line for line in lines if line)
    i = text.lower().find("ingredient")
    start = max(0, i - 1500) if i > 0 else 0
    return " ".join(parser.title.split())[:200], text[start:]


# ---------- ingredient lines without the model ----------

_COUNT_UNITS = {"clove", "can", "package", "pkg", "stalk", "bunch", "slice", "head", "sprig", "stick", "jar",
                "bottle", "bag", "box", "loaf", "piece", "container", "envelope", "packet", "pint", "quart", "gallon"}
_PREP_WORDS = re.compile(r"\b(chopped|minced|diced|sliced|grated|shredded|softened|melted|divided|packed|crushed|"
                         r"finely|coarsely|freshly|thinly|roughly|peeled|cubed|beaten|sifted)\b", re.I)
# A bare size in brackets, as in "1 (16 ounce) package bacon". The model tends to fold it into the unit.
_SIZE_RE = re.compile(r"\(\s*[\d./]+(?:\s*-\s*[\d./]+)?\s*-?\s*(?:fl\.?\s*)?[a-z]{1,8}\.?\s*\)", re.I)
_VAGUE_TAIL = re.compile(r"\b(to taste|as needed|optional|for serving|for garnish)\b", re.I)
_AMOUNT_TOKEN = re.compile(r"^(?:\d+(?:[./]\d+)?|[½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]|\d+[½⅓⅔¼¾⅛⅜⅝⅞]|-|–|to)$")


def _known_unit(word):
    unit = quantities.normalize_unit(word)
    return unit in quantities.VOLUME or unit in quantities.WEIGHT or unit in _COUNT_UNITS


def guess_ingredient(line):
    """Rough {"item", "amount", "unit"} from a line like "2 (4 ounce) chicken breasts, cut up"."""
    words = re.sub(r"\([^)]*\)", " ", line).split()
    amount = []
    while words and _AMOUNT_TOKEN.match(words[0]):
        amount.append(words.pop(0))
    unit = ""
    if amount and len(words) > 2 and _known_unit(" ".join(words[:2])):
        unit, words = " ".join(words[:2]), words[2:]
    elif amount and len(words) > 1 and _known_unit(words[0]):
        unit = words.pop(0)
    # What's after a comma is usually prep ("onion, chopped"), unless the name would be one word ("skinless, boneless chicken").
    pieces = [p.strip() for p in " ".join(words).split(",")]
    name = pieces[0] if len(pieces[0].split()) > 1 or len(pieces) == 1 else f"{pieces[0]} {pieces[1]}"
    name = _VAGUE_TAIL.sub(" ", _PREP_WORDS.sub(" ", name))
    item = re.sub(r"^of\s+", "", " ".join(name.split()).strip(" -"), flags=re.I)
    if not item:
        return None
    return {"item": item[:100], "amount": " ".join(amount)[:30], "unit": unit[:30]}


# ---------- the whole import ----------

def import_link(text, catalog_names, recipe_name=None):
    """{"name", "ingredients": [{"item", "amount", "unit"}], "directions", "source_url"} for a recipe link.

    recipe_name is set when adding to an existing recipe (see scan.read_recipe).
    """
    try:
        url = normalize_link(text)
    except ValueError:
        raise ScanError("Paste a link to a recipe page, like https://www.allrecipes.com/recipe/…")
    final_url, page = fetch_page(url)
    try:
        source_url = normalize_link(final_url)
    except ValueError:
        source_url = url

    found = find_recipe(page)
    if found:
        ingredients = []
        if scan.enabled():
            try:
                lines = [" ".join(_SIZE_RE.sub(" ", line).split()) for line in found["lines"]]
                ingredients = scan.read_ingredient_lines(lines, catalog_names)
            except ScanError:
                ingredients = []  # the recipe data is still good; tidy the lines here instead
        if not ingredients:
            ingredients = [g for g in map(guess_ingredient, found["lines"]) if g]
        if not ingredients:
            raise ScanError("I couldn't find any ingredients on that page.")
        return {"name": found["name"], "ingredients": ingredients, "directions": found["directions"],
                "source_url": source_url}

    if not scan.enabled():
        raise ScanError("I couldn't find a recipe on that page.")
    title, body = page_text(page)
    if not body:
        raise ScanError("I couldn't find a recipe on that page.")
    return {**scan.read_page_text(title, body, catalog_names, recipe_name), "source_url": source_url}
