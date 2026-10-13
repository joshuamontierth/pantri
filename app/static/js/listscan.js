/* Adding from a scanned shopping list: check the items, fix what was misread, pick stores.
 *
 * The server matched each item to the catalog and picked its usual store. Editing a name matches it
 * again here (the same way: same name, or the same but for a plural), so the "New" tag and the
 * store choices follow. A store you picked yourself stays picked.
 */
(function () {
  "use strict";
  const form = document.querySelector("[data-scan-review]");
  if (!form) return;

  const catalog = JSON.parse(document.getElementById("scan-catalog").textContent);
  const info = JSON.parse(document.getElementById("scan-stores").textContent);
  const storeNames = {};
  info.stores.forEach((id, i) => { storeNames[id] = info.names[i]; });
  const ORDINALS = ["1st", "2nd", "3rd"];
  const ordinal = (i) => ORDINALS[i] || i + 1 + "th";

  // services.name_key: "Avocados" and "avocado" are the same item.
  function singularize(word) {
    if (word.length > 4 && word.endsWith("ies")) return word.slice(0, -3) + "y";
    for (const suffix of ["sses", "ches", "shes", "xes", "zes"]) if (word.endsWith(suffix)) return word.slice(0, -2);
    if (word.length > 2 && word.endsWith("s") && !word.endsWith("ss")) return word.slice(0, -1);
    return word;
  }
  function nameKey(name) {
    const words = name.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return "";
    words.push(singularize(words.pop()));
    return words.join(" ");
  }
  const byKey = {};
  Object.keys(catalog).forEach((lower) => { if (!(nameKey(lower) in byKey)) byKey[nameKey(lower)] = catalog[lower]; });
  const match = (name) => catalog[name.trim().toLowerCase()] || byKey[nameKey(name)] || null;

  const rows = Array.from(form.querySelectorAll("[data-row]"));
  const button = form.querySelector("[data-apply]");
  const saveNew = form.querySelector("[data-save-new]");
  const selectAll = form.querySelector("[data-select-all]");
  selectAll.hidden = false;

  function option(value, label, selected) {
    const o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    o.selected = selected;
    return o;
  }

  function fillStores(select, ranks, chosen) {
    const ranked = ranks.filter((id) => id in storeNames);
    const others = info.stores.filter((id) => !ranked.includes(id));
    select.replaceChildren();
    if (ranked.length) {
      const g = document.createElement("optgroup");
      g.label = "Your stores for this";
      ranked.forEach((id, i) => g.appendChild(option(String(id), storeNames[id] + " · " + ordinal(i), String(id) === chosen)));
      select.appendChild(g);
    }
    if (others.length) {
      const g = document.createElement("optgroup");
      g.label = ranked.length ? "Other stores" : "Stores";
      others.forEach((id) => g.appendChild(option(String(id), storeNames[id], String(id) === chosen)));
      select.appendChild(g);
    }
    select.appendChild(option("none", info.other, chosen === "none"));
  }

  function rematch(row) {
    const input = row.querySelector("[data-name]");
    const found = match(input.value);
    row._new = !found && input.value.trim() !== "";
    row.querySelector("[data-new]").hidden = !row._new;
    const onList = row.querySelector("[data-on-list]");
    const select = row.querySelector("[data-store]");
    const ranks = found ? found.ranks.filter((id) => id in storeNames) : [];
    const original = input.value.trim().toLowerCase() === input.dataset.original.toLowerCase();
    const chosen = select.dataset.touched ? select.value : original ? select.dataset.suggested : ranks.length ? String(ranks[0]) : "none";
    fillStores(select, ranks, chosen);
    if (onList) onList.hidden = !original;
  }

  const isOn = (row) => row.querySelector("[data-include]").checked;

  function update() {
    const picked = rows.filter(isOn);
    rows.forEach((row) => row.classList.toggle("on", isOn(row)));
    button.disabled = picked.length === 0;
    button.querySelector(".apply-main").textContent = picked.length
      ? "Add " + picked.length + " item" + (picked.length === 1 ? "" : "s") + " to lists" : "Check the items you need";
    const perStore = new Map();
    picked.forEach((row) => {
      const v = row.querySelector("[data-store]").value;
      const name = v === "none" ? info.other : storeNames[v] || info.other;
      perStore.set(name, (perStore.get(name) || 0) + 1);
    });
    button.querySelector(".apply-sub").textContent = Array.from(perStore, ([name, n]) => name + " " + n).join(" · ");
    const fresh = picked.filter((row) => row._new).length;
    saveNew.hidden = fresh === 0;
    saveNew.querySelector("strong").textContent = "Save " + (fresh === 1 ? "the new item" : fresh + " new items") + " to the catalog";
    selectAll.textContent = picked.length === rows.length ? "Select none" : "Select all";
  }

  rows.forEach((row) => {
    const isNew = !row.querySelector("[data-new]").hidden;
    row._new = isNew;
  });

  form.addEventListener("input", (e) => {
    if (e.target.matches("[data-name]")) {
      rematch(e.target.closest("[data-row]"));
      update();
    }
  });
  form.addEventListener("change", (e) => {
    const row = e.target.closest("[data-row]");
    if (!row) return;
    if (e.target.matches("[data-store]")) {
      e.target.dataset.touched = "1";
      row.querySelector("[data-include]").checked = true; // picking a store means you want it, as when adding recipes
    }
    if (e.target.matches("[data-include]") && e.target.checked && window.App) window.App.buzz(8);
    update();
  });
  selectAll.addEventListener("click", () => {
    const all = rows.every(isOn);
    rows.forEach((row) => { row.querySelector("[data-include]").checked = !all; });
    update();
  });
  // Enter in a box goes to the next item instead of sending the form.
  form.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !e.target.matches(".scan-fields input")) return;
    e.preventDefault();
    const i = rows.indexOf(e.target.closest("[data-row]"));
    const next = rows[i + 1];
    if (next) next.querySelector("[data-name]").focus();
    else e.target.blur();
  });
  form.addEventListener("submit", (e) => {
    const picked = rows.filter(isOn).length;
    if (!picked) { e.preventDefault(); return; }
    try { sessionStorage.setItem("sl:toast", "Added " + picked + " item" + (picked === 1 ? "" : "s") + " from your list"); } catch (_) { /* no toast then */ }
    setTimeout(() => { button.disabled = true; }, 0);
  });
  // Back from the lists with the browser's back button: the button works again.
  window.addEventListener("pageshow", () => update());

  update();
})();
