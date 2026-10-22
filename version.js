"use strict";

// Reloads the page when the server serves HTML, JS or CSS other than what it loaded: a tab
// opened in the morning moves to the day's code by itself, without F5. Only a server answering with another
// version triggers a reload: unreachable, the page stays as is. The reload waits until no input is
// in progress, so nothing being typed is lost.
(() => {
  const CHECK_MS = 30 * 1000;
  const loaded = document.querySelector('meta[name="mr-dashboard-version"]')?.content;
  if (!loaded) {
    return;
  }

  const typing = () => {
    const active = document.activeElement;
    return active?.isContentEditable
      || ["INPUT", "TEXTAREA", "SELECT"].includes(active?.tagName)
      || [...document.querySelectorAll("textarea")].some(area => area.value.trim() !== "");
  };

  const check = async () => {
    let served;
    try {
      const response = await fetch("version", {cache: "no-store"});
      if (!response.ok) {
        return;
      }
      served = (await response.json()).version;
    } catch {
      return;
    }
    if (served && served !== loaded && !typing()) {
      location.reload();
    }
  };

  setInterval(check, CHECK_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      check();
    }
  });
})();
