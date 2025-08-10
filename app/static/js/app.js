(function () {
  "use strict";

  // Dark mode toggle
  const html = document.documentElement;
  const toggleBtn = document.getElementById("darkToggle");
  const themeKey = "ehall.theme";
  function setTheme(mode) {
    html.setAttribute("data-bs-theme", mode);
    localStorage.setItem(themeKey, mode);
  }
  const savedTheme = localStorage.getItem(themeKey) || "light";
  setTheme(savedTheme);
  if (toggleBtn) {
    toggleBtn.addEventListener("click", function () {
      setTheme(html.getAttribute("data-bs-theme") === "light" ? "dark" : "light");
    });
  }

  // Time remaining rendering for elements with data-expires
  function pad(n) { return n.toString().padStart(2, "0"); }

  // Flash map: keep transient effects for 30s
  const flashMap = new Map(); // element -> { cls: 'flash-green'|'flash-red', until: ms }

  function applyFlashEffects() {
    const nowTs = Date.now();
    flashMap.forEach((v, el) => {
      if (nowTs > v.until) {
        el.classList.remove(v.cls);
        flashMap.delete(el);
      } else {
        el.classList.add(v.cls);
      }
    });
  }

  function updateRemaining() {
    const now = new Date();
    document.querySelectorAll("[data-expires]").forEach(function (el) {
      const iso = el.getAttribute("data-expires");
      if (!iso) return;
      const exp = new Date(iso);
      const diff = Math.max(0, Math.floor((exp - now) / 1000));
      const min = Math.floor(diff / 60);
      const sec = diff % 60;
      const remainingSpan = el.querySelector(".remaining");
      if (remainingSpan) remainingSpan.textContent = `${pad(min)}:${pad(sec)}`;

      // Blink near expiry (<= 120s)
      if (diff <= 120 && diff > 0) {
        el.classList.add("blink-red");
      } else {
        el.classList.remove("blink-red");
      }
    });

    applyFlashEffects();
  }
  setInterval(updateRemaining, 1000);
  updateRemaining();

  // Kiosk auto-refresh
  function kioskRefresh() {
    const kioskTableBody = document.getElementById("kioskBody");
    if (!kioskTableBody) return; // not on kiosk page
    fetch("/kiosk/data")
      .then(r => r.json())
      .then(rows => {
        const prevIds = new Set(Array.from(kioskTableBody.querySelectorAll("tr")).map(tr => tr.dataset.id));
        kioskTableBody.innerHTML = "";
        rows.forEach(r => {
          const tr = document.createElement("tr");
          tr.className = "pass-row active";
          tr.dataset.id = String(r.id);
          tr.setAttribute("data-expires", r.expires_at);
          tr.innerHTML = `
            <td>${r.student}</td>
            <td>${r.destination}</td>
            <td>${new Date(r.issued_at).toLocaleTimeString()}</td>
            <td>${new Date(r.expires_at).toLocaleTimeString()}</td>
            <td><span class="remaining">--:--</span></td>
            <td>${r.staff || ""}</td>
          `;
          kioskTableBody.appendChild(tr);

          // If new active pass appears (approved), flash green for 30s
          if (!prevIds.has(String(r.id))) {
            flashMap.set(tr, { cls: "flash-green", until: Date.now() + 30000 });
          }
        });
        updateRemaining();
        // Optional: chime when new passes appear
        // TODO: maintain previous IDs to detect new ones and play a sound.
      })
      .catch(() => { /* ignore */ });
  }
  // Poll every 10s by default, can be adjusted by settings page value via data attribute if needed
  setInterval(kioskRefresh, 10000);
  kioskRefresh();
})();
