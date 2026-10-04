# Shopping List

A self-hosted, mobile-first shopping list server for a household. Each store has its own list, recipes know which stores you buy each ingredient at, and adding recipes drops the ingredients onto the right lists. See [SPEC.md](SPEC.md) for the full feature spec.

- **Households:** shared groups of lists. Invite people by username. A household can have several admins, and you can belong to more than one household.
- **Stores and lists:** one list per store, plus an "Other" list for items without a store. Swipe between stores. Drag to reorder, tap to check off, then "Clear checked" (with undo). New items go to the store you're viewing; suggestions offer a one-tap "+ usual store" when an item normally comes from somewhere else. Changes from other people appear live.
- **Catalog:** each item has a ranked list of stores (1st, 2nd, 3rd…). The 1st store is the default.
- **Recipes:** ingredients have amounts and units. Pick one or more recipes, scale them by servings or a multiplier, check the ingredients you need, and choose a store for each. They're added to those lists and merged with what's already there (1 cup + 4 tbsp = 1¼ cups).

## Run it (Docker)

```bash
docker compose up -d --build
```

Then open `http://<server-ip>:8000`, sign up, create a household, and add your stores.

- Data lives in the `shopping-data` Docker volume as a single SQLite database (`/data/shopping.db`).
- To reach it away from home, put it behind something like Tailscale or a reverse proxy. If you serve it over HTTPS, set `COOKIE_SECURE: "true"` in `docker-compose.yml`.
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

## Accounts

- Anyone can sign up at `/signup`.
- Forgotten password: a household admin opens **household menu → Members → Manage → Reset password** and sets a temporary password. The user must choose a new one at next login, and their other sessions are logged out.
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

The seed script creates users `demo` and `demo2` (the password is in `dev/seed_demo.py`) with stores, catalog items, two recipes, and a few list items.

Run the tests:

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
| `app/routes/` | Auth, households, lists (+ live events), stores, catalog, recipes, plan (recipe → lists picker) |
| `app/templates/`, `app/static/` | Server-rendered pages (Jinja2 + htmx), CSS and JS |

Live updates use Server-Sent Events broadcast in-process, so run a **single** worker. The Docker image already does.
