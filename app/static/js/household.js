/* The household as this device knows it, shared by the pages that work offline (lists.js, plan.js).
 *
 * A copy of the household and a queue of changes live in localStorage. What a page shows is
 * always that copy with the queued changes applied, so it works without a connection. The queue
 * goes to /api/v1/h/<id>/ops whenever the server can be reached; the server applies each change
 * once and sends back the fresh copy. This is the same model as the Android app
 * (android/.../data/LocalView.kt and SyncEngine.kt).
 */
(function () {
  "use strict";

  /** opts: {hid, user, onChange() when what to show changed, onStatus() when online/queue state changed} */
  window.Household = function (opts) {
  const App = window.App;
  const hid = opts.hid;
  const KEY = "sl:" + (opts.user || "") + ":h" + hid;
  const MAX_BATCH = 400;
  const onChange = () => opts.onChange && opts.onChange();
  const onStatus = () => opts.onStatus && opts.onStatus();

  // ---------- quantities (app/quantities.py, for merging and recipe amounts offline) ----------
  const VOLUME = { tsp: 4.92892159375, tbsp: 14.78676478125, "fl oz": 29.5735295625, cup: 236.5882365, pt: 473.176473, qt: 946.352946, gal: 3785.411784, ml: 1, l: 1000 };
  const WEIGHT = { oz: 28.349523125, lb: 453.59237, g: 1, kg: 1000 };
  const FRACTIONS = [[0, ""], [1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [3 / 8, "⅜"], [1 / 2, "½"], [5 / 8, "⅝"], [2 / 3, "⅔"], [3 / 4, "¾"], [7 / 8, "⅞"], [1, ""]];
  const SAME_PLURAL = ["dozen", "each"]; // "3 dozen", not "3 dozens"
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
    else label = !plural || SAME_PLURAL.includes(unit) ? unit : /(s|x|z|ch|sh)$/.test(unit) ? unit + "es" : /[^aeiou]y$/.test(unit) ? unit.slice(0, -1) + "ies" : unit + "s";
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
    return { items, stores: st.stores, catalog: st.catalog, recipes: st.recipes || [], other: st.other_label || "Other" };
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
    onStatus();
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
      onChange();
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
      onStatus();
      if (again) { again = false; setTimeout(sync, 30); }
    }
  }

  function enqueue(...ops) {
    reloadQueue();
    data.ops.push(...ops);
    persist();
    onChange();
    sync();
  }

  /** Take back queued changes that haven't been sent (Undo). False if any already went. */
  function cancel(ids) {
    reloadQueue();
    if (ids.some((id) => inFlight.has(id) || !data.ops.some((op) => op.op_id === id))) return false;
    data.ops = data.ops.filter((op) => !ids.includes(op.op_id));
    persist();
    onChange();
    return true;
  }

  /** Add changes to the queue without showing or sending them yet (the next page will). */
  function queue(...ops) {
    reloadQueue();
    data.ops.push(...ops);
    persist();
  }

  // ---------- live updates ----------
  let source = null;
  let live = false;
  function connect() {
    live = true;
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
    if (live && (!source || source.readyState === EventSource.CLOSED)) connect();
    sync();
  });
  window.addEventListener("online", () => { retryMs = 2000; sync(); });
  window.addEventListener("offline", () => { offline = true; onStatus(); });
  window.addEventListener("storage", (e) => { if (e.key === KEY) { reloadQueue(); onChange(); onStatus(); } });

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
    const urls = [base + "/meals", base + "/recipes", base + "/plan", base + "/catalog", base + "/settings"]
      .concat(data.state.recipes.map((r) => base + "/recipes/" + r.id));
    ctrl.postMessage({ type: "warm", urls });
  }

  function parseAmount(text) {
    const UNI = { "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8" };
    let t = String(text || "").replace(/⁄/g, "/");
    Object.keys(UNI).forEach((ch) => { t = t.split(ch).join(" " + UNI[ch]); });
    t = t.trim();
    if (!t) return null;
    const m = t.match(/^(\d+\s+\d+\s*\/\s*\d+|\d+\s*\/\s*\d+|\d+\.\d*|\.\d+|\d+)$/);
    if (!m) return NaN;
    let total = 0;
    for (const part of m[1].replace(/\s*\/\s*/g, "/").split(/\s+/)) {
      if (part.includes("/")) {
        const [n, d] = part.split("/").map(Number);
        if (!d) return NaN;
        total += n / d;
      } else total += Number(part);
    }
    return total;
  }

  return {
    get data() { return data; },
    view: computeView,
    status: () => ({ offline, pending: data.ops.length, syncing }),
    enqueue, cancel, queue, sync, connect,
    uid, nowIso, combine, formatParts, parseAmount,
  };
  };
})();
