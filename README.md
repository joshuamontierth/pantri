# Shopping List

A self-hosted, mobile-first shopping list server for a household. Each store has its own list, recipes know which stores you buy each ingredient at, and adding recipes drops the ingredients onto the right lists. See [SPEC.md](SPEC.md) for the full feature spec.

**Live at https://shopping.example.com** (tailnet only). See [Our setup](#our-setup).

- **Households:** shared groups of lists. Invite people by username. A household can have several admins, and you can belong to more than one household. The gear in the top bar opens settings, including switching households.
- **Stores and lists:** one list per store, plus an "Other" list for items without a store. Swipe between stores. Drag to reorder, tap to check off, then "Clear checked" (with undo). New items go to the store you're viewing; suggestions offer a one-tap "+ usual store" when an item normally comes from somewhere else. Changes from other people appear live.
- **Catalog:** each item has a ranked list of stores (1st, 2nd, 3rd…). Filter by store, or by "Other" to find items that still need one; the filter is remembered.
- **Recipes:** ingredients have amounts and units. Pick one or more recipes, scale them with a multiplier, check the ingredients you need, and choose a store for each. They're added to those lists and merged with what's already there (1 cup + 4 tbsp = 1¼ cups).
- **Scan a recipe:** take or pick photos of a recipe card and a vision model fills in the recipe for you to check and save. See [Scanning recipes](#scanning-recipes).

## Run it (Docker)

```bash
docker compose up -d --build
```

Then open `http://<server-ip>:8000`, sign up, create a household, and add your stores.

- Data lives in the `shopping-data` Docker volume as a single SQLite database (`/data/shopping.db`).
- To reach it away from home, put it behind something like Tailscale or a reverse proxy.
- `COOKIE_SECURE: "true"` in `docker-compose.yml` limits logins to HTTPS. Leave it `"false"` if you also use a plain `http://` address, or logging in there will stop working.
- Sign-up is open to anyone who can reach the server, so don't expose it to the open internet without a proxy or VPN in front.

### Upgrading

```bash
docker compose up -d --build
```

Tables are created automatically on start. There is no migration tool yet, so back up first if a future change alters existing tables.

### Backups

```bash
docker compose exec shopping python -c "import sqlite3; s=sqlite3.connect('/data/shopping.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"
```

```bash
docker compose cp shopping:/data/backup.db ./shopping-backup.db
```

## Our setup

The app runs on the server from `~/shopping_list`, on port 8000.

| Address | Notes |
| --- | --- |
| https://shopping.example.com | Use this one. HTTPS through `tailscale serve`; needed for the in-app camera. |
| http://shopping.example.com:8000 | Plain HTTP, still works. Scanning falls back to the phone's camera app here. |

Logins are per address, so log in once on each.

Deploy the latest `main`:

```bash
ssh you@server 'cd ~/shopping_list && git pull && docker compose up -d --build'
```

### HTTPS (Tailscale serve)

HTTPS comes from Tailscale on the machine's own name. The certificate is issued and renewed by Tailscale.

```bash
tailscale serve --bg http://127.0.0.1:8000
```

The machine may serve other things through `tailscale serve` too.

- Check both are there: `tailscale serve status`
- Remove only the shopping list's HTTPS: `tailscale serve --https=443 off`
- **Never run `tailscale serve reset`**: it also removes everything else `tailscale serve` serves.

## Scanning recipes

On the Recipes page, tap **Scan** (or **From photo** on a new recipe).

- **Take a photo:** over HTTPS this opens a camera inside the app. Take up to 4 shots (front and back of a card), tap a thumbnail to drop it, use the flashlight button if your phone has one, then tap **Read recipe**. Over plain HTTP, or if camera access is blocked, it opens the phone's camera app instead.
- **Choose photos:** pick up to 4 from your photo library.
- On a computer without a camera, Scan opens the file picker directly.

After a few seconds the recipe editor opens filled in. Ingredients that match your catalog use its spelling and stores; new ones are marked so you can tap their stores. Nothing is saved until you press **Save**.

How the model is asked to read cards:

- Ingredient names are what you'd buy, without prep words like "chopped" or "minced".
- Ranges use the larger number ("4-5 cloves" becomes 5).
- A pinch, dash or "to taste" is left blank, as is any amount that isn't a number, so the recipe always saves.
- "Juice of 1/2 lime" becomes 1/2 Lime; "lime or lemon" keeps the first option.
- Water and cooking directions are left out.

The photos are straightened, shrunk to 1600px and sent to the model; they aren't stored on the server.

### Configuration

Set these in `docker-compose.yml`:

| Variable | Default | |
| --- | --- | --- |
| `OLLAMA_URL` | `http://ollama.example.com:11434` | Ollama server. Set to `""` to hide Scan. |
| `OLLAMA_MODEL` | `gemma4:26b-a4b-it-qat` | Any Ollama model with vision. |
| `OLLAMA_TIMEOUT` | `300` | Seconds to wait for an answer. |

The server running the app has to be able to reach it. If it can't, Scan shows an error and recipes can still be typed in by hand.

## Accounts

- Anyone can sign up at `/signup`.
- Forgotten password: a household admin opens the **gear → Members → Manage → Reset password** and sets a temporary password. The user must choose a new one at next login, and their other sessions are logged out.
- Logins last about a year per device.

## Develop

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements-dev.txt
```

```bash
DATA_DIR=./demo-data .venv/bin/python -m dev.seed_demo
```

```bash
DATA_DIR=./demo-data .venv/bin/uvicorn app.main:app --reload --port 8000
```

The seed script creates users `demo` and `demo2` (the password is in `dev/seed_demo.py`) with stores, catalog items, two recipes, and a few list items. `localhost` counts as secure, so the in-app camera works in local development too.

Run the tests (they never call the real Ollama server):

```bash
.venv/bin/python -m pytest -q
```

### Layout

| Path | What |
| --- | --- |
| `app/main.py` | App setup, error handling |
| `app/models.py` | SQLAlchemy models |
| `app/services.py` | List merging, moving, store deletion, catalog helpers |
| `app/quantities.py` | Parsing, unit conversion, merging and fraction display |
| `app/scan.py` | Reading recipes from photos with Ollama |
| `app/routes/` | Auth, households, lists (+ live events), stores, catalog, recipes (+ scan), plan (recipe → lists picker) |
| `app/templates/`, `app/static/` | Server-rendered pages (Jinja2 + htmx), CSS and JS |

Live updates use Server-Sent Events broadcast in-process, so run a **single** worker. The Docker image already does.
