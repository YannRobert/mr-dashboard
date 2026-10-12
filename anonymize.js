// Mode anonymisation, pour des captures d'écran montrables hors de l'équipe : à l'écran seulement, les noms
// des personnes deviennent des noms fictifs, intitulés et messages du lorem ipsum, les branches des slugs
// lorem, les labels des mots lorem, les numéros de MR décalés, le projet « demo/project », et le corps
// des commentaires du lorem ipsum. Les données de la page
// ne changent pas : actions, liens et filtres continuent d'agir sur les vraies valeurs, et désactiver le
// mode rend l'affichage d'origine sans recharger. Partagé par index.html et comments.html.
//
// Chaque valeur fictive dépend d'un sel aléatoire gardé dans le navigateur : la même personne garde le
// même faux nom d'un rafraîchissement et d'un onglet à l'autre, et aucun mot du texte d'origine n'est
// repris, ce qui empêche de remonter à l'original depuis une capture.
window.Anonymizer = (() => {
  const STORAGE_KEY = "mr-dashboard.anonymize";
  // Prénoms et noms d'exemple de plusieurs pays (John Doe, Erika Mustermann, Ola Nordmann…) : ils se
  // lisent comme fictifs.
  const FIRST_NAMES = [
    "Alice", "Bob", "Carol", "Dave", "Erin", "Frank", "Grace", "Heidi", "Ivan", "Judy", "Mallory", "Niaj",
    "Olivia", "Peggy", "Rupert", "Sybil", "Trent", "Victor", "Walter", "Wendy", "Jane", "John", "Max",
    "Erika", "Hans", "Marie", "Jean", "Lucia", "Mario", "Ola", "Kari", "Joe", "Anna", "Jan", "Sven",
    "Ingrid", "Pablo", "Carmen", "Tomasz", "Zofia", "Matti", "Aino", "Seán", "Aoife", "Luca", "Giulia",
  ];
  const LAST_NAMES = [
    "Doe", "Roe", "Smith", "Bloggs", "Public", "Mustermann", "Musterfrau", "Dupont", "Durand", "Rossi",
    "Bianchi", "Nordmann", "Jansen", "Kowalski", "Novák", "Martin", "García", "Schmidt", "Müller",
    "Moreau", "Lefebvre", "Svensson", "Virtanen", "Murphy", "Pérez", "Fernández", "Esposito", "Nowak",
    "Horvat", "Papadopoulos", "Jensen", "Hansen", "Silva", "Santos", "Peeters", "Meier", "Fischer",
    "Weber", "Wagner", "Bernard", "Petit", "Ricci", "Kelly", "Walsh", "Korhonen", "Lindqvist",
  ];
  const LOREM = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et " +
    "dolore magna aliqua enim ad minim veniam quis nostrud exercitation ullamco laboris nisi aliquip ex ea " +
    "commodo consequat duis aute irure in reprehenderit voluptate velit esse cillum fugiat nulla pariatur " +
    "excepteur sint occaecat cupidatat non proident sunt culpa qui officia deserunt mollit anim id est laborum"
  ).split(" ");
  // Type d'une branche (feature/…), gardé : il ne dit rien du sujet.
  const BRANCH_TYPES = new Set(["feature", "feat", "fix", "bugfix", "hotfix", "release", "chore", "docs", "refactor", "test"]);
  // Branches partagées, gardées : elles ne disent rien du sujet des MR.
  const SHARED_BRANCHES = ["main", "master", "develop"];
  const TICKET = /^[A-Z][A-Z0-9]+-\d+$/;
  const LEADING_TICKET = /^\[?([A-Z][A-Z0-9]+-\d+)\]?\s*/;
  const LEADING_SYMBOLS = /^(Draft:\s*)?([\p{Extended_Pictographic}️‍\s]*)/iu;
  const ATTRIBUTES = ["title", "aria-label"];

  // Lecture des données : clés qui portent une personne, un texte libre, une branche.
  const PERSON_CONTEXT = /author|user|assignee|reviewer|approv|committer|merged_?by|closed_?by|participant/i;
  const PERSON_KEYS = new Set(["author", "author_name", "committer_name", "authorName"]);
  const NAME_LIST_KEYS = new Set(["names", "changesRequested"]);
  const LABEL_LIST_KEYS = new Set(["labels"]);
  const TEXT_KEYS = new Set(["title", "description", "message", "body"]);
  const BRANCH_KEYS = new Set(["source_branch", "sourceBranch", "target_branch", "targetBranch", "branch", "ref"]);
  // Clés d'un tableau GraphQL ou d'un index : la personne se lit dans la clé au-dessus.
  const TRANSPARENT_KEYS = /^(\d+|nodes|edges|node)$/;
  // En deçà, un nom ou un texte remplacerait aussi des mots de l'interface.
  const MIN_TOKEN_LENGTH = 3;
  const MIN_TEXT_LENGTH = 8;

  let settings = readSettings();
  let page = null;
  let observer = null;
  let pattern = null;
  let replacements = new Map();
  // Faux prénom et faux nom par prénom et nom réels (normalisés), et valeurs fictives déjà prises.
  const firstNames = new Map();
  const lastNames = new Map();
  const taken = { first: new Set(), last: new Set() };
  // Valeur d'origine et valeur écrite de chaque nœud texte, attribut ou bloc opaque modifié ; un nœud
  // dont la valeur a changé depuis a été réécrit par la page, il est retraité tel quel.
  const texts = new WeakMap();
  const attributes = new WeakMap();
  const blocks = new WeakMap();
  const touched = new Set();

  function readSettings() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (typeof saved?.salt === "string") return { on: saved.on === true, salt: saved.salt };
    } catch (ignored) { /* stockage indisponible ou illisible : nouveau sel */ }
    const salt = [...crypto.getRandomValues(new Uint32Array(4))].map(n => n.toString(16)).join("");
    return { on: false, salt };
  }

  function saveSettings() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch (ignored) { /* stockage indisponible : le mode ne vaut que pour cette page */ }
  }

  // cyrb53 : hachage rapide, non cryptographique ; le sel inconnu suffit à rendre le lorem non inversible.
  function hash(
      kind,
      text
  ) {
    const input = `${settings.salt}\u0000${kind}\u0000${text}`;
    let h1 = 0xdeadbeef;
    let h2 = 0x41c6ce57;
    for (let i = 0; i < input.length; i++) {
      const code = input.charCodeAt(i);
      h1 = Math.imul(h1 ^ code, 2654435761);
      h2 = Math.imul(h2 ^ code, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return 4294967296 * (2097151 & h2) + (h1 >>> 0);
  }

  // mulberry32, amorcé par le hachage du texte : la même entrée donne toujours le même lorem.
  function generator(
      kind,
      text
  ) {
    let seed = hash(kind, text) >>> 0;
    return bound => {
      seed = (seed + 0x6d2b79f5) >>> 0;
      let t = seed;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return (((t ^ (t >>> 14)) >>> 0) / 4294967296 * bound) | 0;
    };
  }

  const normalize = text => text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim();
  const capitalize = word => word.charAt(0).toUpperCase() + word.slice(1);

  function loremWords(
      kind,
      seed,
      length
  ) {
    const next = generator(kind, seed);
    const words = [];
    let size = -1;
    do {
      const word = LOREM[next(LOREM.length)];
      words.push(word);
      size += word.length + 1;
    } while (size < length);
    return words;
  }

  const fakeTicket = ticket => `DEMO-${100 + hash("ticket", ticket) % 900}`;

  // Draft, emoji et ticket de tête gardés (le ticket fictif) ; le reste en lorem de même longueur.
  function fakeLine(line) {
    const [prefix, draft = "", symbols = ""] = line.match(LEADING_SYMBOLS);
    let rest = line.slice(prefix.length);
    let ticket = "";
    const leading = rest.match(LEADING_TICKET);
    if (leading) {
      ticket = leading[0].replace(leading[1], fakeTicket(leading[1]));
      rest = rest.slice(leading[0].length);
    }
    if (!rest.trim()) return draft + symbols + ticket + rest;
    const words = loremWords("text", rest, rest.trim().length);
    words[0] = capitalize(words[0]);
    return draft + symbols + ticket + words.join(" ");
  }

  const fakeText = text => text.split("\n").map(line => (line.trim() ? fakeLine(line) : line)).join("\n");

  function fakeBranch(branch) {
    const segments = branch.split("/");
    return segments.map((segment, i) => {
      if (i === 0 && segments.length > 1 && BRANCH_TYPES.has(segment)) return segment;
      if (TICKET.test(segment)) return fakeTicket(segment);
      const next = generator("branch", segment);
      const words = Math.min(4, Math.max(2, segment.split(/[-_.]+/).filter(Boolean).length));
      return Array.from({ length: words }, () => LOREM[next(LOREM.length)]).join("-");
    }).join("/");
  }

  // Un faux nom par prénom (et par nom) réel, distinct de ceux des autres : deux personnes qui partagent
  // un prénom le partagent aussi à l'écran, où prénom et nom s'affichent parfois séparément.
  function fakeName(
      real,
      catalog,
      known,
      used
  ) {
    const key = normalize(real);
    if (!known.has(key)) {
      let index = hash(catalog === FIRST_NAMES ? "first" : "last", key) % catalog.length;
      for (let tries = 0; used.has(index) && tries < catalog.length; tries++) index = (index + 1) % catalog.length;
      used.add(index);
      known.set(key, catalog[index]);
    }
    const fake = known.get(key);
    // « DOE » s'écrit en capitales : son faux nom aussi.
    return real.length > 1 && real === real.toUpperCase() ? fake.toUpperCase() : fake;
  }

  function fakePerson(name) {
    const [first, ...others] = name.trim().split(/\s+/);
    const rest = others.join(" ");
    // Un nom d'un seul mot (auteur git) : prénom et nom fictifs tirés de ce mot.
    const fakeFirst = fakeName(rest ? first : `${first}\u0000first`, FIRST_NAMES, firstNames, taken.first);
    const fakeLast = fakeName(rest || first, LAST_NAMES, lastNames, taken.last);
    return { first: fakeFirst, last: fakeLast, full: `${fakeFirst} ${fakeLast}`, rest };
  }

  const fakeUsername = fake => normalize(`${fake.first.charAt(0)}${fake.last}`).replace(/[^a-z0-9]/g, "");

  function addReplacement(
      real,
      fake,
      minLength = MIN_TOKEN_LENGTH
  ) {
    if (typeof real === "string" && real.length >= minLength && real !== fake) replacements.set(real, fake);
  }

  // Numéros de MR décalés d'un même écart tiré du sel : ordre et écarts gardés, valeurs méconnaissables.
  function addIid(iid) {
    const number = Number(iid);
    if (!Number.isInteger(number) || number <= 0) return;
    addReplacement(`!${number}`, `!${number + 100 + hash("iid", "") % 800}`, 2);
  }

  // Label : un mot lorem par mot, la portée d'un label « portée::valeur » comprise.
  function addLabel(label) {
    const fake = label.split("::").map(part => {
      const next = generator("label", part);
      const words = part.split(/[\s_-]+/).filter(Boolean).map(word => {
        const lorem = LOREM[next(LOREM.length)];
        return word.charAt(0) === word.charAt(0).toUpperCase() && word.charAt(0) !== word.charAt(0).toLowerCase() ? capitalize(lorem) : lorem;
      });
      return words.join(part.includes("_") ? "_" : part.includes("-") ? "-" : " ");
    }).join("::");
    addReplacement(label, fake, 2);
  }

  function addPerson(
      name,
      username
  ) {
    if (!name?.trim()) return;
    const fake = fakePerson(name);
    addReplacement(name.trim(), fake.full);
    if (fake.rest) {
      addReplacement(name.trim().split(/\s+/)[0], fake.first);
      addReplacement(fake.rest, fake.last);
    }
    if (username) addReplacement(username, fakeUsername(fake));
  }

  function addText(text) {
    if (text.trim().length < MIN_TEXT_LENGTH || !/\s/.test(text.trim())) return;
    addReplacement(text, fakeText(text));
    // Le tableau affiche les titres sans « Draft: », et un message de commit par sa première ligne.
    const firstLine = text.split("\n")[0];
    addReplacement(firstLine, fakeLine(firstLine));
    const withoutDraft = firstLine.replace(/^Draft:\s*/i, "");
    addReplacement(withoutDraft, fakeLine(withoutDraft));
    // Sans emoji ni ticket de tête, et le ticket seul : même lorem, même ticket fictif.
    const [prefix] = firstLine.match(LEADING_SYMBOLS);
    const rest = firstLine.slice(prefix.length);
    const leading = rest.match(LEADING_TICKET);
    if (leading) {
      addTicket(leading[1]);
      addReplacement(rest.slice(leading[0].length), fakeLine(rest.slice(leading[0].length)));
    }
  }

  function addTicket(ticket) {
    addReplacement(ticket, fakeTicket(ticket));
  }

  function addBranch(
      branch,
      kept
  ) {
    if (kept.has(branch)) return;
    addReplacement(branch, fakeBranch(branch));
    branch.split("/").filter(segment => TICKET.test(segment)).forEach(addTicket);
  }

  // Parcourt les données de la page et range chaque valeur selon sa clé ; ne descend que dans les objets
  // simples, tableaux et Map (ni nœud du DOM, ni notification).
  function harvest(
      value,
      key,
      context,
      kept,
      seen
  ) {
    if (key === "iid" && (typeof value === "number" || typeof value === "string")) {
      addIid(value);
      return;
    }
    if (typeof value === "string") {
      if (PERSON_KEYS.has(key)) addPerson(value);
      else if (TEXT_KEYS.has(key)) addText(value);
      else if (BRANCH_KEYS.has(key)) addBranch(value, kept);
      return;
    }
    if (!value || typeof value !== "object" || seen.has(value)) return;
    seen.add(value);
    if (value instanceof Map) {
      for (const item of value.values()) harvest(item, key, context, kept, seen);
      return;
    }
    if (Array.isArray(value)) {
      if (NAME_LIST_KEYS.has(key)) value.forEach(name => typeof name === "string" && addPerson(name));
      else if (LABEL_LIST_KEYS.has(key)) value.forEach(label => typeof label === "string" && addLabel(label));
      else value.forEach(item => harvest(item, key, context, kept, seen));
      return;
    }
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) return;
    if (typeof value.name === "string" && (typeof value.username === "string" || PERSON_CONTEXT.test(context))) {
      addPerson(value.name, value.username);
    }
    for (const [childKey, child] of Object.entries(value)) {
      harvest(child, childKey, TRANSPARENT_KEYS.test(childKey) ? context : childKey, kept, seen);
    }
  }

  function rebuild() {
    replacements = new Map();
    const kept = new Set([...SHARED_BRANCHES, ...page.keptBranches().filter(Boolean)]);
    for (const [real, fake] of page.fixed()) addReplacement(real, fake);
    harvest(page.data(), "", "", kept, new WeakSet());
    const keys = [...replacements.keys()].sort((a, b) => b.length - a.length)
      .map(key => key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    // Jamais au milieu d'un mot : « Jean » ne touche pas « Jeanne ».
    pattern = keys.length ? new RegExp(`(?<![\\p{L}\\p{N}_])(?:${keys.join("|")})(?![\\p{L}\\p{N}_])`, "gu") : null;
  }

  const replace = text => (pattern && text ? text.replace(pattern, match => replacements.get(match) ?? match) : text);

  const initials = name => name.split(/\s+/).map(part => part[0] ?? "").join("").slice(0, 2).toUpperCase();

  function write(
      store,
      target,
      original,
      value,
      apply
  ) {
    if (value === original) return;
    store.set(target, { original, value });
    touched.add(target);
    apply(value);
  }

  function anonymizeText(node) {
    const previous = texts.get(node);
    if (previous && previous.value === node.nodeValue) return;
    const original = node.nodeValue;
    write(texts, node, original, replace(original), value => { node.nodeValue = value; });
  }

  function anonymizeAttribute(
      element,
      name
  ) {
    const current = element.getAttribute(name);
    if (current == null) return;
    const saved = attributes.get(element) ?? {};
    if (saved[name]?.value === current) return;
    const value = replace(current);
    if (value === current) return;
    saved[name] = { original: current, value };
    attributes.set(element, saved);
    touched.add(element);
    element.setAttribute(name, value);
  }

  // Pastille d'une personne : initiales de son faux nom ; sa couleur, qui ne dit rien d'elle, reste.
  function anonymizeAvatar(element) {
    const node = element.firstChild;
    if (node?.nodeType !== Node.TEXT_NODE) return;
    const previous = texts.get(node);
    if (previous && previous.value === node.nodeValue) return;
    write(texts, node, node.nodeValue, initials(fakePerson(element.dataset.name).full), value => { node.nodeValue = value; });
  }

  // Bloc dont tout le contenu est remplacé, mise en forme comprise : le corps d'un commentaire.
  function anonymizeBlock(element) {
    const previous = blocks.get(element);
    if (previous && previous.value === element.innerHTML) return;
    const text = element.textContent.trim();
    if (!text) return;
    const original = element.innerHTML;
    const paragraphs = text.split(/\n\s*\n/).map(paragraph => {
      const words = loremWords("block", paragraph, Math.min(paragraph.length, 600));
      words[0] = capitalize(words[0]);
      return `<p>${words.join(" ")}.</p>`;
    });
    element.innerHTML = paragraphs.join("");
    blocks.set(element, { original, value: element.innerHTML });
    touched.add(element);
  }

  const skipped = node => node.parentElement?.closest(`script, style${page.opaque ? `, ${page.opaque}` : ""}`);

  function anonymizeTree(root) {
    if (root.nodeType === Node.TEXT_NODE) {
      if (!skipped(root)) anonymizeText(root);
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE || root.closest("script, style")) return;
    if (page.opaque && root.closest(page.opaque)) {
      anonymizeBlock(root.closest(page.opaque));
      return;
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: node => (skipped(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    for (let node = walker.nextNode(); node; node = walker.nextNode()) anonymizeText(node);
    const elements = [root, ...root.querySelectorAll("*")];
    for (const element of elements) {
      for (const name of ATTRIBUTES) anonymizeAttribute(element, name);
    }
    for (const element of elements.filter(e => e.matches(".avatar[data-name]"))) anonymizeAvatar(element);
    if (page.opaque) elements.filter(e => e.matches(page.opaque)).forEach(anonymizeBlock);
  }

  function onMutations(records) {
    rebuild();
    for (const record of records) {
      if (record.type === "childList") record.addedNodes.forEach(anonymizeTree);
      else if (record.type === "characterData") anonymizeTree(record.target);
      else if (record.type === "attributes") anonymizeAttribute(record.target, record.attributeName);
    }
    // Les nœuds retirés de la page n'ont plus rien à restaurer.
    if (touched.size > 5000) [...touched].filter(node => !node.isConnected).forEach(node => touched.delete(node));
  }

  function enable() {
    if (observer || !page) return;
    rebuild();
    anonymizeTree(document.documentElement);
    observer = new MutationObserver(onMutations);
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRIBUTES,
    });
  }

  // Rend la valeur d'origine de ce qui n'a pas été réécrit par la page depuis.
  function disable() {
    if (!observer) return;
    observer.disconnect();
    observer = null;
    for (const target of touched) {
      const text = texts.get(target);
      if (text && target.nodeValue === text.value) target.nodeValue = text.original;
      const block = blocks.get(target);
      if (block && target.innerHTML === block.value) target.innerHTML = block.original;
      for (const [name, saved] of Object.entries(attributes.get(target) ?? {})) {
        if (target.getAttribute(name) === saved.value) target.setAttribute(name, saved.original);
      }
    }
    touched.clear();
  }

  function syncButtons() {
    document.documentElement.classList.toggle("anonymized", settings.on);
    document.querySelectorAll("[data-anonymize]").forEach(button => button.setAttribute("aria-pressed", String(settings.on)));
  }

  function apply() {
    syncButtons();
    if (settings.on) enable();
    else disable();
  }

  function toggle() {
    settings = { ...settings, on: !settings.on };
    saveSettings();
    apply();
  }

  // Bouton [data-anonymize] : active ou désactive le mode, pour tous les onglets du dashboard.
  document.addEventListener("click", event => {
    if (event.target.closest("[data-anonymize]")) toggle();
  });

  window.addEventListener("storage", event => {
    if (event.key !== STORAGE_KEY && event.key !== null) return;
    const next = readSettings();
    if (next.on === settings.on && next.salt === settings.salt) return;
    settings = next;
    apply();
  });

  // La page fournit ses données, ses branches partagées en plus de main, master et develop, les paires
  // vraie valeur → valeur fictive qu'elle seule connaît (le projet), et le sélecteur des blocs remplacés
  // en entier.
  function attach(options) {
    page = {
      data: options.data,
      keptBranches: options.keptBranches ?? (() => []),
      fixed: options.fixed ?? (() => []),
      opaque: options.opaque ?? null,
    };
    apply();
  }

  // Texte affiché hors de la page (notification) : anonymisé tant que le mode est actif.
  function text(value) {
    if (!settings.on || !page || typeof value !== "string") return value;
    rebuild();
    return replace(value);
  }

  return { attach, text, active: () => settings.on };
})();
