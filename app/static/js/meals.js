/* The meal calendar: the "Add" sheet for a lunch or dinner, and a connection check before changes. */
(function () {
  "use strict";
  const sheet = document.getElementById("meal-sheet");
  if (!sheet) return;

  const form = sheet.querySelector("[data-meal-form]");
  const save = form.querySelector("[data-meal-save]");
  const title = form.querySelector("[data-meal-title]");
  const shop = form.querySelector("[data-meal-shop]");
  const search = form.querySelector('input[type="search"]');
  const toast = (text) => window.App && window.App.toast(text, true);

  function update() {
    const n = form.querySelectorAll('input[name="recipe_id"]:checked').length;
    const typed = title.value.trim() !== "";
    if (shop) shop.hidden = n === 0;
    const goesShopping = n > 0 && shop && shop.querySelector("input").checked;
    save.disabled = n === 0 && !typed;
    save.querySelector(".apply-main").textContent = n === 0 && !typed ? "Pick a recipe or type a meal"
      : n ? "Add " + n + " recipe" + (n === 1 ? "" : "s") + (typed ? " and " + title.value.trim() : "") : "Add " + title.value.trim();
    save.querySelector(".apply-sub").textContent = goesShopping ? "Then pick the ingredients you need" : "";
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
  // Back here with the browser's back button: the buttons work again.
  window.addEventListener("pageshow", () => document.querySelectorAll("[data-meal-change] button").forEach((b) => { b.disabled = false; }));
})();
