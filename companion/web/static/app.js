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
  let saved = rendered && Date.now() - rendered.getTime() > OLD_AFTER_MS;

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
  // A form post just put the server's page in place: it's fresh, so a late "fresh" message mustn't reload it.
  document.addEventListener("companion:swap", () => {
    saved = false;
    if (pill) pill.remove();
    pill = null;
  });

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

// Form posts without a page reload. The post goes in the background and the page the server answers with takes
// this one's place (header and main), at the same scroll position when it's the same page. The answer is saved
// for the service worker too, so the next visit doesn't show the copy from before. Sign-in and sign-out, and a
// post that can't be sent, fall back to a normal submit.
(() => {
  const root = document.documentElement;
  const NATIVE = new Set(["/login", "/logout"]);
  let sending = false;
  let shown = location.pathname + location.search; // the page on screen, to tell a jump within it from Back

  async function save(url, html) {
    try {
      const cache = await caches.open("pages"); // the service worker's page cache (sw.js)
      await cache.put(url, new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } }));
    } catch {
      // no Cache API (private window): the service worker fetches a fresh copy anyway
    }
  }

  function swap(doc) {
    for (const sel of ["header.bar", "main", 'meta[name="rendered-at"]']) {
      const here = document.querySelector(sel);
      const next = doc.querySelector(sel);
      if (here && next) here.replaceWith(next);
    }
    document.title = doc.title;
    document.dispatchEvent(new Event("companion:swap"));
  }

  function problem(text) {
    const main = document.querySelector("main");
    if (!main) return;
    main.querySelector(".post-problem")?.remove();
    const p = document.createElement("p");
    p.className = "card warn post-problem";
    p.setAttribute("role", "alert");
    p.textContent = text;
    main.prepend(p);
    p.scrollIntoView({ block: "nearest" });
  }

  document.addEventListener("submit", async (e) => {
    const form = e.target;
    if (e.defaultPrevented || form.method !== "post" || "native" in form.dataset) return;
    const action = new URL(form.getAttribute("action") || location.href, location.href);
    if (action.origin !== location.origin || NATIVE.has(action.pathname)) return;
    e.preventDefault();
    if (sending) return; // a double tap posts once
    sending = true;
    const body = new FormData(form);
    if (e.submitter && e.submitter.name) body.append(e.submitter.name, e.submitter.value);
    try {
      let r;
      try {
        r = await fetch(action, { method: "POST", body, credentials: "same-origin" });
      } catch {
        form.dataset.native = ""; // couldn't reach the server: let the browser try, and show what it gets
        form.requestSubmit(e.submitter);
        return;
      }
      const landed = new URL(r.url);
      if (NATIVE.has(landed.pathname)) return void (location.href = landed.href); // signed out
      if (!(r.headers.get("content-type") || "").startsWith("text/html")) {
        const detail = (await r.json().catch(() => ({}))).detail;
        return problem(typeof detail === "string" ? detail : `Couldn't save (error ${r.status}). Try again.`);
      }
      const html = await r.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const samePage = landed.pathname === location.pathname;
      const y = window.scrollY;
      swap(doc);
      const target = landed.pathname + landed.search;
      if (target === location.pathname + location.search) history.replaceState(null, "", target);
      else history[samePage ? "replaceState" : "pushState"](null, "", target);
      shown = target;
      window.scrollTo(0, samePage ? y : 0);
      if (r.ok) save(landed.href, html);
    } finally {
      sending = false;
      root.classList.remove("is-loading");
    }
  });

  // Back and forward over a page put in place: load it properly (a #jump on the same page is left alone).
  window.addEventListener("popstate", () => {
    if (location.pathname + location.search !== shown) location.reload();
  });
})();

// Reminders page: turn push on or off for this device (app/web_reminders.py). Runs again when a form post puts
// the reminders page in place.
function pushDevice() {
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
}
pushDevice();
document.addEventListener("companion:swap", pushDevice);
