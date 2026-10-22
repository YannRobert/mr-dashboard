"use strict";

// Recharge la page quand le serveur sert d'autres HTML, JS ou CSS que ceux qu'elle a chargés : un onglet
// ouvert le matin passe de lui-même au code du jour, sans F5. Seul un serveur qui répond avec une autre
// version recharge : injoignable, la page reste telle quelle. Le rechargement attend qu'aucune saisie ne
// soit en cours, pour ne rien perdre de ce qui est tapé.
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
