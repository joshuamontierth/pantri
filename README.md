# Shopping List

A self-hosted, mobile-first shopping list server for a household. Each store has its own list, recipes know which stores you buy each ingredient at, and adding recipes drops the ingredients onto the right lists. See [SPEC.md](SPEC.md) for the full feature spec.

- **Households:** shared groups of lists. Invite people by username. A household can have several admins, and you can belong to more than one household. The gear in the top bar opens settings, including switching households.
- **Stores and lists:** one list per store, plus an "Other" list for items without a store. Swipe between stores. Drag to reorder, tap to check off, then "Clear checked" (with undo). New items go to the store you're viewing; suggestions offer a one-tap "+ usual store" when an item normally comes from somewhere else. Changes from other people appear live.
- **Catalog:** each item has a ranked list of stores (1st, 2nd, 3rd…). Filter by store, or by "Other" to find items that still need one; the filter is remembered.
- **Recipes:** ingredients have amounts and units, plus directions and an optional link to where the recipe came from. Pick one or more recipes, scale them with a multiplier, check the ingredients you need, and choose a store for each. They're added to those lists and merged with what's already there (1 cup + 4 tbsp = 1¼ cups, 1 gal + 4 cups = 1¼ gal; US measures).
- **Cooking:** the recipe page shows the directions as numbered steps. Tap a step to mark it done, and turn on **Keep screen on** so the phone doesn't dim while you cook.
- **Import a recipe:** from photos of a recipe card or cookbook (ingredients and directions can be in different photos), or from a link to a recipe website. It opens filled in for you to check and save. See [Importing recipes](#importing-recipes).
- **Works offline:** the lists page and adding recipes to lists keep working without a connection and sync when it's back; other pages open as last seen. See [Offline (website)](#offline-website).
- **Android app:** works offline (in a store with no signal, say) and syncs when it can reach the server, with live updates while it's open. See [Android app](#android-app).
- **Add details to a recipe:** on a recipe you already have, **Add details** reads a photo or link and fills in only what's missing, like directions. See [Adding details](#adding-details-to-an-existing-recipe).
- **Scan a shopping list:** the scan button beside "Add an item" reads a handwritten or printed list, a screenshot, or a list you paste in. Things in your catalog are matched and start at their usual store; new things can join the catalog. You check it all before anything is added. See [Scanning a shopping list](#scanning-a-shopping-list).

## Run it (Docker)

```bash
cp .env.example .env
```

Fill in `.env` (see [Configuration](#configuration)); at least `OLLAMA_URL` if you have an Ollama server for reading photos. Then:

```bash
docker compose up -d --build
```

Open `http://<server-ip>:8000`, sign up, create a household, and add your stores.

- Data lives in the `shopping-data` Docker volume as a single SQLite database (`/data/shopping.db`).
- To reach it away from home, put it behind something like Tailscale or a reverse proxy.
- `COOKIE_SECURE=true` in `.env` limits logins to HTTPS. Leave it `false` if you also use a plain `http://` address, or logging in there will stop working.
- Sign-up is open to anyone who can reach the server, so don't expose it to the open internet without a proxy or VPN in front.

### Upgrading

```bash
docker compose up -d --build
```

Tables are created automatically on start, and new columns are added to existing tables. There is no migration tool for other changes, so back up first.

### Backups

```bash
docker compose exec shopping python -c "import sqlite3; s=sqlite3.connect('/data/shopping.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"
```

```bash
docker compose cp shopping:/data/backup.db ./shopping-backup.db
```

### HTTPS with Tailscale (optional)

If the server is on Tailscale, `tailscale serve` gives the site HTTPS on the machine's tailnet name (`https://<machine>.<tailnet>.ts.net`), with a certificate Tailscale issues and renews. HTTPS is needed for the in-app camera and for the website to work offline; over plain `http://`, taking a photo opens the phone's camera app instead.

```bash
tailscale serve --bg http://127.0.0.1:8000
```

- See what's served: `tailscale serve status`
- Remove only this site's HTTPS: `tailscale serve --https=443 off`
- If the machine serves anything else through `tailscale serve`, don't use `tailscale serve reset`: it removes all of them.

Logins are per address, so log in once on each address you use.

## Importing recipes

On the Recipes page, tap **Import** (it's also on the New recipe page). After a few seconds the recipe editor opens filled in: name, ingredients, directions and, for links, the link. Ingredients that match your catalog use its spelling and stores; new ones are marked so you can tap their stores. Nothing is saved until you press **Save**.

### From photos

- **Take a photo:** over HTTPS this opens a camera inside the app. Take up to 4 shots, tap a thumbnail to drop it, use the flashlight button if your phone has one, then tap **Read recipe**. Over plain HTTP, or if camera access is blocked, it opens the phone's camera app instead. Computers without a camera don't show this option.
- **Choose photos:** pick up to 4 from your photo library. Screenshots work too.

The photos can be different parts of one recipe, like the ingredients on one page and the directions on the next. The photos are straightened, shrunk to 1600px and sent to the model; they aren't stored on the server.

### From a link

**Paste a link** takes a recipe page's address (share text with a link in it works too).

- Most recipe sites (Allrecipes, NYT Cooking, Food Network, BBC Good Food, King Arthur, Serious Eats and many blogs) publish the recipe as structured data. The ingredient lines and steps are taken from that exactly, and the model only tidies the ingredient lines.
- For a page without that data, the model reads the page's text.
- Some sites (Budget Bytes and Sally's Baking Addiction, for example) block servers from reading their pages. Take screenshots of the recipe and use **Choose photos** instead.
- The server only fetches public websites. Links to `localhost`, your home network or tailnet addresses are refused.
- Without a model configured, links still work for sites with structured data, with simpler ingredient parsing.

### Adding details to an existing recipe

On a recipe's page, tap **Add details** and use a photo or a link the same way. The editor opens with only the gaps filled in:

- directions, if the recipe has none;
- ingredients it doesn't have yet (matched by name, so "avocado" and "Avocados" are the same);
- amounts for ingredients that have none;
- the recipe link, if it has none.

Nothing it already has is changed: the name, existing amounts and existing directions stay as they are. Filled-in parts are marked **Added** or **Amount added**, and nothing is saved until you press **Save**. A photo of just the directions works here. If there's nothing new, the recipe page says so.

## Scanning a shopping list

On the lists page, tap the scan button at the left of "Add an item" (it hides while you type). Take a photo of the list, choose photos (up to 4, screenshots work), or paste a list typed in a note or a message. After a few seconds, **Add from your list** shows what was read, one row per item:

- **Matched to your catalog** where it can be: the catalog's name is used ("bananas" finds Banana, "OJ" finds Orange juice), and the store starts at its 1st store. Something not in the catalog that's already on one of your lists starts at that list.
- **New** marks things that aren't in the catalog. Pick a store for each; with **Save new items to the catalog** on (the default), they're saved at that store so they go there next time.
- **Written "…"** shows how a line was written when the name doesn't (an abbreviation or a misspelling), and **Already on …** shows what's on your lists now.
- Fix any name or amount in place. A changed name is matched to the catalog again, and its store follows unless you picked one yourself.
- The same thing written twice is one row with the amounts added up. Crossed-out or checked-off lines, headings ("Costco:", "Produce") and dates are left out.

Uncheck what you don't need, then **Add**. Items merge with what's already on each list, and the lists open at the first store something went to. Reading a list and adding it need a connection (and the model, like photo imports).

### How the model reads recipes

- Ingredient names are what you'd buy, without prep words like "chopped" or "minced". They match catalog items only when it's the same product, so cake flour stays separate from Flour.
- Ranges use the larger number ("4-5 cloves" becomes 5), and package sizes are dropped ("1 (16 ounce) package bacon" becomes 1 package).
- A pinch, dash or "to taste" is left blank, as is any amount that isn't a number, so the recipe always saves.
- "Juice of 1/2 lime" becomes 1/2 Lime; "lime or lemon" keeps the first option; "salt and pepper" becomes two items.
- Water is left out of the ingredients. Directions are copied word for word, one step per numbered step or paragraph.

### Directions format

Directions are plain text. In the editor, number the steps or leave a blank line between them; each becomes a numbered step on the recipe page. A short line ending in a colon, like "For the sauce:", becomes a heading. A single paragraph is shown as written.

### Configuration

Settings live in `.env` (copy [`.env.example`](.env.example); `.env` stays out of git). Docker Compose reads it, and so does the server when you run it locally.

| Variable | Default | |
| --- | --- | --- |
| `PORT` | `8000` | Host port the site is published on. |
| `COOKIE_SECURE` | `false` | `true` when the site is served over HTTPS only. |
| `OLLAMA_URL` | empty | Ollama server, like `http://localhost:11434`. Empty turns off reading photos and lists (recipe links still work). |
| `OLLAMA_MODEL` | `gemma4:26b-a4b-it-qat` | Any Ollama model with vision. |
| `OLLAMA_TIMEOUT` | `300` | Seconds to wait for an answer. |
| `OLLAMA_NUM_CTX` | `8192` | Model context size in tokens. Ollama's default of 4096 is too small for four photos plus directions. |
| `ANDROID_APP_ID` | `com.example.shoppinglist` | The Android app's id, used when building it. |
| `ANDROID_SERVER_URL` | empty | Your server's address, filled in on the app's login screen. |

The server running the app has to be able to reach `OLLAMA_URL`. If it can't, importing from photos shows an error, links fall back to simpler parsing, and recipes can still be typed in by hand.

## Offline (website)

Open the site once with a connection on each device, using the **HTTPS address** (browsers only allow offline support on HTTPS). After that:

- **Lists** work fully offline. Check off, add (with suggestions), edit, delete, clear checked and reorder; changes show straight away and are saved on the device. The header shows **Offline · 3** (three changes waiting) and **Syncing** while they're sent. A small dot on a box marks an item that hasn't reached the server yet.
- **Adding recipes to lists** works offline too: choose recipes, set multipliers, check what you need and pick stores, all from the copy on the device. The items join the same queue and appear on your lists straight away.
- **Recipes, catalog and settings** open as they were last seen (recipes are saved in the background whenever the lists page is open). Changing them and importing need a connection; a page that isn't saved yet shows a "You're offline" page.
- Changes are sent the next time the site is open with a connection. Each one is applied once, so nothing doubles up; a change to an item someone else deleted meanwhile is skipped.
- **Add to Home Screen** (Safari's Share menu, or Chrome's menu) to open it like an app, offline too. On Android, the installed site then appears in the share menu: share a recipe link or photos to it and they're imported, like in the app.
- **Log out** clears the lists and pages saved on that device.

Both pages share [app/static/js/household.js](app/static/js/household.js): the copy of the household, the change queue, and syncing through the same API as the Android app. [lists.js](app/static/js/lists.js) and [plan.js](app/static/js/plan.js) draw the pages, and [sw.js](app/static/sw.js) is the service worker that keeps pages and files cached.

## Android app

A native app (Kotlin + Jetpack Compose) in [`android/`](android/). It does everything the website does, with the same rules and messages: both call the same server code ([app/actions.py](app/actions.py) and the recipe routes), so a check that fails on one fails the same way on the other.

### Install

- **From the website:** gear → **Android app** → **Download the app**, on the phone. The section only appears once the APK has been put on the server (below). Android asks once to allow installs from your browser.
- **Over USB:** `adb install -r android/dist/ShoppingList.apk`

Open it and log in with your server's address (filled in for you when the app was built with `ANDROID_SERVER_URL`), your username and password. The phone has to be able to reach the server, just like the website (for example, with Tailscale on).

### What it does

The same pages as the website:

- **Lists:** swipe between stores, check off, add with catalog suggestions (the one-tap "+ usual store", and "Save to catalog" for new things), edit, move, delete, clear checked (with undo), drag to reorder.
- **Scan a shopping list** from a photo or pasted text, and check the matches and stores before adding, as on the website.
- **Recipes:** search; new, edit, delete, copy to another household; import from a photo (camera or gallery, up to 4) or a link; **Add details** to fill in what a recipe is missing; read ingredients and directions (tap a step when it's done, keep the screen on); add recipes to the lists with multipliers and a store per ingredient.
- **Catalog:** filter by store (remembered), search, add, rename, change store rankings, delete.
- **Settings:** stores (add, rename, reorder, delete), switch or create households, invites, members (roles, password reset, remove), rename, leave or delete; account (change password, log out); sign up.
- **Share to the app:** share a recipe page from Chrome, or recipe photos from Photos, and pick Shopping List; it opens in the editor to check and save.

What works offline is the same as on the website: lists and adding recipes to lists fully, everything else read-only; saving recipes, imports and settings changes need a connection.

### Offline and live updates

- Everything above works without a connection. The phone keeps a copy of the household, and changes are queued on the phone and shown straight away (a small grey dot marks a row that hasn't synced yet).
- When the server is reachable again the queue is sent, oldest first, and the phone takes the server's state. If you close the app first, Android sends the queue in the background once there's a network.
- Every change has an id and the server applies each one once, so a change resent after a dropped connection doesn't count twice. A change to an item someone else deleted meanwhile is skipped.
- While the app is open it holds a live connection, so changes from the website or other phones show up within a second or two. The header shows **Live**, **Offline · 3 waiting**, and so on.

### Build it

Needs the Android SDK (`android/local.properties` points at it) and JDK 17+. The build reads `ANDROID_APP_ID` and `ANDROID_SERVER_URL` from `.env` (environment variables win). Pick your own app id, and keep it: a build with a different id installs as a second app instead of an update.

```bash
cd android && ./gradlew testDebugUnitTest assembleRelease
```

The signed APK is `android/app/build/outputs/apk/release/app-release.apk`; copy it to `android/dist/ShoppingList.apk`. Release signing reads `android/keystore.properties` (`storeFile`, `storePassword`, `keyAlias`, `keyPassword`), which with `release.keystore` stays out of git: back both up, because updates must be signed with the same key. Without it the build falls back to the debug key.

### Put it on the server

Copy `android/dist/ShoppingList.apk` to the server, then from the folder with `docker-compose.yml` there:

```bash
docker compose cp ShoppingList.apk shopping:/data/ShoppingList.apk
```

It lives in the data volume, so it survives rebuilds. Bump `versionCode` in `android/app/build.gradle.kts` for each new version.

### API

The app uses `/api/v1` ([app/routes/api.py](app/routes/api.py)), with a bearer token from `POST /api/v1/login` (the same sessions as the website). The website's lists page uses it too, with its session cookie and CSRF token:

| Endpoint | |
| --- | --- |
| `POST /login`, `POST /logout`, `GET /me` | Token, user and households |
| `GET /h/{id}/state` | The whole household: stores, list items, catalog, recipes (with an ETag) |
| `POST /h/{id}/ops` | A batch of changes (`add`, `check`, `update`, `delete`, `reorder`, `restore`), each with an `op_id`; returns per-change results and fresh state |
| `GET /h/{id}/events` | Live updates (Server-Sent Events) |
| `POST /signup`, `POST /account/password` | Account (the password change also completes an admin reset) |
| `POST /households`, `POST /invites/{id}/accept`, `…/decline` | Households and invites |
| `GET /h/{id}/settings`, `POST /h/{id}/rename`, `…/invites`, `…/members/{id}/role`, `…/reset-password`, `DELETE …/members/{id}`, `POST /h/{id}/leave`, `…/delete` | The settings page |
| `POST /h/{id}/stores`, `PUT/DELETE /h/{id}/stores/{id}`, `POST /h/{id}/stores/reorder` | Stores |
| `POST /h/{id}/catalog`, `PUT/DELETE /h/{id}/catalog/{id}` | Catalog |
| `POST /h/{id}/recipes`, `PUT/DELETE /h/{id}/recipes/{id}`, `GET …/{id}/draft`, `POST …/{id}/copy` | Recipes |
| `POST /h/{id}/recipes/scan` (photos), `POST /h/{id}/recipes/import` (link) | Read a recipe into a draft to review; with `recipe_id`, only fill that recipe's gaps |
| `POST /h/{id}/lists/scan` (`photos`, or `text`) | Read a shopping list into rows to check: `{notice, items: [{name, qty, read_as, catalog_id, ranks, store, on_list}]}` |
| `POST /h/{id}/lists/add` | `{items: [{name, qty, store}], save_new}`: add them (new things join the catalog when `save_new`); returns `{added, store_id, state}` |

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
cp .env.example .env
```

```bash
DATA_DIR=./demo-data .venv/bin/python -m dev.seed_demo
```

```bash
DATA_DIR=./demo-data .venv/bin/uvicorn app.main:app --reload --port 8000
```

The seed script creates users `demo` and `demo2` (the password is in `dev/seed_demo.py`) with stores, catalog items, two recipes, and a few list items. `localhost` counts as secure, so the in-app camera works in local development too.

Run the tests (they ignore `.env` and never call a real Ollama server):

```bash
.venv/bin/python -m pytest -q
```

### Layout

| Path | What |
| --- | --- |
| `app/main.py` | App setup, error handling |
| `app/models.py` | SQLAlchemy models |
| `app/actions.py` | Everything people can do (accounts, households, stores, catalog...), shared by the website and the API |
| `app/services.py` | List merging, moving, store deletion, catalog helpers |
| `app/quantities.py` | Parsing, unit conversion, merging and fraction display |
| `app/routes/api.py` | JSON API for the Android app (sync, live events) |
| `android/` | The Android app; `data/` is sync and offline storage, `ui/` the screens |
| `app/static/js/household.js`, `lists.js`, `plan.js`, `app/static/sw.js` | Offline sync (shared), the lists page, the recipe picker, and the service worker |
| `app/scan.py` | Asking the Ollama model to read recipes (photos, page text, ingredient lines) |
| `app/importer.py` | Fetching recipe links (public addresses only) and reading their recipe data |
| `app/directions.py` | Splitting directions into steps |
| `app/routes/` | Auth, households, lists (+ live events), stores, catalog, recipes (+ import), plan (the recipe picker page) |
| `app/templates/`, `app/static/` | Server-rendered pages (Jinja2 + htmx), CSS and JS |

Live updates use Server-Sent Events broadcast in-process, so run a **single** worker. The Docker image already does.
