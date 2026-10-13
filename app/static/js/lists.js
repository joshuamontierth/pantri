/* The lists page. It works offline: everything here goes through the household copy and change
 * queue in household.js, so checking off, adding, editing, deleting and reordering work without a
 * connection and sync when it's back.
 */
(function () {
  "use strict";
  if (!document.body.hasAttribute("data-lists-page")) return;

  const App = window.App;
  const hid = Number(document.body.dataset.household);
  const hh = window.Household({ hid, user: document.body.dataset.user, onChange: () => render(), onStatus: () => renderStatus() });
  const { enqueue, cancel, uid, nowIso } = hh;

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
    if (!hh.data.state) return;
    if (dragging) { renderLater = true; return; }
    view = hh.view();
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
    const { offline, pending: n } = hh.status();
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

  // "Added 3 items from recipes" (plan.js) or "from your list" (listscan.js), left for this page to say.
  try {
    const said = sessionStorage.getItem("sl:toast");
    if (said) {
      sessionStorage.removeItem("sl:toast");
      setTimeout(() => actionToast(said), 200);
    }
  } catch (_) { /* storage blocked */ }

  render();
  renderStatus();
  hh.connect();
  hh.sync();
})();
