(function () {
  "use strict";

  const OTHER = "Other"; // label of the store-less list (services.OTHER_LABEL)
  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  // Identifies this page so we can ignore live events caused by our own actions.
  const clientId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  const buzz = (ms) => { try { if (navigator.vibrate) navigator.vibrate(ms || 10); } catch (_) { /* unsupported */ } };

  // ---------- toasts ----------
  const toastBox = document.getElementById("toasts");

  function dismissToast(el) {
    if (!el || el._gone) return;
    el._gone = true;
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 260);
  }

  function armToast(el) {
    if (!el || el._armed) return;
    el._armed = true;
    setTimeout(() => dismissToast(el), el.querySelector(".toast-action") ? 7000 : 3200);
  }

  function toast(text, isError) {
    const el = document.createElement("div");
    el.className = "toast" + (isError ? " error" : "");
    const span = document.createElement("span");
    span.textContent = text;
    el.appendChild(span);
    toastBox.appendChild(el);
  }

  if (toastBox) {
    new MutationObserver((muts) => {
      muts.forEach((m) => m.addedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        if (n.classList.contains("toast")) armToast(n);
        if (n.querySelectorAll) n.querySelectorAll(".toast").forEach(armToast);
      }));
    }).observe(toastBox, { childList: true, subtree: true });
    // Tapping Undo / Save to catalog: the action runs (htmx or link), then the toast goes.
    toastBox.addEventListener("click", (e) => {
      const action = e.target.closest(".toast-action");
      if (action) setTimeout(() => dismissToast(action.closest(".toast")), 60);
    });
    const initial = document.getElementById("initial-toast");
    if (initial) toastBox.appendChild(initial.content.cloneNode(true));
  }

  // ---------- htmx wiring ----------
  document.addEventListener("htmx:configRequest", (e) => {
    e.detail.headers["X-CSRF-Token"] = csrf();
    e.detail.headers["X-Client-Id"] = clientId;
  });
  document.addEventListener("htmx:responseError", (e) => {
    const xhr = e.detail.xhr;
    const text = xhr && xhr.responseText && xhr.responseText.length < 400 && !xhr.responseText.trim().startsWith("{")
      ? xhr.responseText : "Something went wrong (" + (xhr ? xhr.status : "?") + ").";
    toast(text, true);
  });
  document.addEventListener("htmx:sendError", () => toast("Can't reach the server. Check your connection.", true));

  function postForm(url, pairs) {
    return fetch(url, {
      method: "POST",
      headers: {
        "X-CSRF-Token": csrf(),
        "X-Client-Id": clientId,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams(pairs),
    }).then((r) => { if (!r.ok) toast("Couldn't save the new order.", true); return r; })
      .catch(() => toast("Can't reach the server.", true));
  }

  // ---------- small helpers used on several pages ----------
  document.addEventListener("submit", (e) => {
    const msg = e.target.dataset && e.target.dataset.confirm;
    if (msg && !window.confirm(msg)) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  document.addEventListener("input", (e) => {
    const sel = e.target.dataset && e.target.dataset.filter;
    if (!sel) return;
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll(sel + " > [data-filter-text]").forEach((li) => {
      li.hidden = q !== "" && !li.dataset.filterText.includes(q);
    });
  });

  // ---------- rank picker (tap stores in order) ----------
  function setRanks(picker, ids) {
    picker.querySelector("[data-rank-input]").value = ids.join(",");
    picker.querySelectorAll(".chip").forEach((chip) => {
      const r = ids.indexOf(chip.dataset.store) + 1;
      chip.classList.toggle("ranked", r > 0);
      chip.setAttribute("aria-pressed", r > 0 ? "true" : "false");
      chip.querySelector(".rank-badge").textContent = r || "";
    });
  }
  function getRanks(picker) {
    const v = picker.querySelector("[data-rank-input]").value;
    return v ? v.split(",") : [];
  }
  function rankSummary(picker) {
    const names = getRanks(picker).map((id) => {
      const chip = picker.querySelector('.chip[data-store="' + id + '"] .chip-name');
      return chip ? chip.textContent : "?";
    });
    return names.length ? names.join(" › ") : OTHER;
  }
  document.addEventListener("click", (e) => {
    const chip = e.target.closest(".rank-picker .chip");
    if (!chip) return;
    const picker = chip.closest(".rank-picker");
    const id = chip.dataset.store;
    const ids = getRanks(picker);
    setRanks(picker, ids.includes(id) ? ids.filter((x) => x !== id) : ids.concat([id]));
    buzz(6);
    picker.dispatchEvent(new CustomEvent("ranks-change", { bubbles: true }));
  });

  // ---------- drag to reorder ----------
  let dragging = false;
  const afterDrag = [];

  function initSortables(root) {
    if (typeof Sortable === "undefined") return;
    const lists = root.matches && root.matches("[data-sortable], [data-sortable-stores]")
      ? [root] : Array.from(root.querySelectorAll("[data-sortable], [data-sortable-stores]"));
    lists.forEach((ul) => {
      if (ul._sortable) return;
      const isStores = ul.hasAttribute("data-sortable-stores");
      ul._sortable = Sortable.create(ul, {
        handle: ".handle",
        animation: 160,
        ghostClass: "sortable-ghost",
        chosenClass: "sortable-chosen",
        onStart: () => { dragging = true; buzz(8); },
        onEnd: (evt) => {
          dragging = false;
          if (evt.oldIndex !== evt.newIndex) {
            const ids = Array.from(ul.children).map((li) => li.dataset.id).filter(Boolean);
            postForm(ul.dataset.reorderUrl, ids.map((id) => [isStores ? "store" : "item", id]));
          }
          afterDrag.splice(0).forEach((fn) => fn());
        },
      });
    });
  }

  // Runs for the initial page and for every piece of content htmx swaps in.
  if (window.htmx) htmx.onLoad(initSortables);
  else document.addEventListener("DOMContentLoaded", () => initSortables(document.body));

  // ---------- lists page ----------
  function initListsPage() {
    const hid = document.body.dataset.household;
    const panels = document.getElementById("panels");
    const tabs = document.getElementById("store-tabs");
    const indicator = tabs.querySelector(".tab-indicator");
    const targetInput = document.getElementById("qa-target");
    const qaForm = document.getElementById("quick-add");
    const qaName = qaForm.querySelector(".qa-name");
    const qaQty = qaForm.querySelector(".qa-qty");
    const sheet = document.getElementById("sheet");
    const sheetBody = document.getElementById("sheet-body");
    let activeKey = null;

    const panelList = () => Array.from(panels.querySelectorAll(".panel"));
    const tabList = () => Array.from(tabs.querySelectorAll(".tab"));
    const panelEl = (key) => document.getElementById("panel-" + key);
    const tabEl = (key) => tabs.querySelector('.tab[data-key="' + key + '"]');
    const allKeys = () => panelList().map((p) => p.dataset.key);
    const tabName = (key) => { const t = tabEl(key); return t ? t.querySelector(".tab-name").textContent : ""; };

    // ----- tabs, swiping and the sliding underline -----
    function updateIndicator() {
      const tl = tabList();
      if (!tl.length || !indicator) return;
      const f = Math.max(0, Math.min(tl.length - 1, panels.scrollLeft / (panels.clientWidth || 1)));
      const i = Math.floor(f), t = f - i;
      const a = tl[i], b = tl[Math.min(i + 1, tl.length - 1)];
      const left = a.offsetLeft + (b.offsetLeft - a.offsetLeft) * t;
      const width = a.offsetWidth + (b.offsetWidth - a.offsetWidth) * t;
      indicator.style.width = width + "px";
      indicator.style.transform = "translateX(" + left + "px)";
    }

    // New items go to the list you're looking at; the box says which.
    function updateTarget() {
      const name = tabName(activeKey);
      targetInput.value = activeKey || "none";
      qaName.placeholder = name && name.length <= 14 ? "Add to " + name : "Add an item";
      if (!suggestBox.hidden) renderSuggestions();
    }

    function setActive(key, opts) {
      opts = opts || {};
      if (!panelEl(key)) key = allKeys()[0];
      activeKey = key;
      tabList().forEach((t) => t.setAttribute("aria-selected", t.dataset.key === key ? "true" : "false"));
      const t = tabEl(key);
      if (t) tabs.scrollTo({ left: t.offsetLeft - tabs.clientWidth / 2 + t.clientWidth / 2, behavior: opts.instant ? "auto" : "smooth" });
      if (opts.scroll) panels.scrollTo({ left: panelEl(key).offsetLeft, behavior: opts.instant ? "auto" : "smooth" });
      history.replaceState(null, "", "#store-" + key);
      updateTarget();
    }

    tabs.addEventListener("click", (e) => {
      const t = e.target.closest(".tab");
      if (t) setActive(t.dataset.key, { scroll: true });
    });

    let scrollTimer = null;
    let rafPending = false;
    panels.addEventListener("scroll", () => {
      if (!rafPending) {
        rafPending = true;
        requestAnimationFrame(() => { rafPending = false; updateIndicator(); });
      }
      clearTimeout(scrollTimer);
      scrollTimer = setTimeout(() => {
        const p = panelList()[Math.round(panels.scrollLeft / panels.clientWidth)];
        if (p && p.dataset.key !== activeKey) { setActive(p.dataset.key); buzz(4); }
      }, 90);
    }, { passive: true });

    window.addEventListener("resize", () => {
      const p = panelEl(activeKey);
      if (p) panels.scrollLeft = p.offsetLeft;
      updateIndicator();
    });
    document.addEventListener("htmx:afterSettle", updateIndicator);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(updateIndicator);

    // ----- check off: instant feedback, then sync -----
    panels.addEventListener("click", (e) => {
      const btn = e.target.closest(".item-main");
      if (!btn || btn._pending) return;
      btn._pending = true;
      const li = btn.closest(".item");
      const checking = !li.classList.contains("is-checked");
      li.classList.add(checking ? "checking" : "unchecking");
      if (checking) buzz(12);
      const id = li.dataset.id;
      // Let the pen stroke land before the item moves to "In cart".
      setTimeout(() => {
        htmx.ajax("POST", btn.dataset.toggleUrl, { swap: "none", target: "body" }).then(() => {
          const moved = panels.querySelector('.item[data-id="' + id + '"]');
          if (moved && moved !== li) moved.classList.add("arrive");
          if (li.isConnected) { li.classList.remove("checking", "unchecking"); btn._pending = false; }
        });
      }, checking ? 280 : 120);
    });

    // ----- edit sheet -----
    document.addEventListener("htmx:afterSwap", (e) => {
      if (e.detail.target === sheetBody && !sheet.open) sheet.showModal();
    });
    document.addEventListener("htmx:afterRequest", (e) => {
      if (sheet.open && sheet.contains(e.detail.elt) && e.detail.successful) sheet.close();
    });
    sheet.addEventListener("close", () => { sheetBody.replaceChildren(); sheet.style.transform = ""; });
    sheet.addEventListener("click", (e) => {
      if (e.target !== sheet) return;
      const r = sheet.getBoundingClientRect();
      if (e.clientY < r.top || e.clientY > r.bottom || e.clientX < r.left || e.clientX > r.right) sheet.close();
    });
    // Drag the grabber down to dismiss.
    let dragStart = null;
    sheet.addEventListener("pointerdown", (e) => {
      if (!e.target.closest(".sheet-grabber, .sheet-head")) return;
      dragStart = e.clientY;
      sheet.setPointerCapture(e.pointerId);
    });
    sheet.addEventListener("pointermove", (e) => {
      if (dragStart === null) return;
      sheet.style.transform = "translateY(" + Math.max(0, e.clientY - dragStart) + "px)";
    });
    sheet.addEventListener("pointerup", (e) => {
      if (dragStart === null) return;
      const dy = e.clientY - dragStart;
      dragStart = null;
      if (dy > 90) sheet.close();
      else sheet.style.transform = "";
    });

    // ----- quick add with suggestions -----
    const catalog = JSON.parse((document.getElementById("catalog-suggest") || {}).textContent || "[]");
    const suggestBox = document.getElementById("qa-suggest");
    let suggestions = [];
    let activeIdx = -1;

    function hideSuggestions() {
      suggestBox.hidden = true;
      suggestBox.replaceChildren();
      suggestions = [];
      activeIdx = -1;
    }

    function renderSuggestions() {
      const q = qaName.value.trim();
      if (!q || document.activeElement !== qaName) { hideSuggestions(); return; }
      const ql = q.toLowerCase();
      const starts = [], contains = [];
      catalog.forEach((c) => {
        const n = c.n.toLowerCase();
        if (n.startsWith(ql)) starts.push(c);
        else if (n.includes(ql)) contains.push(c);
      });
      suggestions = starts.concat(contains).slice(0, 4).map((c) => ({ name: c.n, entry: c }));
      if (!suggestions.length) { hideSuggestions(); return; }
      if (activeIdx >= suggestions.length) activeIdx = -1;

      // Each row adds the item to this list. If the item usually comes from another store,
      // a second button sends it there instead.
      suggestBox.replaceChildren(...suggestions.map((s, i) => {
        const row = document.createElement("div");
        row.className = "sg-row" + (i === activeIdx ? " active" : "");
        const main = document.createElement("button");
        main.type = "button";
        main.className = "sg-main";
        main.dataset.index = String(i);
        main.setAttribute("aria-label", "Add " + s.name + " to " + tabName(activeKey));
        const at = s.name.toLowerCase().indexOf(ql);
        const strong = document.createElement("b");
        strong.textContent = s.name.slice(at, at + ql.length);
        main.append(s.name.slice(0, at), strong, s.name.slice(at + ql.length));
        row.appendChild(main);
        if (s.entry.s !== "none" && s.entry.s !== activeKey) {
          const alt = document.createElement("button");
          alt.type = "button";
          alt.className = "sg-alt";
          alt.dataset.index = String(i);
          alt.dataset.store = s.entry.s;
          alt.setAttribute("aria-label", "Add " + s.name + " to " + s.entry.sn + " instead");
          alt.insertAdjacentHTML("afterbegin", '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>');
          alt.append(s.entry.sn);
          row.appendChild(alt);
        }
        return row;
      }));
      suggestBox.hidden = false;
    }

    function pickSuggestion(i, storeKey) {
      const s = suggestions[i];
      if (!s) return;
      qaName.value = s.name;
      hideSuggestions();
      if (storeKey) targetInput.value = storeKey;
      qaForm.requestSubmit(); // htmx reads the form values right here
      targetInput.value = activeKey || "none";
    }

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
      } else if (e.key === "Enter" && activeIdx >= 0) {
        e.preventDefault();
        pickSuggestion(activeIdx);
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

    qaForm.addEventListener("htmx:afterRequest", (e) => {
      if (e.detail.elt !== qaForm || !e.detail.successful) return;
      qaName.value = "";
      qaQty.value = "";
      hideSuggestions();
      buzz(10);
      qaName.focus();
    });

    const fromHash = (location.hash.match(/^#store-(\w+)$/) || [])[1];
    setActive(fromHash || allKeys()[0], { scroll: true, instant: true });
    updateIndicator();

    // ----- live refresh -----
    const pending = new Set();
    let reloadPending = false;

    function refresh(keys) {
      if (dragging) { keys.forEach((k) => pending.add(k)); return; }
      if (keys.length) {
        htmx.ajax("GET", "/h/" + hid + "/lists/refresh?stores=" + encodeURIComponent(keys.join(",")), { swap: "none", target: "body" });
      }
    }
    function refreshAll() { refresh(allKeys()); }

    function reloadPage() {
      if (dragging || sheet.open || document.activeElement === qaName || document.activeElement === qaQty) {
        reloadPending = true;
      } else {
        location.reload();
      }
    }

    function flushPending() {
      if (reloadPending && !dragging && !sheet.open) { reloadPending = false; location.reload(); return; }
      if (pending.size && !dragging) {
        const keys = Array.from(pending);
        pending.clear();
        refresh(keys);
      }
    }
    sheet.addEventListener("close", () => setTimeout(flushPending, 50));
    qaName.addEventListener("blur", () => setTimeout(flushPending, 300));

    let source = null;
    let everOpened = false;
    function connect() {
      if (source) source.close();
      source = new EventSource("/h/" + hid + "/events");
      source.onopen = () => {
        if (everOpened) refreshAll(); // reconnected: catch up on anything missed
        everOpened = true;
      };
      source.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (_) { return; }
        if (msg.origin && msg.origin === clientId) return;
        if (msg.kind === "lists") {
          if (dragging) afterDrag.push(flushPending);
          refresh(msg.stores || []);
        } else if (msg.kind === "stores") {
          reloadPage();
        } else if (msg.kind === "deleted") {
          location.href = "/households";
        }
      };
    }
    connect();

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) return;
      if (!source || source.readyState === EventSource.CLOSED) {
        everOpened = true; // the new connection's onopen refreshes everything
        connect();
      } else {
        refreshAll();
      }
    });
  }

  // ---------- recipe editor ----------
  function initRecipeEditor(form) {
    const catalog = JSON.parse(document.getElementById("catalog-data").textContent || "{}");
    const rowsEl = document.getElementById("ing-rows");
    const tmpl = document.getElementById("ing-row-template");

    function updateRow(row, nameChanged) {
      const name = row.querySelector(".ing-name").value.trim();
      const known = catalog[name.toLowerCase()];
      const status = row.querySelector(".ing-status");
      const summary = row.querySelector(".ing-summary");
      const ranksBox = row.querySelector(".ing-ranks");
      const toggle = row.querySelector("[data-toggle-ranks]");
      const dirty = row.querySelector("[data-dirty]");
      const picker = row.querySelector(".rank-picker");
      if (!name) {
        status.hidden = true;
        ranksBox.hidden = true;
        return;
      }
      status.hidden = false;
      if (known) {
        if (nameChanged && row._lastKnown !== name.toLowerCase()) {
          setRanks(picker, known.ranks.map(String));
          dirty.value = "0";
          ranksBox.hidden = true;
        }
        row._lastKnown = name.toLowerCase();
        summary.textContent = rankSummary(picker) + (dirty.value === "1" ? " (changed)" : "");
        toggle.hidden = false;
        toggle.textContent = ranksBox.hidden ? "Change" : "Done";
      } else {
        row._lastKnown = null;
        summary.textContent = "New item. Tap its stores in order of preference.";
        toggle.hidden = true;
        ranksBox.hidden = false;
      }
    }

    function addRow(focus) {
      const frag = tmpl.content.cloneNode(true);
      const row = frag.querySelector("[data-ing-row]");
      rowsEl.appendChild(frag);
      updateRow(row, false);
      if (focus) row.querySelector(".ing-name").focus();
      return row;
    }

    rowsEl.querySelectorAll("[data-ing-row]").forEach((row) => {
      const name = row.querySelector(".ing-name").value.trim().toLowerCase();
      if (catalog[name]) row._lastKnown = name;
      updateRow(row, false);
    });

    form.addEventListener("input", (e) => {
      if (e.target.matches(".ing-name")) updateRow(e.target.closest("[data-ing-row]"), true);
    });
    form.addEventListener("ranks-change", (e) => {
      const row = e.target.closest("[data-ing-row]");
      if (!row) return;
      row.querySelector("[data-dirty]").value = "1";
      updateRow(row, false);
    });
    form.addEventListener("click", (e) => {
      if (e.target.closest("[data-add-row]")) { addRow(true); return; }
      const remove = e.target.closest("[data-remove-row]");
      if (remove) {
        const row = remove.closest("[data-ing-row]");
        if (rowsEl.querySelectorAll("[data-ing-row]").length > 1) row.remove();
        else { row.querySelectorAll("input:not([type=hidden])").forEach((i) => { i.value = ""; }); updateRow(row, true); }
        return;
      }
      const toggle = e.target.closest("[data-toggle-ranks]");
      if (toggle) {
        const row = toggle.closest("[data-ing-row]");
        const box = row.querySelector(".ing-ranks");
        box.hidden = !box.hidden;
        updateRow(row, false);
      }
    });
    // Enter inside an ingredient's text boxes moves to the next row instead of submitting.
    form.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !e.target.matches("input") || !e.target.closest("[data-ing-row]")) return;
      e.preventDefault();
      const rows = Array.from(rowsEl.querySelectorAll("[data-ing-row]"));
      const idx = rows.indexOf(e.target.closest("[data-ing-row]"));
      if (idx === rows.length - 1) addRow(true);
      else rows[idx + 1].querySelector(".ing-name").focus();
    });
  }

  // ---------- choosing recipes ----------
  function initChoose(button) {
    const form = button.form;
    const update = () => {
      const n = form.querySelectorAll('input[name="r"]:checked').length;
      button.textContent = n ? "Next: " + n + " recipe" + (n === 1 ? "" : "s") : "Choose at least one recipe";
      button.disabled = n === 0;
    };
    form.addEventListener("change", update);
    update();
  }

  // ---------- recipes to lists picker ----------
  function initPlanPicker(form) {
    const applyBtn = form.querySelector("[data-apply-button]");
    const applyMain = applyBtn.querySelector(".apply-main");
    const applySub = applyBtn.querySelector("[data-apply-sub]");

    function updateCount() {
      const rows = Array.from(form.querySelectorAll(".pick-row")).filter((r) => r.querySelector('input[name="include"]').checked);
      const n = rows.length;
      applyMain.textContent = n ? "Add " + n + " item" + (n === 1 ? "" : "s") + " to lists" : "Check the items you need";
      applyBtn.disabled = n === 0;
      const perStore = new Map();
      rows.forEach((r) => {
        const opt = r.querySelector(".pick-store").selectedOptions[0];
        const name = opt ? opt.dataset.name : OTHER;
        perStore.set(name, (perStore.get(name) || 0) + 1);
      });
      applySub.textContent = Array.from(perStore, ([name, count]) => name + " " + count).join(" · ");
    }

    form.addEventListener("change", (e) => {
      if (e.target.matches(".mult")) htmx.trigger("#plan-rows", "recalc");
      if (e.target.matches('input[name="include"]')) {
        e.target.closest(".pick-row").classList.toggle("on", e.target.checked);
        if (e.target.checked) buzz(8);
      }
      if (e.target.matches(".pick-store")) {
        const box = e.target.closest(".pick-row").querySelector('input[name="include"]');
        if (!box.checked) { box.checked = true; e.target.closest(".pick-row").classList.add("on"); }
      }
      updateCount();
    });
    form.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.matches(".mult")) { e.preventDefault(); e.target.blur(); }
    });
    form.querySelector("[data-select-all]").addEventListener("click", () => {
      const boxes = Array.from(form.querySelectorAll('input[name="include"]'));
      const all = boxes.every((b) => b.checked);
      boxes.forEach((b) => { b.checked = !all; b.closest(".pick-row").classList.toggle("on", !all); });
      updateCount();
    });
    // Rows are re-rendered when scaling changes. Keep the user's latest checks and store
    // choices (a tap can land while the request is in flight, so trust the DOM, not the request).
    let saved = null;
    document.addEventListener("htmx:beforeSwap", (e) => {
      if (e.detail.target.id !== "plan-rows") return;
      saved = {};
      form.querySelectorAll(".pick-row").forEach((row) => {
        const box = row.querySelector('input[name="include"]');
        saved[box.value] = { checked: box.checked, store: row.querySelector(".pick-store").value };
      });
    });
    document.addEventListener("htmx:afterSwap", (e) => {
      if (e.detail.target.id !== "plan-rows") return;
      if (saved) {
        form.querySelectorAll(".pick-row").forEach((row) => {
          const box = row.querySelector('input[name="include"]');
          const prev = saved[box.value];
          if (!prev) return;
          box.checked = prev.checked;
          row.classList.toggle("on", prev.checked);
          const sel = row.querySelector(".pick-store");
          if (sel.querySelector('option[value="' + prev.store + '"]')) sel.value = prev.store;
        });
        saved = null;
      }
      updateCount();
    });
    updateCount();
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (document.body.hasAttribute("data-lists-page")) initListsPage();
    const editor = document.querySelector("[data-recipe-editor]");
    if (editor) initRecipeEditor(editor);
    const choose = document.querySelector("[data-choose-button]");
    if (choose) initChoose(choose);
    const plan = document.querySelector("[data-plan-form]");
    if (plan) initPlanPicker(plan);
  });
})();
