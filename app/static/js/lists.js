/* The lists page, offline-capable.
 *
 * The page keeps a copy of the household and a queue of changes in localStorage. What you see is
 * always that copy with the queued changes applied, so checking off, adding, editing, deleting and
 * reordering all work without a connection. The queue goes to /api/v1/h/<id>/ops whenever the
 * server can be reached; the server applies each change once and sends back the fresh copy.
 * This is the same model as the Android app (android/.../data/LocalView.kt and SyncEngine.kt).
 */
(function () {
  "use strict";
  if (!document.body.hasAttribute("data-lists-page")) return;

  const App = window.App;
  const hid = Number(document.body.dataset.household);
  const KEY = "sl:" + (document.body.dataset.user || "") + ":h" + hid;
  const MAX_BATCH = 400;

  // ---------- quantities (app/quantities.py, for merging and recipe amounts offline) ----------
  const VOLUME = { tsp: 4.92892159375, tbsp: 14.78676478125, "fl oz": 29.5735295625, cup: 236.5882365, pt: 473.176473, qt: 946.352946, gal: 3785.411784, ml: 1, l: 1000 };
  const WEIGHT = { oz: 28.349523125, lb: 453.59237, g: 1, kg: 1000 };
  const FRACTIONS = [[0, ""], [1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [3 / 8, "⅜"], [1 / 2, "½"], [5 / 8, "⅝"], [2 / 3, "⅔"], [3 / 4, "¾"], [7 / 8, "⅞"], [1, ""]];
  const family = (u) => (u in VOLUME ? VOLUME : u in WEIGHT ? WEIGHT : null);
  const compatible = (a, b) => a === b || (family(a) !== null && family(a) === family(b));
  function combine(a, b) {
    const out = a.map((p) => [p[0], p[1]]);
    b.forEach(([amount, unit]) => {
      const t = out.find((p) => compatible(p[1], unit));
      if (t) t[0] += t[1] === unit ? amount : (amount * family(unit)[unit]) / family(t[1])[t[1]];
      else out.push([amount, unit]);
    });
    return out;
  }
  function roundFraction(x) {
    let whole = Math.floor(x);
    let best = FRACTIONS[0];
    FRACTIONS.forEach((f) => { if (Math.abs(f[0] - (x - whole)) < Math.abs(best[0] - (x - whole))) best = f; });
    if (best[0] === 1) whole += 1;
    return [whole, best[1], best[0] === 1 ? 0 : best[0]];
  }
  function formatPart(amount, unit) {
    let num;
    if (unit === "g" || unit === "ml") num = amount >= 10 ? String(Math.round(amount)) : String(Math.round(amount * 10) / 10);
    else {
      const [whole, sym] = roundFraction(amount);
      num = whole === 0 && !sym ? (amount > 0 ? "⅛" : "0") : whole === 0 ? sym : whole + sym;
    }
    if (!unit) return num;
    const [w, , f] = unit === "g" || unit === "ml" ? [amount, "", 0] : roundFraction(amount);
    const plural = w + f > 1 + 1e-9;
    let label;
    if (family(unit)) label = plural && unit === "cup" ? "cups" : unit === "l" ? "L" : unit;
    else label = !plural ? unit : /(s|x|z|ch|sh)$/.test(unit) ? unit + "es" : /[^aeiou]y$/.test(unit) ? unit.slice(0, -1) + "ies" : unit + "s";
    return num + " " + label;
  }
  const formatParts = (parts) => parts.map((p) => formatPart(p[0], p[1])).join(" + ");

  // ---------- the saved copy and the queue ----------
  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || null; } catch (_) { return null; }
  }
  function persist() {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (_) { /* full or blocked: still works this session */ }
  }
  const data = Object.assign({ state: null, at: 0, etag: null, ops: [], refs: {} }, load() || {});
  const embedded = document.getElementById("initial-state");
  if (embedded) {
    // The page carries the server's copy as of when it was made. Use it unless the saved one is newer
    // (the page may have come from the offline cache).
    const at = Number(embedded.dataset.at) || 0;
    if (!data.state || at > (data.at || 0)) {
      try { data.state = JSON.parse(embedded.textContent); data.at = at; data.etag = null; } catch (_) { /* keep saved */ }
    }
  }
  try { localStorage.setItem("sl:last", "/h/" + hid); } catch (_) { /* offline page link */ }

  // Other tabs share the queue, so re-read it before changing it.
  function reloadQueue() {
    const saved = load();
    if (saved) { data.ops = saved.ops || []; data.refs = saved.refs || {}; }
  }

  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
  const nowIso = () => new Date().toISOString().slice(0, 23); // naive UTC, like the server's timestamps
  const parts = (q) => (Array.isArray(q) ? q.filter((p) => Array.isArray(p) && p.length === 2).map((p) => [Number(p[0]), String(p[1])]) : []);

  // ---------- the copy with the queue applied ----------
  function computeView() {
    const st = data.state;
    const refFor = {};
    Object.keys(data.refs).forEach((r) => { refFor[data.refs[r]] = r; });
    const items = st.items.map((i) => ({
      key: i.id, uiKey: refFor[i.id] ? "l" + refFor[i.id] : "s" + i.id, store: i.store_id, name: i.name,
      catalogId: i.catalog_id, parts: parts(i.quantities), qty: i.qty || "", qtyText: i.qty_text || "",
      note: i.note || "", tags: i.tags || [], checked: !!i.checked, checkedAt: i.checked_at, position: i.position, pending: false,
    }));
    const catalogByLower = {};
    st.catalog.forEach((c) => { catalogByLower[c.name.toLowerCase()] = c; });
    const alias = {};
    const resolve = (k) => (typeof k === "number" ? k : k in alias ? alias[k] : k in data.refs ? data.refs[k] : k);
    const indexOf = (k) => { const r = resolve(k); return items.findIndex((i) => i.key === r); };
    const nextPos = (s) => items.filter((i) => i.store === s).reduce((m, i) => Math.max(m, i.position), -1) + 1;
    const twinOf = (s, name, cid, except) => items.findIndex((i) => !i.checked && i.store === s && i.key !== except &&
      ((cid != null && i.catalogId === cid) || i.name.toLowerCase() === name.toLowerCase()));
    function merge(t, src) {
      const p = t.parts && src.parts ? combine(t.parts, src.parts) : null;
      const qty = p ? formatParts(p) : [t.qty, src.qty].filter(Boolean).join(" + ");
      const note = !src.note || t.note.toLowerCase().includes(src.note.toLowerCase()) ? t.note : t.note ? t.note + "; " + src.note : src.note;
      return Object.assign({}, t, { parts: p, qty, qtyText: qty, note, tags: Array.from(new Set(t.tags.concat(src.tags))), pending: true });
    }

    data.ops.forEach((op) => {
      if (op.type === "add") {
        const cat = catalogByLower[op.name.trim().toLowerCase()];
        const name = cat ? cat.name : op.name.trim();
        const p = op.parts ? parts(op.parts) : op.qty ? null : [];
        const incoming = {
          key: op.ref, uiKey: "l" + op.ref, store: op.store, name, catalogId: cat ? cat.id : null, parts: p,
          qty: p ? formatParts(p) : op.qty.trim(), qtyText: op.qty ? op.qty.trim() : p ? formatParts(p) : "",
          note: (op.note || "").trim(), tags: op.tags || [], checked: false, checkedAt: null, position: nextPos(op.store), pending: true,
        };
        const t = twinOf(op.store, name, incoming.catalogId, null);
        if (t >= 0) { items[t] = merge(items[t], incoming); alias[op.ref] = items[t].key; } else items.push(incoming);
      } else if (op.type === "check") {
        const i = indexOf(op.item);
        if (i < 0) return;
        const it = items[i];
        if (op.checked) {
          items[i] = Object.assign({}, it, { checked: true, checkedAt: it.checked ? it.checkedAt : op.at, pending: true });
        } else {
          const un = Object.assign({}, it, { checked: false, checkedAt: null, pending: true });
          const t = twinOf(it.store, it.name, it.catalogId, it.key);
          if (t >= 0) { items[t] = merge(items[t], un); items.splice(i, 1); } else items[i] = un;
        }
      } else if (op.type === "update") {
        const i = indexOf(op.item);
        if (i < 0) return;
        const before = items[i];
        const name = op.name.trim() || before.name;
        const qtyText = (op.qty || "").trim();
        const same = qtyText === before.qtyText;
        let it = Object.assign({}, before, {
          name,
          catalogId: name.toLowerCase() === before.name.toLowerCase() ? before.catalogId : (catalogByLower[name.toLowerCase()] || {}).id || null,
          parts: same ? before.parts : qtyText ? null : [], qty: same ? before.qty : qtyText, qtyText,
          note: (op.note || "").trim(), pending: true,
        });
        items.splice(i, 1);
        if (op.store !== it.store) it = Object.assign(it, { store: op.store, position: nextPos(op.store) });
        const t = it.checked ? -1 : twinOf(it.store, it.name, it.catalogId, it.key);
        if (t >= 0) items[t] = merge(items[t], it); else items.splice(Math.min(i, items.length), 0, it);
      } else if (op.type === "delete") {
        const i = indexOf(op.item);
        if (i >= 0) items.splice(i, 1);
      } else if (op.type === "reorder") {
        const wanted = op.items.map(resolve);
        const onList = items.filter((x) => !x.checked && x.store === op.store).sort((a, b) => a.position - b.position);
        const ordered = [];
        wanted.forEach((k) => { const x = onList.find((y) => y.key === k); if (x && !ordered.includes(x)) ordered.push(x); });
        ordered.concat(onList.filter((x) => !ordered.includes(x))).forEach((x, pos) => {
          const i = items.findIndex((y) => y.key === x.key);
          if (i >= 0) items[i] = Object.assign({}, items[i], { position: pos });
        });
      }
    });
    return { items, stores: st.stores, catalog: st.catalog, other: st.other_label || "Other" };
  }

  // ---------- syncing ----------
  let syncing = false;
  let again = false;
  let offline = false;
  let retryMs = 2000;
  let retryTimer = null;
  const inFlight = new Set();

  // The Date header only has whole seconds; never let a newer copy look older than the one it replaced.
  const serverTime = (resp) => Math.max(Date.parse(resp.headers.get("Date") || "") || Date.now(), (data.at || 0) + 1);

  function httpError(resp, body) {
    const e = new Error((body && body.detail) || "HTTP " + resp.status);
    e.status = resp.status;
    return e;
  }

  async function sync() {
    if (syncing) { again = true; return; }
    syncing = true;
    clearTimeout(retryTimer);
    reloadQueue();
    const batch = data.ops.slice(0, MAX_BATCH);
    batch.forEach((op) => inFlight.add(op.op_id));
    renderStatus();
    try {
      const problems = [];
      if (batch.length) {
        const resp = await fetch("/api/v1/h/" + hid + "/ops", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": App.csrf(), "X-Client-Id": App.clientId },
          body: JSON.stringify({ ops: batch }),
        });
        const body = await resp.json().catch(() => null);
        if (!resp.ok || !body) throw httpError(resp, body);
        reloadQueue();
        const byId = {};
        body.results.forEach((r) => { byId[r.op_id] = r; });
        batch.forEach((op) => {
          const r = byId[op.op_id];
          if (!r) return;
          if (op.type === "add" && r.item_id != null) data.refs[op.ref] = r.item_id;
          if (r.status === "error" && r.message) problems.push(r.message);
        });
        const sent = new Set(batch.map((op) => op.op_id));
        data.ops = data.ops.filter((op) => !sent.has(op.op_id));
        const refKeys = Object.keys(data.refs);
        refKeys.slice(0, Math.max(0, refKeys.length - 300)).forEach((k) => delete data.refs[k]);
        data.state = body.state;
        data.at = serverTime(resp);
        data.etag = null;
      } else {
        const resp = await fetch("/api/v1/h/" + hid + "/state", {
          credentials: "same-origin", cache: "no-store", headers: data.etag ? { "If-None-Match": data.etag } : {},
        });
        if (resp.status !== 304) {
          const body = await resp.json().catch(() => null);
          if (!resp.ok || !body) throw httpError(resp, body);
          data.state = body;
          data.etag = resp.headers.get("ETag");
          data.at = serverTime(resp);
        }
      }
      persist();
      offline = false;
      retryMs = 2000;
      render();
      Array.from(new Set(problems)).forEach((m) => App.toast(m, true));
      if (data.ops.length) again = true;
      warmOfflineCache();
    } catch (e) {
      if (e.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return; }
      if (e.status === 404) { location.href = "/households"; return; }
      if (e.status === 403) { location.reload(); return; } // the page's CSRF token is from an older login
      offline = true;
      if (!document.hidden) {
        retryTimer = setTimeout(sync, retryMs);
        retryMs = Math.min(retryMs * 2, 15000);
      }
    } finally {
      batch.forEach((op) => inFlight.delete(op.op_id));
      syncing = false;
      renderStatus();
      if (again) { again = false; setTimeout(sync, 30); }
    }
  }

  function enqueue(...ops) {
    reloadQueue();
    data.ops.push(...ops);
    persist();
    render();
    sync();
  }

  /** Take back queued changes that haven't been sent (Undo). False if any already went. */
  function cancel(ids) {
    reloadQueue();
    if (ids.some((id) => inFlight.has(id) || !data.ops.some((op) => op.op_id === id))) return false;
    data.ops = data.ops.filter((op) => !ids.includes(op.op_id));
    persist();
    render();
    return true;
  }

  // ---------- rendering ----------
  const panelsEl = document.getElementById("panels");
  const tabsEl = document.getElementById("store-tabs");
  const track = tabsEl.querySelector(".tabs-track");
  const indicator = tabsEl.querySelector(".tab-indicator");
  const pill = document.getElementById("sync-pill");
  let view = null;
  let activeKey = null;
  let storesSig = null;
  let rendered = {};
  let firstRender = true;
  let dragging = false;
  let renderLater = false;

  const ICONS = {
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    more: '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
    list: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
  };
  const icon = (name, size, stroke) => '<svg class="icon" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' +
    stroke + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const keyOf = (storeId) => (storeId == null ? "none" : String(storeId));
  const storeOf = (key) => (key === "none" || key == null ? null : Number(key));
  const listKeys = () => view.stores.map((s) => String(s.id)).concat(["none"]);
  function storeName(key) {
    if (key === "none") return view.other;
    const s = view.stores.find((x) => String(x.id) === key);
    return s ? s.name : view.other;
  }
  const unchecked = (key) => view.items.filter((i) => !i.checked && keyOf(i.store) === key)
    .sort((a, b) => a.position - b.position || (a.uiKey < b.uiKey ? -1 : 1));
  const checked = (key) => view.items.filter((i) => i.checked && keyOf(i.store) === key)
    .sort((a, b) => ((a.checkedAt || "") < (b.checkedAt || "") ? -1 : (a.checkedAt || "") > (b.checkedAt || "") ? 1 : a.uiKey < b.uiKey ? -1 : 1));
  const itemByUi = (uiKey) => view.items.find((i) => i.uiKey === uiKey);

  function itemHTML(it) {
    return '<li class="item' + (it.checked ? " is-checked" : "") + (it.pending ? " is-pending" : "") + '" data-key="' + esc(it.uiKey) + '">' +
      (it.checked ? "" : '<span class="handle" aria-hidden="true" title="Drag to reorder"></span>') +
      '<button type="button" class="item-main" aria-pressed="' + it.checked + '" aria-label="' + (it.checked ? "Uncheck " : "Check off ") + esc(it.name) + '">' +
      '<span class="check" aria-hidden="true">' + icon("check", 16, 3) + "</span>" +
      '<span class="item-body"><span class="item-line"><span class="item-name">' + esc(it.name) + "</span>" +
      (it.qty ? '<span class="item-qty">' + esc(it.qty) + "</span>" : "") + "</span>" +
      (it.note ? '<span class="item-note">' + esc(it.note) + "</span>" : "") +
      (it.tags.length ? '<span class="item-tags">for ' + esc(it.tags.join(", ")) + "</span>" : "") +
      "</span></button>" +
      '<button type="button" class="item-more" aria-label="Edit ' + esc(it.name) + '">' + icon("more", 22, 1.9) + "</button></li>";
  }

  function panelHTML(key) {
    const open = unchecked(key);
    const done = checked(key);
    const name = storeName(key);
    let h = "";
    if (open.length || done.length) {
      const pct = Math.round((100 * done.length) / (open.length + done.length));
      h += '<div class="panel-meta"><span>' + (open.length ? open.length + " to get" : "All done") + (done.length ? " · " + done.length + " in cart" : "") +
        '</span><span class="meter" role="progressbar" aria-label="' + esc(name) + ' progress" aria-valuemin="0" aria-valuemax="' + (open.length + done.length) +
        '" aria-valuenow="' + done.length + '"><span style="width: ' + pct + '%"></span></span></div>';
    }
    if (!open.length && !done.length) {
      h += '<div class="state"><span class="state-mark">' + icon("list", 28, 1.8) + '</span><p class="state-title">Nothing on the ' + esc(name) +
        ' list</p><p class="state-text">Type an item below, or <a href="/h/' + hid + '/plan">add ingredients from recipes</a>.</p></div>';
    } else if (!open.length) {
      h += '<div class="state state-done"><span class="state-mark">' + icon("check", 30, 2.6) + '</span><p class="state-title">Everything is in the cart</p>' +
        '<button type="button" class="btn primary" data-clear>Clear ' + done.length + " checked item" + (done.length !== 1 ? "s" : "") + "</button></div>";
    }
    h += '<ul class="items items-open">' + open.map(itemHTML).join("") + "</ul>";
    if (done.length) {
      h += '<div class="cart-bar"><span class="section-label">In cart</span>' +
        (open.length ? '<button type="button" class="linklike" data-clear>Clear checked</button>' : "") + "</div>" +
        '<ul class="items items-done">' + done.map(itemHTML).join("") + "</ul>";
    }
    return h;
  }

  function buildLists() {
    const keep = activeKey;
    const tabs = listKeys().map((key) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "tab";
      b.setAttribute("role", "tab");
      b.dataset.key = key;
      b.innerHTML = '<span class="tab-name">' + esc(storeName(key)) + '</span><span class="count" id="count-' + key + '"></span>';
      return b;
    });
    track.replaceChildren(...tabs, indicator);
    panelsEl.replaceChildren(...listKeys().map((key) => {
      const p = document.createElement("section");
      p.className = "panel";
      p.id = "panel-" + key;
      p.dataset.key = key;
      p.setAttribute("role", "tabpanel");
      p.setAttribute("aria-label", storeName(key));
      return p;
    }));
    rendered = {};
    return keep;
  }

  function renderPanel(key) {
    const el = document.getElementById("panel-" + key);
    if (!el) return;
    const html = panelHTML(key);
    if (rendered[key] === html) return;
    const before = new Set(Array.from(el.querySelectorAll(".item")).map((li) => li.dataset.key + (li.classList.contains("is-checked") ? ":c" : "")));
    el.innerHTML = html;
    rendered[key] = html;
    if (!firstRender) {
      el.querySelectorAll(".item").forEach((li) => {
        if (!before.has(li.dataset.key + (li.classList.contains("is-checked") ? ":c" : ""))) li.classList.add("arrive");
      });
    }
    makeSortable(el.querySelector(".items-open"), key);
  }

  function render() {
    if (!data.state) return;
    if (dragging) { renderLater = true; return; }
    view = computeView();
    const sig = JSON.stringify(view.stores.map((s) => [s.id, s.name]));
    let keep = activeKey;
    let rebuilt = false;
    if (sig !== storesSig) { keep = buildLists(); storesSig = sig; rebuilt = true; }
    listKeys().forEach(renderPanel);
    listKeys().forEach((key) => {
      const c = document.getElementById("count-" + key);
      if (c) c.textContent = unchecked(key).length || "";
    });
    const names = document.getElementById("catalog-names");
    if (names) names.replaceChildren(...view.catalog.map((c) => { const o = document.createElement("option"); o.value = c.name; return o; }));
    if (firstRender || rebuilt || !document.getElementById("panel-" + activeKey)) {
      const fromHash = (location.hash.match(/^#store-(\w+)$/) || [])[1];
      setActive(firstRender ? fromHash || keep : keep, { scroll: true, instant: true });
    } else {
      updateTarget();
    }
    firstRender = false;
    updateIndicator();
  }

  function renderStatus() {
    if (!pill) return;
    const n = data.ops.length;
    let text = "";
    if (offline) text = n ? "Offline · " + n : "Offline";
    else if (n) text = "Syncing";
    pill.textContent = text;
    pill.title = offline
      ? "Can't reach the server." + (n ? " " + n + " change" + (n === 1 ? "" : "s") + " saved here, waiting to sync." : "")
      : n ? "Sending your changes" : "";
    pill.setAttribute("aria-label", pill.title || text);
    pill.hidden = !text;
    pill.classList.toggle("is-offline", offline);
  }

  // ---------- drag to reorder ----------
  function makeSortable(ul, key) {
    if (!ul || typeof Sortable === "undefined") return;
    Sortable.create(ul, {
      handle: ".handle",
      animation: 160,
      ghostClass: "sortable-ghost",
      chosenClass: "sortable-chosen",
      onStart: () => { dragging = true; App.buzz(8); },
      onEnd: (evt) => {
        dragging = false;
        if (evt.oldIndex !== evt.newIndex) {
          const items = Array.from(ul.children).map((li) => itemByUi(li.dataset.key)).filter(Boolean).map((i) => i.key);
          enqueue({ op_id: uid(), type: "reorder", store: storeOf(key), items });
        } else if (renderLater) {
          renderLater = false;
          render();
        }
      },
    });
  }

  // ---------- tabs and swiping ----------
  const panelList = () => Array.from(panelsEl.querySelectorAll(".panel"));
  const tabList = () => Array.from(track.querySelectorAll(".tab"));
  const qaForm = document.getElementById("quick-add");
  const qaName = qaForm.querySelector(".qa-name");
  const qaQty = qaForm.querySelector(".qa-qty");
  const suggestBox = document.getElementById("qa-suggest");

  function updateIndicator() {
    const tl = tabList();
    if (!tl.length || !indicator) return;
    const f = Math.max(0, Math.min(tl.length - 1, panelsEl.scrollLeft / (panelsEl.clientWidth || 1)));
    const i = Math.floor(f);
    const t = f - i;
    const a = tl[i];
    const b = tl[Math.min(i + 1, tl.length - 1)];
    indicator.style.width = a.offsetWidth + (b.offsetWidth - a.offsetWidth) * t + "px";
    indicator.style.transform = "translateX(" + (a.offsetLeft + (b.offsetLeft - a.offsetLeft) * t) + "px)";
  }

  function updateTarget() {
    const name = storeName(activeKey);
    qaName.placeholder = name && name.length <= 14 ? "Add to " + name : "Add an item";
    if (!suggestBox.hidden) renderSuggestions();
  }

  function setActive(key, opts) {
    opts = opts || {};
    if (!document.getElementById("panel-" + key)) key = listKeys()[0];
    activeKey = key;
    tabList().forEach((t) => t.setAttribute("aria-selected", t.dataset.key === key ? "true" : "false"));
    const t = track.querySelector('.tab[data-key="' + key + '"]');
    if (t) tabsEl.scrollTo({ left: t.offsetLeft - tabsEl.clientWidth / 2 + t.clientWidth / 2, behavior: opts.instant ? "auto" : "smooth" });
    if (opts.scroll) panelsEl.scrollTo({ left: document.getElementById("panel-" + key).offsetLeft, behavior: opts.instant ? "auto" : "smooth" });
    history.replaceState(null, "", "#store-" + key);
    updateTarget();
  }

  tabsEl.addEventListener("click", (e) => {
    const t = e.target.closest(".tab");
    if (t) setActive(t.dataset.key, { scroll: true });
  });
  let scrollTimer = null;
  let rafPending = false;
  panelsEl.addEventListener("scroll", () => {
    if (!rafPending) {
      rafPending = true;
      requestAnimationFrame(() => { rafPending = false; updateIndicator(); });
    }
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      const p = panelList()[Math.round(panelsEl.scrollLeft / panelsEl.clientWidth)];
      if (p && p.dataset.key !== activeKey) { setActive(p.dataset.key); App.buzz(4); }
    }, 90);
  }, { passive: true });
  window.addEventListener("resize", () => {
    const p = document.getElementById("panel-" + activeKey);
    if (p) panelsEl.scrollLeft = p.offsetLeft;
    updateIndicator();
  });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(updateIndicator);

  // ---------- toasts with an action ----------
  function actionToast(text, label, onAction) {
    const el = document.createElement("div");
    el.className = "toast";
    const span = document.createElement("span");
    span.textContent = text;
    el.appendChild(span);
    if (label) {
      const b = document.createElement(typeof onAction === "string" ? "a" : "button");
      b.className = "toast-action";
      b.textContent = label;
      if (typeof onAction === "string") b.href = onAction;
      else { b.type = "button"; b.addEventListener("click", onAction); }
      el.appendChild(b);
    }
    document.getElementById("toasts").appendChild(el);
  }

  /** Undo a delete or clear: drop the queued deletes, or add the items back if they already went. */
  function undo(opIds, items) {
    if (cancel(opIds)) return;
    const ops = [];
    items.forEach((it) => {
      const ref = uid();
      ops.push({ op_id: uid(), type: "add", ref, name: it.name, qty: it.parts ? null : it.qtyText, parts: it.parts, note: it.note, store: it.store, tags: it.tags });
      if (it.checked) ops.push({ op_id: uid(), type: "check", item: ref, checked: true, at: nowIso() });
    });
    enqueue(...ops);
  }

  // ---------- check off, clear, edit ----------
  panelsEl.addEventListener("click", (e) => {
    const clear = e.target.closest("[data-clear]");
    if (clear) {
      const done = checked(clear.closest(".panel").dataset.key);
      if (!done.length) return;
      const ops = done.map((it) => ({ op_id: uid(), type: "delete", item: it.key }));
      enqueue(...ops);
      actionToast("Cleared " + done.length + " item" + (done.length === 1 ? "" : "s"), "Undo", () => undo(ops.map((o) => o.op_id), done));
      return;
    }
    const more = e.target.closest(".item-more");
    if (more) {
      const it = itemByUi(more.closest(".item").dataset.key);
      if (it) openSheet(it);
      return;
    }
    const btn = e.target.closest(".item-main");
    if (!btn || btn._pending) return;
    const li = btn.closest(".item");
    const it = itemByUi(li.dataset.key);
    if (!it) return;
    btn._pending = true;
    const checking = !it.checked;
    li.classList.add(checking ? "checking" : "unchecking");
    if (checking) App.buzz(12);
    // Let the pen stroke land before the item moves to "In cart".
    setTimeout(() => enqueue({ op_id: uid(), type: "check", item: it.key, checked: checking, at: nowIso() }), checking ? 280 : 120);
  });

  const sheet = document.getElementById("sheet");
  const sheetBody = document.getElementById("sheet-body");

  function openSheet(it) {
    const options = listKeys().map((k) => '<option value="' + k + '"' + (k === keyOf(it.store) ? " selected" : "") + ">" + esc(storeName(k)) + "</option>").join("");
    sheetBody.innerHTML =
      '<form class="sheet-form" data-sheet-form><div class="sheet-head"><h2 id="sheet-title" tabindex="-1">' + esc(it.name) + "</h2>" +
      (it.tags.length ? '<span class="sheet-sub">for ' + esc(it.tags.join(", ")) + "</span>" : "") + "</div>" +
      '<label class="field"><span class="field-label">Name</span><input name="name" value="' + esc(it.name) + '" maxlength="100" required list="catalog-names" autocomplete="off"></label>' +
      '<div class="two-col"><label class="field"><span class="field-label">Quantity</span><input name="qty" value="' + esc(it.qtyText) + '" placeholder="2 lb"></label>' +
      '<label class="field"><span class="field-label">List</span><select name="store">' + options + "</select></label></div>" +
      '<label class="field"><span class="field-label">Note</span><input name="note" value="' + esc(it.note) + '" maxlength="300" placeholder="the organic kind"></label>' +
      '<div class="sheet-actions"><button class="btn primary grow">Save</button>' +
      '<button type="button" class="btn icon-btn danger" data-delete aria-label="Delete ' + esc(it.name) + '">' + icon("trash", 20, 1.9) + "</button></div></form>";
    const form = sheetBody.querySelector("form");
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const f = new FormData(form);
      enqueue({ op_id: uid(), type: "update", item: it.key, name: String(f.get("name")).trim() || it.name, qty: String(f.get("qty")), note: String(f.get("note")), store: storeOf(String(f.get("store"))) });
      sheet.close();
    });
    form.querySelector("[data-delete]").addEventListener("click", () => {
      const op = { op_id: uid(), type: "delete", item: it.key };
      enqueue(op);
      sheet.close();
      actionToast("Deleted " + it.name, "Undo", () => undo([op.op_id], [it]));
    });
    sheet.showModal();
    sheetBody.querySelector("#sheet-title").focus();
  }

  sheet.addEventListener("close", () => { sheetBody.replaceChildren(); sheet.style.transform = ""; });
  sheet.addEventListener("click", (e) => {
    if (e.target !== sheet) return;
    const r = sheet.getBoundingClientRect();
    if (e.clientY < r.top || e.clientY > r.bottom || e.clientX < r.left || e.clientX > r.right) sheet.close();
  });
  let dragStart = null;
  sheet.addEventListener("pointerdown", (e) => {
    if (!e.target.closest(".sheet-grabber, .sheet-head")) return;
    dragStart = e.clientY;
    sheet.setPointerCapture(e.pointerId);
  });
  sheet.addEventListener("pointermove", (e) => {
    if (dragStart !== null) sheet.style.transform = "translateY(" + Math.max(0, e.clientY - dragStart) + "px)";
  });
  sheet.addEventListener("pointerup", (e) => {
    if (dragStart === null) return;
    const dy = e.clientY - dragStart;
    dragStart = null;
    if (dy > 90) sheet.close(); else sheet.style.transform = "";
  });

  // ---------- quick add with suggestions ----------
  let suggestions = [];
  let activeIdx = -1;

  function usualKey(c) {
    const r = (c.ranks || []).find((id) => view.stores.some((s) => s.id === id));
    return r == null ? "none" : String(r);
  }

  function hideSuggestions() {
    suggestBox.hidden = true;
    suggestBox.replaceChildren();
    suggestions = [];
    activeIdx = -1;
  }

  function renderSuggestions() {
    const q = qaName.value.trim();
    if (!q || document.activeElement !== qaName || !view) { hideSuggestions(); return; }
    const ql = q.toLowerCase();
    const starts = [];
    const contains = [];
    view.catalog.forEach((c) => {
      const n = c.name.toLowerCase();
      if (n.startsWith(ql)) starts.push(c); else if (n.includes(ql)) contains.push(c);
    });
    suggestions = starts.concat(contains).slice(0, 4);
    if (!suggestions.length) { hideSuggestions(); return; }
    if (activeIdx >= suggestions.length) activeIdx = -1;
    // Each row adds to this list; if the item usually comes from another store, a second button sends it there.
    suggestBox.replaceChildren(...suggestions.map((c, i) => {
      const row = document.createElement("div");
      row.className = "sg-row" + (i === activeIdx ? " active" : "");
      const main = document.createElement("button");
      main.type = "button";
      main.className = "sg-main";
      main.dataset.index = String(i);
      main.setAttribute("aria-label", "Add " + c.name + " to " + storeName(activeKey));
      const at = c.name.toLowerCase().indexOf(ql);
      const strong = document.createElement("b");
      strong.textContent = c.name.slice(at, at + ql.length);
      main.append(c.name.slice(0, at), strong, c.name.slice(at + ql.length));
      row.appendChild(main);
      const usual = usualKey(c);
      if (usual !== "none" && usual !== activeKey) {
        const alt = document.createElement("button");
        alt.type = "button";
        alt.className = "sg-alt";
        alt.dataset.index = String(i);
        alt.dataset.store = usual;
        alt.setAttribute("aria-label", "Add " + c.name + " to " + storeName(usual) + " instead");
        alt.innerHTML = icon("plus", 14, 2.6);
        alt.append(storeName(usual));
        row.appendChild(alt);
      }
      return row;
    }));
    suggestBox.hidden = false;
  }

  function addItem(name, key) {
    name = name.trim().slice(0, 100);
    if (!name) return;
    const qty = qaQty.value.trim();
    const before = view.items.find((i) => !i.checked && keyOf(i.store) === key && i.name.toLowerCase() === name.toLowerCase());
    enqueue({ op_id: uid(), type: "add", ref: uid(), name, qty: qty || null, parts: null, note: "", store: storeOf(key), tags: [] });
    const known = view.catalog.some((c) => c.name.toLowerCase() === name.toLowerCase());
    const text = (before ? "Updated " : "Added ") + name + (before ? " on " : " to ") + storeName(key);
    if (known) actionToast(text);
    else actionToast(text, "Save to catalog", "/h/" + hid + "/catalog/new?name=" + encodeURIComponent(name) + "&next=" + encodeURIComponent("/h/" + hid + "#store-" + key));
    qaName.value = "";
    qaQty.value = "";
    hideSuggestions();
    App.buzz(10);
    qaName.focus();
  }

  function pickSuggestion(i, key) {
    const c = suggestions[i];
    if (c) addItem(c.name, key || activeKey);
  }

  qaForm.addEventListener("submit", (e) => {
    e.preventDefault();
    if (activeIdx >= 0 && !suggestBox.hidden) pickSuggestion(activeIdx);
    else addItem(qaName.value, activeKey);
  });
  qaName.addEventListener("input", () => { activeIdx = -1; renderSuggestions(); });
  qaName.addEventListener("focus", renderSuggestions);
  qaName.addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== qaName) hideSuggestions(); }, 120));
  qaName.addEventListener("keydown", (e) => {
    if (suggestBox.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = suggestions.length;
      activeIdx = e.key === "ArrowDown" ? (activeIdx + 1) % n : (activeIdx - 1 + n) % n;
      renderSuggestions();
    } else if (e.key === "Escape") {
      hideSuggestions();
    }
  });
  // Keep the keyboard up: tapping a suggestion must not blur the input.
  suggestBox.addEventListener("pointerdown", (e) => e.preventDefault());
  suggestBox.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-index]");
    if (b) pickSuggestion(Number(b.dataset.index), b.dataset.store);
  });

  // ---------- live updates ----------
  let source = null;
  function connect() {
    if (source) source.close();
    source = new EventSource("/h/" + hid + "/events");
    source.onopen = () => sync(); // (re)connected: catch up
    source.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.origin && msg.origin === App.clientId) return;
      if (msg.kind === "deleted") location.href = "/households";
      else sync();
    };
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    retryMs = 2000;
    if (!source || source.readyState === EventSource.CLOSED) connect();
    sync();
  });
  window.addEventListener("online", () => { retryMs = 2000; sync(); });
  window.addEventListener("offline", () => { offline = true; renderStatus(); });
  window.addEventListener("storage", (e) => { if (e.key === KEY) { reloadQueue(); render(); renderStatus(); } });

  // ---------- keep the other pages ready for offline use ----------
  function warmOfflineCache() {
    const ctrl = navigator.serviceWorker && navigator.serviceWorker.controller;
    if (!ctrl || !data.state) return;
    const stamp = "sl:warm:" + hid;
    try {
      if (Date.now() - Number(localStorage.getItem(stamp) || 0) < 6 * 3600 * 1000) return;
      localStorage.setItem(stamp, String(Date.now()));
    } catch (_) { return; }
    const base = "/h/" + hid;
    const urls = [base + "/recipes", base + "/catalog", base + "/settings"]
      .concat(data.state.recipes.map((r) => base + "/recipes/" + r.id));
    ctrl.postMessage({ type: "warm", urls });
  }

  render();
  renderStatus();
  connect();
  sync();
})();
