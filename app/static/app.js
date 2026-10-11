// Service worker + push-notificaties
(function () {
  const isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const pushSupported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  document.documentElement.dataset.standalone = isStandalone ? "1" : "0";
  document.documentElement.dataset.ios = isIOS ? "1" : "0";

  function b64ToUint8(base64) {
    const padding = "=".repeat((4 - (base64.length % 4)) % 4);
    const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  async function registration() {
    return navigator.serviceWorker.register("/sw.js");
  }

  async function currentSubscription() {
    if (!pushSupported) return null;
    const reg = await registration();
    return reg.pushManager.getSubscription();
  }

  async function enablePush() {
    const key = document.body.dataset.vapid;
    if (!key) throw new Error("Push is nog niet ingesteld op de server.");
    const permission = await Notification.requestPermission();
    if (permission !== "granted") throw new Error("Je hebt notificaties niet toegestaan.");
    const reg = await registration();
    let sub = await reg.pushManager.getSubscription();
    if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToUint8(key) });
    const res = await fetch("/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sub.toJSON()),
    });
    if (!res.ok) throw new Error("Opslaan mislukt.");
  }

  async function disablePush() {
    const sub = await currentSubscription();
    if (!sub) return;
    await fetch("/push/unsubscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ endpoint: sub.endpoint }) });
    await sub.unsubscribe();
  }

  async function pushState() {
    if (!pushSupported) return isIOS && !isStandalone ? "needs-install" : "unsupported";
    if (Notification.permission === "denied") return "denied";
    const sub = await currentSubscription();
    return sub ? "on" : "off";
  }

  window.Filosofie = { enablePush, disablePush, pushState, isStandalone, isIOS, pushSupported };

  if ("serviceWorker" in navigator) registration().catch(() => {});

  document.addEventListener("DOMContentLoaded", async () => {
    // Meldingsbanner op de startpagina
    const banner = document.querySelector("[data-push-banner]");
    if (banner && document.body.dataset.vapid) {
      const state = await pushState().catch(() => "unsupported");
      if (state === "off" || state === "needs-install") banner.classList.add("show");
    }

    // Tekenteller
    document.querySelectorAll("[data-count]").forEach((el) => {
      const out = document.getElementById(el.dataset.count);
      const max = el.getAttribute("maxlength");
      const update = () => (out.textContent = `${el.value.length}/${max}`);
      el.addEventListener("input", update);
      update();
    });

    // Verzendknop pas actief als er een keuze is
    document.querySelectorAll("form[data-needs-choice]").forEach((form) => {
      const btn = form.querySelector("button[type=submit]");
      const sync = () => (btn.disabled = !form.querySelector("input[type=radio]:checked"));
      form.addEventListener("change", sync);
      sync();
    });

    // Maximaal N vinkjes
    document.querySelectorAll("[data-max]").forEach((group) => {
      const max = Number(group.dataset.max);
      const boxes = [...group.querySelectorAll("input[type=checkbox]")];
      const sync = () => {
        const full = boxes.filter((b) => b.checked).length >= max;
        boxes.forEach((b) => (b.disabled = full && !b.checked));
      };
      group.addEventListener("change", sync);
      sync();
    });
  });
})();
