// Pastille colorée d'un auteur, partagée par index.html et diff.html : un auteur y a la même couleur.
window.Avatars = (() => {
  const COLORS_KEY = "mr-dashboard.avatar-colors";
  // Nombre de couleurs --avatar-<n> définies pour chaque thème, rangées des plus éloignées aux plus proches.
  const COLOR_COUNT = 8;

  // Une couleur dérivée du nom pourrait donner la même, ou une voisine, à deux auteurs. Chaque nouvel auteur prend
  // la couleur la moins utilisée et la garde : retenue d'un chargement à l'autre, elle ne change pas non plus quand
  // la vue des MR mergées fait apparaître d'autres auteurs.
  let slots = null;

  function readSlots() {
    try {
      const saved = JSON.parse(localStorage.getItem(COLORS_KEY)) ?? {};
      return Object.fromEntries(Object.entries(saved).filter(([, slot]) => Number.isInteger(slot) && slot >= 0 && slot < COLOR_COUNT));
    } catch (ignored) {
      return {};
    }
  }

  function saveSlots() {
    try {
      localStorage.setItem(COLORS_KEY, JSON.stringify(slots));
    } catch (ignored) { /* stockage indisponible : les couleurs seront réattribuées au prochain chargement */ }
  }

  function color(name) {
    slots ??= readSlots();
    if (!Object.hasOwn(slots, name)) {
      const uses = Array(COLOR_COUNT).fill(0);
      Object.values(slots).forEach(slot => uses[slot]++);
      slots[name] = uses.indexOf(Math.min(...uses));
      saveSlots();
    }
    return `var(--avatar-${slots[name]})`;
  }

  const initials = name => name.split(/\s+/).map(part => part[0] ?? "").join("").slice(0, 2).toUpperCase();

  // « Jane DOE », « doe », « jane.doe » : mêmes mots, sans casse, accents ni ordre.
  const words = text => text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase()
    .split(/[\s._-]+/).filter(Boolean).sort().join(" ");

  // Nom GitLab d'un auteur git, déjà connu du tableau des MR : le nom git est libre (« doe »), la partie
  // locale de l'e-mail suit en général le prénom et le nom. Inconnu : son nom git.
  function gitlabName(name, email) {
    slots ??= readSlots();
    const wanted = [words(name), words(email.split("@")[0])];
    return Object.keys(slots).find(known => wanted.includes(words(known))) ?? name;
  }

  return { color, initials, gitlabName };
})();
