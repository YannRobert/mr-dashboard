// Colored badge of an author, shared by index.html and diff.html: an author gets the same color in both.
window.Avatars = (() => {
  const COLORS_KEY = "mr-dashboard.avatar-colors";
  // Number of --avatar-<n> colors defined for each theme, ordered from most to least distinct.
  const COLOR_COUNT = 8;

  // A color derived from the name could give the same one, or a close one, to two authors. Each new author takes
  // the least used color and keeps it: remembered across loads, it does not change either when
  // the merged MRs view brings in other authors.
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
    } catch (ignored) { /* storage unavailable: colors will be reassigned on next load */ }
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

  // « Jane DOE », « doe », « jane.doe »: same words, ignoring case, accents and order.
  const words = text => text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase()
    .split(/[\s._-]+/).filter(Boolean).sort().join(" ");

  // GitLab name of a git author, already known from the MR table: the git name is free-form (« doe »), the
  // local part of the email usually follows first and last name. Unknown: their git name.
  function gitlabName(name, email) {
    slots ??= readSlots();
    const wanted = [words(name), words(email.split("@")[0])];
    return Object.keys(slots).find(known => wanted.includes(words(known))) ?? name;
  }

  return { color, initials, gitlabName };
})();
