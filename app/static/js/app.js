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

  // Shared with lists.js.
  window.App = { toast, buzz, csrf, clientId };

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

  // ---------- offline ----------
  // The service worker (/sw.js) keeps pages and assets cached so the site opens without a connection.
  // The lists page goes further and works fully offline (lists.js).
  if (document.body.hasAttribute("data-anon")) {
    // Logged out: forget this account's saved lists and cached pages (shared computers).
    try { Object.keys(localStorage).filter((k) => k.startsWith("sl:")).forEach((k) => localStorage.removeItem(k)); } catch (_) { /* blocked */ }
    if (window.caches) caches.keys().then((keys) => keys.filter((k) => k.startsWith("pages-")).forEach((k) => caches.delete(k))).catch(() => {});
  } else if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* not available: online only */ });
  }
  // Other pages: say so when this is a saved copy because the server can't be reached.
  const syncPill = document.getElementById("sync-pill");
  if (syncPill && !document.body.hasAttribute("data-lists-page")) {
    const showOffline = (off) => { syncPill.textContent = "Offline"; syncPill.hidden = !off; syncPill.classList.toggle("is-offline", off); };
    const check = () => fetch("/healthz", { cache: "no-store" }).then((r) => showOffline(!r.ok)).catch(() => showOffline(true));
    check();
    window.addEventListener("online", check);
    window.addEventListener("offline", () => showOffline(true));
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

  // ---------- import a recipe (photos or a link) ----------
  const MAX_SHOTS = 4;
  // A live camera view needs HTTPS (or localhost). Over plain http, "Take a photo" opens the phone's camera app.
  const liveCamera = !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  // Offer the camera on touch devices, and on any device where the browser reports a camera.
  // Worked out up front so the tap that opens a file picker stays a direct user gesture.
  let offerCamera = window.matchMedia("(pointer: coarse)").matches;
  if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
    navigator.mediaDevices.enumerateDevices()
      .then((devices) => { if (devices.some((d) => d.kind === "videoinput")) offerCamera = true; })
      .catch(() => {});
  }

  function submitScan(form, input) {
    // Only send the input that holds the photos.
    form.querySelectorAll("[data-scan-input]").forEach((other) => { if (other !== input) other.disabled = true; });
    form.querySelectorAll("dialog[open]").forEach((d) => d.close());
    showReading();
    form.submit();
  }

  function showReading() {
    const overlay = document.querySelector(".scan-overlay");
    if (overlay) overlay.hidden = false;
  }

  function showLinkStep(sheet) {
    const choices = sheet.querySelector("[data-import-choices]");
    if (choices) choices.hidden = true;
    sheet.querySelector("[data-link-step]").hidden = false;
    const paste = sheet.querySelector("[data-link-paste]");
    paste.hidden = !(window.isSecureContext && navigator.clipboard && navigator.clipboard.readText);
    sheet.querySelector("[data-link-input]").focus();
  }

  function cameraFor(form) {
    if (form._camera !== undefined) return form._camera;
    const dialog = form.querySelector("[data-camera]");
    if (!liveCamera || !dialog) return (form._camera = null);
    const video = dialog.querySelector("video");
    const shotsEl = dialog.querySelector("[data-camera-shots]");
    const shutter = dialog.querySelector("[data-camera-shutter]");
    const done = dialog.querySelector("[data-camera-done]");
    const torch = dialog.querySelector("[data-camera-torch]");
    const hint = dialog.querySelector("[data-camera-hint]");
    const problem = dialog.querySelector("[data-camera-problem]");
    let stream = null;
    let shots = [];
    let torchOn = false;

    function render() {
      shotsEl.replaceChildren(...shots.map((shot, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "shot";
        b.setAttribute("aria-label", "Remove photo " + (i + 1));
        const img = document.createElement("img");
        img.src = shot.url;
        img.alt = "";
        b.appendChild(img);
        b.addEventListener("click", () => {
          URL.revokeObjectURL(shot.url);
          shots.splice(i, 1);
          render();
        });
        return b;
      }));
      done.disabled = shots.length === 0;
      done.textContent = shots.length > 1 ? "Read " + shots.length + " photos" : "Read recipe";
      shutter.disabled = !stream || shots.length >= MAX_SHOTS;
      hint.textContent = shots.length >= MAX_SHOTS ? MAX_SHOTS + " photos is the most" :
        shots.length ? "Add another photo, or tap Read" : "Get the ingredients in view";
    }

    function stop() {
      if (stream) stream.getTracks().forEach((t) => t.stop());
      stream = null;
      video.srcObject = null;
      torchOn = false;
    }

    function clear() {
      shots.forEach((s) => URL.revokeObjectURL(s.url));
      shots = [];
    }

    async function open() {
      clear();
      problem.hidden = true;
      torch.hidden = true;
      dialog.showModal();
      render();
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: "environment" }, width: { ideal: 2560 }, height: { ideal: 1920 } },
        });
        video.srcObject = stream;
        await video.play();
        const track = stream.getVideoTracks()[0];
        const caps = track.getCapabilities ? track.getCapabilities() : {};
        torch.hidden = !caps.torch;
      } catch (err) {
        stop();
        problem.querySelector("p").textContent = err && err.name === "NotAllowedError"
          ? "Camera access is blocked for this site. Allow it in your browser's site settings, or use your camera app."
          : "The camera couldn't start. You can use your camera app instead.";
        problem.hidden = false;
      }
      render();
    }

    async function grabFrame() {
      const track = stream.getVideoTracks()[0];
      // Full-resolution still where the browser supports it (sharper text), else the current video frame.
      if (window.ImageCapture) {
        try { return await new ImageCapture(track).takePhoto(); } catch (_) { /* fall back */ }
      }
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    }

    shutter.addEventListener("click", async () => {
      if (!stream || shots.length >= MAX_SHOTS || shutter._busy) return;
      shutter._busy = true;
      dialog.classList.remove("flash");
      void dialog.offsetWidth; // restart the flash animation
      dialog.classList.add("flash");
      buzz(15);
      try {
        const blob = await grabFrame();
        if (blob) {
          const file = new File([blob], "scan-" + (shots.length + 1) + ".jpg", { type: blob.type || "image/jpeg" });
          shots.push({ file, url: URL.createObjectURL(file) });
        }
      } finally {
        shutter._busy = false;
        render();
      }
    });

    done.addEventListener("click", () => {
      if (!shots.length) return;
      const input = form.querySelector("[data-scan-library]");
      const dt = new DataTransfer();
      shots.forEach((s) => dt.items.add(s.file));
      input.files = dt.files;
      stop();
      submitScan(form, input);
    });

    torch.addEventListener("click", () => {
      const track = stream && stream.getVideoTracks()[0];
      if (!track) return;
      torchOn = !torchOn;
      track.applyConstraints({ advanced: [{ torch: torchOn }] }).catch(() => { torchOn = false; });
      torch.setAttribute("aria-pressed", torchOn ? "true" : "false");
    });

    dialog.querySelector("[data-camera-close]").addEventListener("click", () => dialog.close());
    dialog.querySelector("[data-camera-native]").addEventListener("click", () => {
      dialog.close();
      form.querySelector("input[capture]").click();
    });
    // However it closes (X, Escape, back gesture), let go of the camera.
    dialog.addEventListener("close", () => { stop(); clear(); });

    return (form._camera = { open });
  }

  document.addEventListener("click", (e) => {
    const button = e.target.closest("[data-import-button]");
    if (button) {
      const sheet = button.form.querySelector(".scan-sheet");
      const takePhoto = sheet.querySelector("[data-take-photo]");
      if (takePhoto) takePhoto.hidden = !offerCamera;
      sheet.showModal();
      if (!sheet.querySelector("[data-import-choices]")) showLinkStep(sheet);
      return;
    }
    const linkChoice = e.target.closest("[data-link-choice]");
    if (linkChoice) {
      showLinkStep(linkChoice.closest("dialog"));
      return;
    }
    const paste = e.target.closest("[data-link-paste]");
    if (paste) {
      const input = paste.closest("dialog").querySelector("[data-link-input]");
      navigator.clipboard.readText().then((text) => { if (text.trim()) input.value = text.trim(); input.focus(); }).catch(() => input.focus());
      return;
    }
    // "Take a photo": the in-app camera when we can, otherwise the label opens the phone's camera app.
    const takePhoto = e.target.closest("[data-take-photo]");
    // (A click aimed at the file input itself is the camera-app fallback; let it through.)
    if (takePhoto && !e.target.matches("input[type=file]")) {
      const camera = cameraFor(takePhoto.closest("form"));
      if (camera) {
        e.preventDefault();
        takePhoto.closest("dialog").close();
        camera.open();
      }
      return;
    }
    if (e.target.closest("[data-scan-cancel]")) {
      e.target.closest("dialog").close();
      return;
    }
    // Tap outside the sheet closes it.
    const sheet = e.target.closest(".scan-sheet");
    if (sheet && e.target === sheet) {
      const r = sheet.getBoundingClientRect();
      if (e.clientY < r.top || e.clientY > r.bottom || e.clientX < r.left || e.clientX > r.right) sheet.close();
    }
  });

  // Back to the first choices whenever the sheet closes.
  document.querySelectorAll(".scan-sheet").forEach((sheet) => {
    sheet.addEventListener("close", () => {
      const choices = sheet.querySelector("[data-import-choices]");
      if (choices) {
        choices.hidden = false;
        sheet.querySelector("[data-link-step]").hidden = true;
      }
    });
  });
  document.addEventListener("submit", (e) => {
    if (!e.target.matches("[data-link-form]") || e.defaultPrevented) return;
    document.querySelectorAll(".scan-sheet[open]").forEach((d) => d.close());
    showReading();
  });

  // Upload as soon as photos are picked (library, or the phone's camera app).
  document.addEventListener("change", (e) => {
    const input = e.target.closest("[data-scan-input]");
    if (!input || !input.files.length) return;
    if (input.files.length > MAX_SHOTS) {
      toast("Use up to " + MAX_SHOTS + " photos at a time.", true);
      input.value = "";
      return;
    }
    submitScan(input.form, input);
  });
  // Shared to the installed site (sw.js -> /share -> here): import the link or photos.
  (function importShared() {
    const params = new URLSearchParams(location.search);
    const form = document.querySelector("[data-scan-form]");
    if (!params.get("shared") || !form) return;
    history.replaceState(null, "", location.pathname);
    const count = Number(params.get("photos") || 0);
    const library = document.getElementById("scan-library");
    if (count && library && window.caches) {
      caches.open("share-inbox").then(async (inbox) => {
        const dt = new DataTransfer();
        for (let i = 0; i < count; i++) {
          const r = await inbox.match("/share-inbox/" + i);
          if (r) { const b = await r.blob(); dt.items.add(new File([b], "shared-" + (i + 1) + ".jpg", { type: b.type || "image/jpeg" })); }
        }
        await caches.delete("share-inbox");
        if (dt.files.length) { library.files = dt.files; submitScan(form, library); }
      });
      return;
    }
    const link = (params.get("text") || "").match(/https?:\/\/\S+/);
    const linkForm = document.querySelector("[data-link-form]");
    const input = document.querySelector("[data-link-input]");
    if (link && linkForm && input) {
      input.value = link[0];
      showReading();
      linkForm.submit();
    } else {
      toast("Share a link to a recipe page, or photos of a recipe.", true);
    }
  })();

  // Coming back with the browser's back button shouldn't leave the reading screen up.
  window.addEventListener("pageshow", () => {
    document.querySelectorAll(".scan-overlay").forEach((o) => { o.hidden = true; });
    document.querySelectorAll("[data-scan-input]").forEach((i) => { i.disabled = false; i.value = ""; });
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
    // The directions box grows with its text.
    form.querySelectorAll("textarea[data-autogrow]").forEach((ta) => {
      ta.style.overflowY = "hidden";
      const fit = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + 2 + "px"; };
      ta.addEventListener("input", fit);
      fit();
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

  // ---------- cooking from a recipe ----------
  function initSteps(list) {
    // Tap a step to mark it done. Remembered for this tab, so a reload mid-recipe keeps your place.
    const key = "steps-" + list.dataset.steps;
    const buttons = Array.from(list.querySelectorAll(".step"));
    let done = [];
    try { done = JSON.parse(sessionStorage.getItem(key) || "[]"); } catch (_) { done = []; }
    buttons.forEach((b, i) => b.setAttribute("aria-pressed", done.includes(i) ? "true" : "false"));
    list.addEventListener("click", (e) => {
      const b = e.target.closest(".step");
      if (!b) return;
      b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") === "true" ? "false" : "true");
      buzz(8);
      const now = buttons.flatMap((x, i) => (x.getAttribute("aria-pressed") === "true" ? [i] : []));
      try { sessionStorage.setItem(key, JSON.stringify(now)); } catch (_) { /* private mode */ }
    });
  }

  function initWakeLock(button) {
    // Keep the screen from dimming while cooking. Browsers drop the lock when the tab is hidden; take it back on return.
    if (!("wakeLock" in navigator)) return;
    button.hidden = false;
    const label = button.querySelector("span");
    let lock = null;
    let wanted = false;
    function render() {
      button.setAttribute("aria-pressed", wanted ? "true" : "false");
      label.textContent = wanted ? "Screen stays on" : "Keep screen on";
    }
    async function acquire() {
      try {
        lock = await navigator.wakeLock.request("screen");
        lock.addEventListener("release", () => { lock = null; });
      } catch (_) {
        wanted = false;
      }
      render();
    }
    button.addEventListener("click", () => {
      wanted = !wanted;
      if (wanted) acquire();
      else if (lock) lock.release();
      render();
    });
    document.addEventListener("visibilitychange", () => {
      if (wanted && !lock && document.visibilityState === "visible") acquire();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const editor = document.querySelector("[data-recipe-editor]");
    if (editor) initRecipeEditor(editor);
    const steps = document.querySelector("[data-steps]");
    if (steps) initSteps(steps);
    const wake = document.querySelector("[data-wake-lock]");
    if (wake) initWakeLock(wake);
  });
})();
