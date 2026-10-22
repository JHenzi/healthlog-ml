// Page side of the installable app (app/pwa.py): register the service worker, show a loading bar while a
// page or form is on its way, and say how old a saved copy is until the fresh one arrives.
(() => {
  const root = document.documentElement;
  const OLD_AFTER_MS = 30000; // a page rendered more than this long ago is a saved copy

  // Loading bar: a tap on a link or a form post shows it until the next page is up.
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || a.target || e.metaKey || e.ctrlKey || e.shiftKey || a.origin !== location.origin) return;
    if (a.pathname === location.pathname && a.search === location.search && a.hash) return;
    root.classList.add("is-loading");
  });
  document.addEventListener("submit", () => root.classList.add("is-loading"));
  window.addEventListener("pageshow", () => root.classList.remove("is-loading"));

  // How old is this copy?
  const meta = document.querySelector('meta[name="rendered-at"]');
  const rendered = meta ? new Date(meta.content) : null;
  const saved = rendered && Date.now() - rendered.getTime() > OLD_AFTER_MS;

  function when(d) {
    const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const today = new Date().toDateString() === d.toDateString();
    return today ? time : `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
  }

  let pill = null;
  function say(text, action) {
    if (!pill) {
      pill = document.createElement("button");
      pill.type = "button";
      pill.className = "freshness";
      pill.setAttribute("role", "status");
      document.body.appendChild(pill);
    }
    pill.textContent = text;
    pill.disabled = !action;
    pill.onclick = action || null;
  }

  function busy() {
    const el = document.activeElement;
    return (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) || window.scrollY > 200;
  }

  if (saved) say(`Saved ${when(rendered)} · checking for updates…`);

  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/sw.js").catch(() => {});
  navigator.serviceWorker.addEventListener("message", (e) => {
    const m = e.data || {};
    if (m.type === "signed-out") location.href = "/login";
    if (!saved || m.path !== location.pathname + location.search) return;
    if (m.type === "fresh") {
      if (busy()) say("Newer numbers ready · tap to show", () => location.reload());
      else location.reload();
    }
    if (m.type === "offline") say(`Saved ${when(rendered)} · offline, showing the last copy`);
  });
})();

// Reminders page: turn push on or off for this device (app/web_reminders.py).
(() => {
  const box = document.getElementById("push-device");
  if (!box) return;
  const status = box.querySelector("[data-push-status]");
  const on = box.querySelector("[data-push-on]");
  const off = box.querySelector("[data-push-off]");
  const install = box.querySelector("[data-push-install]");
  const csrf = box.dataset.csrf;

  function key(b64) {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }

  async function post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csrf, ...body }),
      credentials: "same-origin",
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `error ${r.status}`);
  }

  function show(text, subscribed) {
    status.textContent = text;
    on.hidden = subscribed;
    off.hidden = !subscribed;
  }

  async function refresh() {
    const standalone = window.navigator.standalone || matchMedia("(display-mode: standalone)").matches;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      show("This browser can't receive reminders.", false);
      on.hidden = true;
      install.hidden = standalone;
      return;
    }
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) show("Reminders are on for this phone.", true);
    else if (Notification.permission === "denied")
      show("Notifications are blocked for the Companion. Allow them in the phone's Settings → Notifications.", false);
    else show("Reminders are off for this phone.", false);
  }

  on.addEventListener("click", async () => {
    try {
      if ((await Notification.requestPermission()) !== "granted") return refresh();
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: key(box.dataset.publicKey),
      });
      await post("/push/subscribe", { subscription: sub.toJSON() });
      show("Reminders are on for this phone.", true);
    } catch (e) {
      show(`Couldn't turn reminders on: ${e.message}`, false);
    }
  });

  off.addEventListener("click", async () => {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await post("/push/unsubscribe", { endpoint: sub.endpoint });
        await sub.unsubscribe();
      }
      show("Reminders are off for this phone.", false);
    } catch (e) {
      show(`Couldn't turn reminders off: ${e.message}`, true);
    }
  });

  refresh();
})();
