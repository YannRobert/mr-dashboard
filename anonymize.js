// Anonymization mode, for screenshots that can be shown outside the team: on screen only, people's
// names become fictitious names, titles and messages become lorem ipsum, branches lorem slugs,
// labels lorem words, MR numbers are shifted, the project becomes « demo/project », comment
// bodies become lorem ipsum, and link addresses, which the browser shows on hover, become a
// neutral address. The page data does not change: actions, links and filters keep working on
// the real values, and turning the mode off restores the original display without reloading. Shared by
// index.html and comments.html.
//
// Each fictitious value depends on a random salt kept in the browser: the same person keeps the
// same fake name across refreshes and tabs, and no word of the original text is reused,
// which prevents tracing back to the original from a screenshot.
window.Anonymizer = (() => {
  const STORAGE_KEY = "mr-dashboard.anonymize";
  // Sample first and last names from several countries (John Doe, Erika Mustermann, Ola Nordmann…): they
  // read as fictitious.
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
  // Branch type (feature/…), kept: it says nothing about the subject.
  const BRANCH_TYPES = new Set(["feature", "feat", "fix", "bugfix", "hotfix", "release", "chore", "docs", "refactor", "test"]);
  // Shared branches, kept: they say nothing about the MRs' subject.
  const SHARED_BRANCHES = ["main", "master", "develop"];
  const TICKET = /^[A-Z][A-Z0-9]+-\d+$/;
  const LEADING_TICKET = /^\[?([A-Z][A-Z0-9]+-\d+)\]?\s*/;
  const LEADING_SYMBOLS = /^(Draft:\s*)?([\p{Extended_Pictographic}️‍\s]*)/iu;
  const ATTRIBUTES = ["title", "aria-label", "href"];
  // Address shown on hover for a link to another site (GitLab, Sonar…); for the dashboard, its
  // path without parameters.
  const STAND_IN_URL = "https://example.com/demo/project";
  // Delay after which a link revealed by a click gets its neutral address back.
  const REVEAL_DELAY = 1000;

  // Reading the data: keys holding a person, free text, a branch.
  const PERSON_CONTEXT = /author|user|assignee|reviewer|approv|committer|merged_?by|closed_?by|participant/i;
  const PERSON_KEYS = new Set(["author", "author_name", "committer_name", "authorName"]);
  const NAME_LIST_KEYS = new Set(["names", "changesRequested"]);
  const LABEL_LIST_KEYS = new Set(["labels"]);
  const TEXT_KEYS = new Set(["title", "description", "message", "body"]);
  const BRANCH_KEYS = new Set(["source_branch", "sourceBranch", "target_branch", "targetBranch", "branch", "ref"]);
  // Keys of a GraphQL array or an index: the person is read from the key above.
  const TRANSPARENT_KEYS = /^(\d+|nodes|edges|node)$/;
  // Below this, a name or text would also replace words of the UI.
  const MIN_TOKEN_LENGTH = 3;
  const MIN_TEXT_LENGTH = 8;

  let settings = readSettings();
  let page = null;
  let observer = null;
  let pattern = null;
  let replacements = new Map();
  // Fake first and last name per real (normalized) first and last name, and fictitious values already taken.
  const firstNames = new Map();
  const lastNames = new Map();
  const taken = { first: new Set(), last: new Set() };
  // Original value and written value of each modified text node, attribute or opaque block; a node
  // whose value has changed since was rewritten by the page, and is processed again as is.
  const texts = new WeakMap();
  const attributes = new WeakMap();
  const blocks = new WeakMap();
  const touched = new Set();
  // Links holding their real address for the duration of a click, and the timer that removes it.
  const revealed = new Map();

  function readSettings() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (typeof saved?.salt === "string") return { on: saved.on === true, salt: saved.salt };
    } catch (ignored) { /* storage unavailable or unreadable: new salt */ }
    const salt = [...crypto.getRandomValues(new Uint32Array(4))].map(n => n.toString(16)).join("");
    return { on: false, salt };
  }

  function saveSettings() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch (ignored) { /* storage unavailable: the mode applies to this page only */ }
  }

  // cyrb53: fast, non-cryptographic hash; the unknown salt is enough to make the lorem non-invertible.
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

  // mulberry32, seeded by the text hash: the same input always yields the same lorem.
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

  // Leading Draft, emoji and ticket kept (the ticket made fictitious); the rest as lorem of the same length.
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

  // One fake name per real first (and last) name, distinct from the others: two people sharing
  // a first name share it on screen too, where first and last names are sometimes shown separately.
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
    // « DOE » is written in capitals: so is its fake name.
    return real.length > 1 && real === real.toUpperCase() ? fake.toUpperCase() : fake;
  }

  function fakePerson(name) {
    const [first, ...others] = name.trim().split(/\s+/);
    const rest = others.join(" ");
    // A single-word name (git author): fictitious first and last names drawn from that word.
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

  // MR numbers shifted by the same salt-derived offset: order and gaps kept, values unrecognizable.
  function addIid(iid) {
    const number = Number(iid);
    if (!Number.isInteger(number) || number <= 0) return;
    addReplacement(`!${number}`, `!${number + 100 + hash("iid", "") % 800}`, 2);
  }

  // Label: one lorem word per word, including the scope of a « scope::value » label.
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
    // The table shows titles without « Draft: », and a commit message by its first line.
    const firstLine = text.split("\n")[0];
    addReplacement(firstLine, fakeLine(firstLine));
    const withoutDraft = firstLine.replace(/^Draft:\s*/i, "");
    addReplacement(withoutDraft, fakeLine(withoutDraft));
    // Without leading emoji or ticket, and the ticket alone: same lorem, same fictitious ticket.
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

  // Walks the page data and files each value by its key; only descends into plain
  // objects, arrays and Maps (no DOM node, no notification).
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
    // Never mid-word: « Jean » does not touch « Jeanne ».
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

  // http(s) link: neutral address; anchors, mailto: and other schemes kept.
  function fakeHref(href) {
    try {
      const url = new URL(href, location.href);
      if (url.protocol !== "http:" && url.protocol !== "https:") return href;
      if (url.origin !== location.origin) return STAND_IN_URL;
      return url.pathname === location.pathname && !url.search ? href : url.pathname;
    } catch (ignored) {
      return href;
    }
  }

  function anonymizeAttribute(
      element,
      name
  ) {
    const current = element.getAttribute(name);
    if (current == null || name === "href" && (element.localName !== "a" || revealed.has(element))) return;
    const saved = attributes.get(element) ?? {};
    if (saved[name]?.value === current) return;
    const value = name === "href" ? fakeHref(current) : replace(current);
    if (value === current) return;
    saved[name] = { original: current, value };
    attributes.set(element, saved);
    touched.add(element);
    element.setAttribute(name, value);
  }

  // A person's badge: initials of their fake name; its color, which says nothing about them, stays.
  function anonymizeAvatar(element) {
    const node = element.firstChild;
    if (node?.nodeType !== Node.TEXT_NODE) return;
    const previous = texts.get(node);
    if (previous && previous.value === node.nodeValue) return;
    write(texts, node, node.nodeValue, initials(fakePerson(element.dataset.name).full), value => { node.nodeValue = value; });
  }

  // Block whose whole content is replaced, formatting included: a comment body.
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
    // Nodes removed from the page have nothing left to restore.
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

  // Restores the original value of whatever the page has not rewritten since.
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

  // A followed link keeps its real address: it is restored for the duration of the click, before the page
  // (tabs.js tabs) or the browser reads it, then removed.
  function reveal(event) {
    const link = event.target.closest?.("a[href]");
    const saved = link && attributes.get(link)?.href;
    if (!saved) return;
    if (link.getAttribute("href") === saved.value) {
      revealed.set(link, null);
      link.setAttribute("href", saved.original);
    } else if (!revealed.has(link)) {
      return;
    }
    clearTimeout(revealed.get(link));
    revealed.set(link, setTimeout(() => {
      revealed.delete(link);
      if (observer && link.getAttribute("href") === saved.original) link.setAttribute("href", saved.value);
    }, REVEAL_DELAY));
  }

  for (const type of ["pointerdown", "click", "auxclick", "contextmenu"]) document.addEventListener(type, reveal, true);

  // [data-anonymize] button: turns the mode on or off, for all dashboard tabs.
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

  // The page provides its data, its shared branches in addition to main, master and develop, the
  // real value → fictitious value pairs only it knows (the project), and the selector of blocks replaced
  // entirely.
  function attach(options) {
    page = {
      data: options.data,
      keptBranches: options.keptBranches ?? (() => []),
      fixed: options.fixed ?? (() => []),
      opaque: options.opaque ?? null,
    };
    apply();
  }

  // Text shown outside the page (notification): anonymized while the mode is on.
  function text(value) {
    if (!settings.on || !page || typeof value !== "string") return value;
    rebuild();
    return replace(value);
  }

  return { attach, text, active: () => settings.on };
})();
