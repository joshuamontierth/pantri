/* The meal calendar: the "Add" sheet for a lunch or dinner, choosing meals to shop for, and a connection
 * check before changes. */
(function () {
  "use strict";
  const sheet = document.getElementById("meal-sheet");
  if (!sheet) return;

  const form = sheet.querySelector("[data-meal-form]");
  const save = form.querySelector("[data-meal-save]");
  const title = form.querySelector("[data-meal-title]");
  const search = form.querySelector('input[type="search"]');
  const toast = (text) => window.App && window.App.toast(text, true);

  function update() {
    const n = form.querySelectorAll('input[name="recipe_id"]:checked').length;
    const typed = title.value.trim() !== "";
    save.disabled = n === 0 && !typed;
    save.querySelector(".apply-main").textContent = n === 0 && !typed ? "Pick a recipe or type a meal"
      : n ? "Add " + n + " recipe" + (n === 1 ? "" : "s") + (typed ? " and " + title.value.trim() : "") : "Add " + title.value.trim();
  }

  document.addEventListener("click", (e) => {
    const add = e.target.closest("[data-meal-add]");
    if (add) {
      if (!navigator.onLine) { toast("Changing meals needs a connection."); return; }
      form.reset();
      form.querySelector("[data-meal-day]").value = add.dataset.day;
      form.querySelector("[data-meal-slot]").value = add.dataset.slot;
      form.querySelector("[data-meal-label]").textContent = add.dataset.label;
      if (search) search.dispatchEvent(new Event("input", { bubbles: true })); // show every recipe again
      update();
      sheet.showModal();
      return;
    }
    if (e.target.closest("[data-meal-cancel]")) { sheet.close(); return; }
    // Tap outside the sheet closes it.
    if (e.target === sheet) {
      const r = sheet.getBoundingClientRect();
      if (e.clientY < r.top || e.clientY > r.bottom || e.clientX < r.left || e.clientX > r.right) sheet.close();
    }
  });

  form.addEventListener("input", update);
  form.addEventListener("change", update);

  // Adding and removing need the server; say so instead of landing on the offline page.
  document.addEventListener("submit", (e) => {
    if (!e.target.matches("[data-meal-change]")) return;
    if (!navigator.onLine) { e.preventDefault(); toast("Changing meals needs a connection."); return; }
    const button = e.target.querySelector("button:not([type=button])");
    setTimeout(() => { if (button) button.disabled = true; }, 0);
  });
  // Items added from here go through the lists' change queue: send any still waiting, and say what was added.
  if (window.Household && document.body.dataset.user) {
    window.Household({ hid: Number(document.body.dataset.household), user: document.body.dataset.user }).sync();
  }
  try {
    const said = sessionStorage.getItem("sl:toast");
    if (said) {
      sessionStorage.removeItem("sl:toast");
      setTimeout(() => window.App && window.App.toast(said), 200);
    }
  } catch (_) { /* storage blocked */ }

  // ---------- choosing meals to shop for ----------
  // Plan the week first; then check the meals to buy for. Each checked recipe goes to the ingredient
  // picker, counted once per meal (cooked twice = twice the ingredients), and it comes back to this week.
  const page = document.getElementById("meals");
  const start = document.querySelector("[data-shop-start]");
  const bar = document.querySelector("[data-shop-bar]");
  const hint = document.querySelector("[data-shop-hint]");
  const chips = () => Array.from(page.querySelectorAll(".meal-item[data-recipe]"));
  const CHECK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';

  function countShop() {
    const n = chips().filter((c) => c.classList.contains("is-chosen")).length;
    const go = bar.querySelector("[data-shop-go]");
    go.disabled = n === 0;
    go.querySelector(".apply-main").textContent = n ? "Shop for " + n + " meal" + (n === 1 ? "" : "s") : "Check the meals to shop for";
    hint.querySelector("[data-shop-all]").textContent = chips().every((c) => c.classList.contains("is-chosen")) ? "Select none" : "Select all";
  }

  function choose(on) {
    page.classList.toggle("is-choosing", on);
    start.hidden = on;
    bar.hidden = hint.hidden = !on;
    chips().forEach((c) => {
      if (on) {
        if (!c.querySelector(".choose-box")) c.insertAdjacentHTML("afterbegin", '<span class="choose-box">' + CHECK + "</span>");
        // Meals still ahead start checked; past days don't.
        c.classList.toggle("is-chosen", c.dataset.day >= page.dataset.today);
        c.setAttribute("role", "checkbox");
        c.tabIndex = 0;
      } else {
        c.removeAttribute("role");
        c.removeAttribute("aria-checked");
        c.removeAttribute("tabindex");
      }
      if (on) c.setAttribute("aria-checked", String(c.classList.contains("is-chosen")));
    });
    if (on) countShop();
  }

  function toggle(chip) {
    chip.classList.toggle("is-chosen");
    chip.setAttribute("aria-checked", String(chip.classList.contains("is-chosen")));
    if (chip.classList.contains("is-chosen") && window.App) window.App.buzz(8);
    countShop();
  }

  if (page && start && bar) {
    start.addEventListener("click", (e) => { e.preventDefault(); choose(true); });
    bar.querySelector("[data-shop-cancel]").addEventListener("click", () => choose(false));
    hint.querySelector("[data-shop-all]").addEventListener("click", () => {
      const all = chips().every((c) => c.classList.contains("is-chosen"));
      chips().forEach((c) => { c.classList.toggle("is-chosen", !all); c.setAttribute("aria-checked", String(!all)); });
      countShop();
    });
    // While choosing, a recipe's chip checks it instead of opening the recipe.
    page.addEventListener("click", (e) => {
      if (!page.classList.contains("is-choosing")) return;
      const chip = e.target.closest(".meal-item[data-recipe]");
      if (!chip) return;
      e.preventDefault();
      toggle(chip);
    }, true);
    page.addEventListener("keydown", (e) => {
      const chip = page.classList.contains("is-choosing") && e.target.closest(".meal-item[data-recipe]");
      if (chip && (e.key === " " || e.key === "Enter")) { e.preventDefault(); toggle(chip); }
    });
    bar.querySelector("[data-shop-go]").addEventListener("click", () => {
      const counts = new Map();
      chips().filter((c) => c.classList.contains("is-chosen")).forEach((c) => counts.set(c.dataset.recipe, (counts.get(c.dataset.recipe) || 0) + 1));
      if (!counts.size) return;
      const p = new URLSearchParams([["step", "pick"]]);
      counts.forEach((n, id) => p.append("r", id));
      counts.forEach((n, id) => { if (n > 1) p.set("m_" + id, String(n)); });
      p.set("back", page.dataset.back);
      location.href = page.dataset.plan + "#" + p.toString();
    });
  }

  // Back here with the browser's back button: the buttons work again.
  window.addEventListener("pageshow", () => document.querySelectorAll("[data-meal-change] button").forEach((b) => { b.disabled = false; }));
})();
