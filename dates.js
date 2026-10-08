// Date et heure affichées par toutes les pages du dashboard, quelle que soit la langue : jour, mois, année,
// du plus utile au moins utile, mois sur deux chiffres. Jamais le format américain du navigateur.
window.formatDateTime = iso => {
  const date = new Date(iso);
  const two = n => String(n).padStart(2, "0");
  return `${two(date.getDate())}/${two(date.getMonth() + 1)}/${date.getFullYear()} ${two(date.getHours())}:${two(date.getMinutes())}`;
};

// Heure de chargement de la page dans element, pour juger si ce qu'elle montre a pu changer depuis :
// « chargée à 14:32 · il y a 5 min », remise à jour chaque minute, signalée (classe stale) au-delà de
// STALE_MINUTES. at remplace l'heure d'ouverture de la page quand ce qu'elle montre date d'avant (sauvegarde)
// ou d'après (mise à jour).
window.showLoadedAt = (() => {
  const STALE_MINUTES = 30;
  const TEXTS = {
    fr: {
      at: time => `chargée à ${time}`,
      on: dateTime => `chargée le ${dateTime}`,
      now: "à l'instant",
      ago: age => `il y a ${age}`,
      day: "j",
      title: "Heure de chargement de la page : rechargez-la (F5) pour voir les derniers changements de la MR.",
    },
    en: {
      at: time => `loaded at ${time}`,
      on: dateTime => `loaded on ${dateTime}`,
      now: "just now",
      ago: age => `${age} ago`,
      day: "d",
      title: "When this page was loaded: reload it (F5) to see the latest changes of the MR.",
    },
  };
  const openedAt = new Date();

  return (
      element,
      lang,
      at
  ) => {
    const texts = TEXTS[lang] ?? TEXTS.en;
    if (at) element.dataset.loadedAt = new Date(at).toISOString();
    const loadedAt = element.dataset.loadedAt ? new Date(element.dataset.loadedAt) : openedAt;
    const dateTime = window.formatDateTime(loadedAt.toISOString());
    const sameDay = loadedAt.toDateString() === new Date().toDateString();
    const minutes = Math.floor((Date.now() - loadedAt) / 60000);
    const age = minutes < 1 ? texts.now
      : texts.ago(minutes < 60 ? `${minutes} min`
        : minutes < 48 * 60 ? `${Math.floor(minutes / 60)} h`
          : `${Math.floor(minutes / 1440)} ${texts.day}`);
    element.textContent = `${sameDay ? texts.at(dateTime.slice(-5)) : texts.on(dateTime)} · ${age}`;
    element.title = `${texts.title}\n${dateTime}`;
    element.classList.toggle("stale", minutes >= STALE_MINUTES);
    if (!element.dataset.loadedAtTimer) {
      element.dataset.loadedAtTimer = String(setInterval(() => window.showLoadedAt(element, lang), 60000));
    }
  };
})();
