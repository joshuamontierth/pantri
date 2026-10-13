# Shopping List Server: Spec

## Platform
- **Stack:** Python (FastAPI) + SQLite, server-rendered pages (Jinja2 + HTMX), light JS for drag-and-drop and swipe tabs.
- **Deploy:** Docker Compose on a home server/LAN; SQLite file in a mounted volume; auto-restart.
- **UI:** Mobile-first, plain website (no PWA/offline). Dark mode follows system setting.
- **Live sync:** Changes by other household members appear within ~1–2s without refresh (Server-Sent Events).

## Accounts
- Open sign-up page: username + password. Usernames unique, case-insensitive. Passwords hashed (argon2/bcrypt).
- Sessions last ~1 year per device until logout.
- Users can change their own password.
- **Password reset:** a household admin can set a temporary password for any member of that household; the member must change it at next login. (Accepted risk: trusted family.)

## Households
- A user can belong to **multiple households** and switches between them.
- After sign-up with no households: prompt to create one or accept a pending invite.
- **Invite by username** → invitee sees pending invite → accept/decline.
- **Roles:** admin(s) and members. Multiple admins allowed.
  - Admins: invite/remove members, promote/demote admins, reset member passwords, delete household.
  - Members: everything else (lists, stores, catalog, recipes).
  - The last admin can't leave or demote themselves without promoting someone else first.

## Stores & Lists
- Stores are **per household**; any number. Create, rename, reorder (drag), delete.
- **Exactly one list per store**, plus a permanent **"Other"** list (items without a store).
- Deleting a store: its unchecked items move to "Other"; the store is removed from every ingredient's ranking and lower ranks shift up.
- **Main screen:** swipeable tabs, one per store (plus "Other"), with quick-add always visible.
- **List items:** name, optional quantity + unit, optional free-text note, recipe tags (e.g. `Eggs 3, for Pancakes, Quiche`).
- **Ordering:** order added (new at bottom); drag-and-drop to reorder.
- **Check off:** crosses out and moves to bottom; tap again to uncheck; **"Clear checked"** button removes checked items.
- Items can be moved between store lists.
- **Adding items manually:**
  - Quick-add goes to the list on screen (autocomplete from catalog).
  - A suggestion whose 1st-choice store is a different store also offers "+ <that store>" to send it there.
  - Typing a name not in the catalog offers to save it to the catalog with store rankings.
- **Scan a shopping list** (button beside quick-add, hidden while typing; needs the model and a connection):
  - From photos (camera or library, up to 4) of a handwritten or printed list or a screenshot, or from pasted text.
  - Crossed-out or checked-off lines, headings and dates are left out; misspellings and abbreviations are written out; "x2" and ranges become amounts (the larger number).
  - Review page ("Add from your list"): one row per item, all checked, with editable name and quantity and a store dropdown like the recipe picker's. The same item written twice is one row with amounts combined.
  - Matching: the catalog's name when it's the same product (same name, or the same but for a plural, after the model maps wording like "OJ" to a catalog name). Matched items start at their 1st-ranked store; items not in the catalog start at the list they're already on, else "Other". A renamed row is matched again; a store picked by hand stays.
  - Rows show "New" (not in the catalog), "Written “…”" (when the written line doesn't show the name) and "Already on <store>: <qty>".
  - Add → each checked row is added to its store's list, merging per the rules below. With **Save new items to the catalog** (on by default), new items are created in the catalog ranked at the store picked (no ranking for "Other").
- **Merging:** adding an item that already exists *unchecked* on that list merges into one line (quantities summed, recipe tags combined). If the existing line is checked, a new line is created.

## Ingredient Catalog (per household)
- Each item has a name and an ordered store ranking (1st, 2nd, 3rd, … any number; may be empty → routes to "Other").
- Catalog page: create, rename, edit rankings, delete (blocked if used by a recipe; shows which).

## Recipes (per household)
- Fields: name, ingredients (catalog item + optional quantity + unit), directions (free text, shown as numbered steps), optional link to the source.
- **Import** from photos (camera or library, up to 4, read by a vision model) or from a link to a recipe page (schema.org data, else the page text). Opens the editor prefilled; nothing is saved until Save.
- **Add details** to an existing recipe from a photo or link: fills in only what's missing (directions, new ingredients, blank amounts, the link) and never changes what's there. Opens the editor with the additions marked; nothing is saved until Save.
- Typing an ingredient not in the catalog creates it inline, with store rankings settable right in the recipe editor.
- **Copy recipe** to another household you belong to: ingredients match that household's catalog by name, or are created there with no rankings.

## Add Recipe(s) → Lists
- Select **one or more recipes**; each has its own multiplier (×2, ×½, …).
- One combined picker; ingredients shared across selected recipes are combined into one row.
- Every ingredient starts **unchecked**; check the ones you need.
- Each row has a store dropdown: that ingredient's ranked stores in order (default = primary), then other household stores, then "Other".
- Rows show if the item is already on a list (e.g. "already on Costco: 6 each").
- Confirm → items are added to each store's list, merging per the rules above, tagged with source recipe(s).

## Quantities & Units
- Units: common list (tsp, tbsp, cup, pt, qt, gal, fl oz, ml, L, oz, lb, g, kg, each; US measures) + free-text custom units (can, bunch, clove…). Quantity is optional (e.g. "salt").
- Merging converts within a unit type (volume ↔ volume, weight ↔ weight), shown in the existing line's unit. Custom units only merge with the same unit. Incompatible units stay on one line: `2 cups + 1 lb`.
- Display as kitchen fractions (1½ cups, ¾ tsp), rounded to common fractions. Custom units are pluralized ("3 cans"), except "dozen" and "each".

## Android app
- Native client for the same server and accounts; the website stays fully usable.
- Lists and recipes work offline from a copy kept on the phone. Changes queue on the phone and sync when the server is reachable (also in the background after the app is closed); each change is applied once by the server.
- Live updates while the app is open.
- Same features and behavior as the website (accounts, households, members, stores, catalog, recipes with import and add details, adding recipes to lists, scanning a shopping list), backed by the same server code. Sharing a link or photos to the app (or to the installed website) imports a recipe.

## Offline website
- The lists page works offline from a copy kept in the browser, with the same change queue and sync as the Android app; it syncs when the server is reachable and shows live updates when online.
- Adding recipes to lists (choose recipes, multipliers, ingredients, stores) also works offline; the items join the same queue.
- A service worker caches pages and files: recipes, catalog and settings open read-only offline. Needs the HTTPS address. Logging out clears the device's saved data.

