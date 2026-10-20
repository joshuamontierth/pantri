/* Adding recipes to the lists, offline-capable.
 *
 * Two steps on one page: choose recipes, then check the ingredients you need and pick a store for
 * each. Everything comes from the household copy in household.js (recipes, catalog rankings, what's
 * already on the lists), so it works without a connection. "Add" queues the items like any other
 * change and opens the lists, which send them. The step and selection live in the URL's #fragment
 * (#step=pick&r=3&m_3=2), so the one saved page works for any recipes.
 */
(function () {
  "use strict";
  if (!document.body.hasAttribute("data-plan-page")) return;

  const App = window.App;
  const hid = Number(document.body.dataset.household);
  const root = document.getElementById("plan");
  const hh = window.Household({ hid, user: document.body.dataset.user, onChange: () => refresh() });

  const ICONS = {
    back: '<path d="M15 6l-6 6 6 6"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
  };
  const icon = (name, size, stroke) => '<svg class="icon" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' +
    (stroke || 1.9) + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const ORDINALS = ["1st", "2nd", "3rd"];
  const ordinal = (i) => ORDINALS[i] || i + 1 + "th";

  // Checks and store picks survive changing a multiplier, keyed by ingredient.
  const choices = {};
  let view = null;

  // ---------- the #fragment ----------
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const ids = [];
    p.getAll("r").forEach((x) => x.split(",").forEach((y) => { const n = Number(y); if (n && !ids.includes(n)) ids.push(n); }));
    const mult = {};
    ids.forEach((id) => { if (p.get("m_" + id)) mult[id] = p.get("m_" + id); });
    // Opened from the meal calendar: its back link returns to that week.
    const back = p.get("back") || "";
    return { step: p.get("step") === "pick" ? "pick" : "choose", ids, mult, back: back.startsWith("/h/" + hid + "/meals") ? back : "" };
  }

  function hashFor(step, ids, mult, back) {
    const p = new URLSearchParams();
    if (step === "pick") p.set("step", "pick");
    ids.forEach((id) => p.append("r", id));
    ids.forEach((id) => { if (mult[id] && mult[id] !== "1") p.set("m_" + id, mult[id]); });
    if (back) p.set("back", back);
    return "#" + p.toString();
  }

  // ---------- step 1: choose recipes ----------
  function renderChoose(sel) {
    const recipes = view.recipes;
    let h = (sel.back ? '<a class="back-link" href="' + esc(sel.back) + '">' + icon("back", 18) + "Meals</a>"
      : '<a class="back-link" href="/h/' + hid + '/recipes">' + icon("back", 18) + "Recipes</a>") +
      '<h1 class="page-title">Choose recipes</h1>';
    if (!recipes.length) {
      root.innerHTML = h + '<p class="lede">No recipes yet. <a href="/h/' + hid + '/recipes/new">Create one</a></p>';
      return;
    }
    h += '<form class="stack" data-choose>' +
      '<label class="search">' + icon("search", 18) + '<input type="search" placeholder="Search recipes" data-filter="#choose-list" aria-label="Search recipes"></label>' +
      '<ul class="rows" id="choose-list">' +
      recipes.map((r) => {
        const n = r.ingredients.length;
        return '<li data-filter-text="' + esc(r.name.toLowerCase()) + '"><label class="row-item check-row">' +
          '<input type="checkbox" name="r" value="' + r.id + '"' + (sel.ids.includes(r.id) ? " checked" : "") + ">" +
          '<span class="grow"><span class="row-title">' + esc(r.name) + '</span><span class="rank-summary">' + n + " ingredient" + (n !== 1 ? "s" : "") + "</span></span></label></li>";
      }).join("") +
      '</ul><div class="sticky-actions"><button class="btn primary grow" data-next></button></div></form>';
    root.innerHTML = h;
    const form = root.querySelector("[data-choose]");
    const button = form.querySelector("[data-next]");
    const update = () => {
      const n = form.querySelectorAll('input[name="r"]:checked').length;
      button.textContent = n ? "Next: " + n + " recipe" + (n === 1 ? "" : "s") : "Choose at least one recipe";
      button.disabled = n === 0;
    };
    form.addEventListener("change", update);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const ids = Array.from(form.querySelectorAll('input[name="r"]:checked')).map((b) => Number(b.value));
      if (ids.length) location.hash = hashFor("pick", ids, sel.mult, sel.back);
    });
    update();
  }

  // ---------- step 2: check ingredients, pick stores ----------
  function selections(sel) {
    const errors = [];
    const out = [];
    sel.ids.forEach((id) => {
      const recipe = view.recipes.find((r) => r.id === id);
      if (!recipe) return;
      const text = (sel.mult[id] || "1").trim();
      let mult = hh.parseAmount(text);
      if (mult == null || !(mult > 0) || mult > 100) {
        errors.push("Couldn't read the multiplier for " + recipe.name + ": “" + text + "”.");
        mult = 1;
      }
      out.push({ recipe, mult, text });
    });
    return { list: out, errors };
  }

  const storeName = (id) => {
    if (id == null) return view.other;
    const s = view.stores.find((x) => x.id === id);
    return s ? s.name : view.other;
  };

  /** One row per ingredient across the recipes, scaled and merged (like the server did). */
  function computeRows(list) {
    const storeIds = new Set(view.stores.map((s) => s.id));
    const catalog = {};
    view.catalog.forEach((c) => { catalog[c.id] = c; });
    const rows = new Map();
    list.forEach(({ recipe, mult }) => recipe.ingredients.forEach((ing) => {
      const key = ing.catalog_id != null ? "c" + ing.catalog_id : "n" + ing.name.toLowerCase();
      let row = rows.get(key);
      if (!row) { row = { key, cid: ing.catalog_id, name: ing.name, parts: [], tags: [] }; rows.set(key, row); }
      if (ing.amount != null) row.parts = hh.combine(row.parts, [[ing.amount * mult, ing.unit || ""]]);
      if (!row.tags.includes(recipe.name)) row.tags.push(recipe.name);
    }));
    rows.forEach((row) => {
      const c = catalog[row.cid];
      row.ranked = (c ? c.ranks : []).filter((id) => storeIds.has(id));
      row.others = view.stores.filter((s) => !row.ranked.includes(s.id));
      row.onList = view.items
        .filter((i) => !i.checked && ((row.cid != null && i.catalogId === row.cid) || i.name.toLowerCase() === row.name.toLowerCase()))
        .map((i) => storeName(i.store) + (i.qty ? ": " + i.qty : ""));
      const choice = choices[row.key] || {};
      const valid = new Set(row.ranked.map(String).concat(row.others.map((s) => String(s.id)), ["none"]));
      row.store = choice.store && valid.has(choice.store) ? choice.store : row.ranked.length ? String(row.ranked[0]) : "none";
      row.on = !!choice.on;
    });
    return Array.from(rows.values());
  }

  function rowsHTML(rows, errors) {
    let h = errors.map((e) => '<p class="alert error">' + esc(e) + "</p>").join("") + '<ul class="pick-list">';
    if (!rows.length) h += '<li class="muted">These recipes have no ingredients.</li>';
    rows.forEach((row) => {
      const qty = hh.formatParts(row.parts);
      const opt = (id, label) => '<option value="' + id + '" data-name="' + esc(storeName(id === "none" ? null : Number(id))) + '"' + (String(id) === row.store ? " selected" : "") + ">" + esc(label) + "</option>";
      h += '<li class="pick-row' + (row.on ? " on" : "") + '" data-key="' + esc(row.key) + '">' +
        '<label class="pick-check"><input type="checkbox" class="box" data-include' + (row.on ? " checked" : "") + ">" +
        '<span class="pick-text"><span class="pick-line"><span class="pick-name">' + esc(row.name) + "</span>" +
        (qty ? '<span class="pick-qty">' + esc(qty) + "</span>" : "") + "</span>" +
        (row.tags.length > 1 ? '<span class="item-tags">for ' + esc(row.tags.join(", ")) + "</span>" : "") +
        (row.onList.length ? '<span class="on-list">Already on ' + esc(row.onList.join(", ")) + "</span>" : "") +
        '</span></label><select class="pick-store" aria-label="Store for ' + esc(row.name) + '">' +
        (row.ranked.length ? '<optgroup label="Your stores for this">' + row.ranked.map((id, i) => opt(String(id), storeName(id) + " · " + ordinal(i))).join("") + "</optgroup>" : "") +
        (row.others.length ? '<optgroup label="Other stores">' + row.others.map((s) => opt(String(s.id), s.name)).join("") + "</optgroup>" : "") +
        opt("none", view.other) + "</select></li>";
    });
    return h + "</ul>";
  }

  let current = null; // {sel, rows}

  function renderPick(sel) {
    const { list, errors } = selections(sel);
    if (!list.length) { location.replace("#"); return; }
    const back = hashFor("choose", sel.ids, sel.mult, sel.back);
    root.innerHTML =
      (sel.back ? '<a class="back-link" href="' + esc(sel.back) + '">' + icon("back", 18) + "Meals</a>"
        : '<a class="back-link" href="' + back + '">' + icon("back", 18) + "Recipes</a>") +
      '<h1 class="page-title">Choose ingredients</h1>' +
      '<div class="plan-recipes">' + list.map(({ recipe, text }) =>
        '<div class="plan-recipe"><span class="row-title">' + esc(recipe.name) + '</span><div class="plan-scale"><label>× ' +
        '<input class="mult" data-recipe="' + recipe.id + '" value="' + esc(text) + '" inputmode="decimal" aria-label="Multiplier for ' + esc(recipe.name) + '"></label></div></div>').join("") +
      "</div>" +
      '<a class="small-link" href="' + back + '">Add or remove recipes</a>' +
      '<div class="pick-tools"><span class="section-label">Check what you need</span><button type="button" class="linklike" data-select-all>Select all</button></div>' +
      '<div id="plan-rows"></div>' +
      '<div class="sticky-actions"><button type="button" class="btn primary grow apply-btn" data-apply><span class="apply-main"></span><span class="apply-sub"></span></button></div>';
    current = { sel };
    renderRows();
  }

  function renderRows() {
    const { list, errors } = selections(current.sel);
    current.rows = computeRows(list);
    document.getElementById("plan-rows").innerHTML = rowsHTML(current.rows, errors);
    updateCount();
  }

  function updateCount() {
    const btn = root.querySelector("[data-apply]");
    if (!btn) return;
    const picked = current.rows.filter((r) => r.on);
    btn.querySelector(".apply-main").textContent = picked.length
      ? "Add " + picked.length + " item" + (picked.length === 1 ? "" : "s") + " to lists" : "Check the items you need";
    btn.disabled = picked.length === 0;
    const perStore = new Map();
    picked.forEach((r) => { const n = storeName(r.store === "none" ? null : Number(r.store)); perStore.set(n, (perStore.get(n) || 0) + 1); });
    btn.querySelector(".apply-sub").textContent = Array.from(perStore, ([name, count]) => name + " " + count).join(" · ");
  }

  root.addEventListener("change", (e) => {
    const row = e.target.closest(".pick-row");
    if (e.target.matches(".mult")) {
      current.sel.mult[e.target.dataset.recipe] = e.target.value.trim() || "1";
      history.replaceState(null, "", hashFor("pick", current.sel.ids, current.sel.mult, current.sel.back));
      renderRows();
      return;
    }
    if (!row) return;
    const key = row.dataset.key;
    const choice = (choices[key] = choices[key] || {});
    if (e.target.matches("[data-include]")) {
      choice.on = e.target.checked;
      row.classList.toggle("on", choice.on);
      if (choice.on) App.buzz(8);
    } else if (e.target.matches(".pick-store")) {
      choice.store = e.target.value;
      if (!choice.on) { choice.on = true; row.classList.add("on"); row.querySelector("[data-include]").checked = true; }
    }
    current.rows.forEach((r) => { if (r.key === key) { r.on = !!choice.on; r.store = choice.store || r.store; } });
    updateCount();
  });

  root.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches(".mult")) { e.preventDefault(); e.target.blur(); }
  });

  root.addEventListener("click", (e) => {
    if (e.target.closest("[data-select-all]")) {
      const all = current.rows.every((r) => r.on);
      current.rows.forEach((r) => { (choices[r.key] = choices[r.key] || {}).on = !all; choices[r.key].store = choices[r.key].store || r.store; });
      renderRows();
      return;
    }
    if (e.target.closest("[data-apply]")) {
      const picked = current.rows.filter((r) => r.on);
      if (!picked.length) return;
      hh.queue(...picked.map((r) => ({
        op_id: hh.uid(), type: "add", ref: hh.uid(), name: r.name, qty: null, parts: r.parts, note: "",
        store: r.store === "none" ? null : Number(r.store), tags: r.tags,
      })));
      try { sessionStorage.setItem("sl:toast", "Added " + picked.length + " item" + (picked.length === 1 ? "" : "s") + " from recipes"); } catch (_) { /* no toast then */ }
      // From the meal calendar: back to the week you were on (it sends the queue too). Otherwise on to the lists.
      location.href = current.sel.back || "/h/" + hid + "#store-" + picked[0].store;
    }
  });

  // ---------- which step ----------
  function show() {
    if (!hh.data.state) {
      root.innerHTML = '<p class="lede">Open this once with a connection so your recipes are saved on this device.</p>';
      return;
    }
    view = hh.view();
    const sel = readHash();
    if (sel.step === "pick" && sel.ids.length) renderPick(sel);
    else { current = null; renderChoose(sel); }
    window.scrollTo(0, 0);
  }

  /** Fresh data arrived: redraw, keeping checks, stores and typed multipliers. */
  function refresh() {
    if (!hh.data.state) return;
    view = hh.view();
    if (current && document.getElementById("plan-rows")) renderRows();
    else if (!current && !root.querySelector("[data-choose] input:checked, [data-choose] input[type=search]:not(:placeholder-shown)")) show();
  }

  window.addEventListener("hashchange", show);
  show();
  hh.sync();
})();
