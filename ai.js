// Bouton AI d'une MR : un dialogue propose les actions du catalogue du projet suivi (cf. ai_actions.py),
// et le prompt de l'action choisie, à copier dans Claude Code ou à lancer dans un onglet Orca.
// Partagé par index.html (une ligne par MR) et diff.html (la MR du diff).
window.MrAi = (() => {
  const TEXTS = {
    fr: {
      "ai": "AI",
      "ai.title": "Afficher un prompt Claude Code pour cette MR",
      "ai.title.toFix": "Afficher un prompt Claude Code pour cette MR, qui a quelque chose à corriger",
      "ai.fix": "Corriger",
      "ai.free": "Libre",
      "dialog.title": p => `Claude Code sur la MR !${p.iid}`,
      "dialog.actions": "Action",
      "dialog.catalogError": p => `Catalogue des actions AI illisible : ${p.message}`,
      "dialog.hint": "Prompt à compléter ou retoucher ici si besoin, puis à coller dans Claude Code, lancé à la racine du dépôt — ou à lancer directement dans Orca.",
      "dialog.hint.free": "Prompt à rédiger ici, puis à coller dans Claude Code, lancé à la racine du dépôt — ou à lancer directement dans Orca.",
      "dialog.reset": "Prompt d'origine",
      "dialog.reset.title": "Remplace le prompt modifié par celui de l'action",
      "dialog.aria": "Prompt pour Claude Code",
      "dialog.close": "Fermer",
      "dialog.copy": "Copier",
      "dialog.copied": "Copié",
      "dialog.orca": "Ouvrir dans Orca",
      "dialog.orca.title": "Lance Claude Code avec ce prompt dans un nouvel onglet Orca, sur le worktree principal",
      "dialog.model": "Modèle",
      "dialog.model.title": "Modèle de la session lancée dans Orca. Un prompt copié prend celui de la session où on le colle : /model pour en changer.",
      "dialog.model.default": "par défaut",
      "dialog.effort": "Effort",
      "dialog.effort.title": "Niveau d'effort de la session lancée dans Orca : bas pour une tâche simple, qui coûte moins, élevé pour une tâche difficile. Un prompt copié prend celui de la session où on le colle : /effort pour en changer.",
      "dialog.effort.default": "par défaut",
      "dialog.effort.low": "Bas",
      "dialog.effort.medium": "Moyen",
      "dialog.effort.high": "Élevé",
      "dialog.effort.xhigh": "Très élevé",
      "dialog.effort.max": "Maximal",
      "dialog.orca.opening": "Ouverture dans Orca…",
      "dialog.orca.opened": "Session lancée dans Orca",
      "dialog.orca.unconfirmed": "Orca n'a pas confirmé à temps : bascule sur Orca, l'onglet s'y ouvre dès que sa fenêtre est au premier plan",
      "dialog.orca.failed": p => `Échec : ${p.message}`,
    },
    en: {
      "ai": "AI",
      "ai.title": "Show a Claude Code prompt for this MR",
      "ai.title.toFix": "Show a Claude Code prompt for this MR, which has something to fix",
      "ai.fix": "Fix",
      "ai.free": "Free",
      "dialog.title": p => `Claude Code on MR !${p.iid}`,
      "dialog.actions": "Action",
      "dialog.catalogError": p => `Unreadable AI actions catalogue: ${p.message}`,
      "dialog.hint": "Prompt to complete or adjust here if needed, then paste into Claude Code, started at the repository root — or to start directly in Orca.",
      "dialog.hint.free": "Prompt to write here, then paste into Claude Code, started at the repository root — or to start directly in Orca.",
      "dialog.reset": "Original prompt",
      "dialog.reset.title": "Replace the edited prompt with the action's own",
      "dialog.aria": "Prompt for Claude Code",
      "dialog.close": "Close",
      "dialog.copy": "Copy",
      "dialog.copied": "Copied",
      "dialog.orca": "Open in Orca",
      "dialog.orca.title": "Start Claude Code with this prompt in a new Orca tab, on the main worktree",
      "dialog.model": "Model",
      "dialog.model.title": "Model of the session started in Orca. A copied prompt runs on the model of the session it is pasted into: /model to change it.",
      "dialog.model.default": "default",
      "dialog.effort": "Effort",
      "dialog.effort.title": "Effort level of the session started in Orca: low for a simple task, which costs less, high for a hard one. A copied prompt runs at the effort of the session it is pasted into: /effort to change it.",
      "dialog.effort.default": "default",
      "dialog.effort.low": "Low",
      "dialog.effort.medium": "Medium",
      "dialog.effort.high": "High",
      "dialog.effort.xhigh": "Extra high",
      "dialog.effort.max": "Max",
      "dialog.orca.opening": "Opening in Orca…",
      "dialog.orca.opened": "Session started in Orca",
      "dialog.orca.unconfirmed": "Orca did not confirm in time: switch to Orca, the tab opens as soon as its window is in front",
      "dialog.orca.failed": p => `Failed: ${p.message}`,
    },
  };
  // Prompt de correction de chaque MR ouverte, calculé par le dashboard à chaque mise à jour de ses
  // données : seul lui charge les indicateurs CI et les threads dont il se nourrit. Le diff le relit.
  const FIX_CONTEXTS_KEY = "mr-dashboard.aiFixContexts";
  // Au-delà, plus aucun onglet du dashboard ne le tient à jour : la correction n'est plus proposée.
  const FIX_CONTEXT_MAX_AGE_MS = 30 * 60 * 1000;
  const ORCA_LOGO = `<svg class="orca-logo" viewBox="6.67 70.67 318.6 202.67" aria-hidden="true"><path fill="currentColor" d="m 177.81311,248.33334 c 23.82304,-41.29793 40.54045,-66.84626 49.51207,-75.66667 6.81685,-6.70196 10.07373,-8.7374 20.07265,-12.54475 34.57822,-13.16655 61.04674,-26.78733 72.37222,-37.24295 9.62924,-8.88966 9.34286,-9.01142 -23.43671,-9.964 -35.71756,-1.03796 -43.72989,0.42119 -62.17546,11.323 -16.72118,9.88265 -34.20103,30.11225 -42.74704,49.47157 -2.57353,5.82985 -14.81294,44.3056 -27.96399,87.90747 -2.86036,9.48343 -3.02466,11.71633 -0.86213,11.71633 0.44382,0 7.29659,-11.25 15.22839,-25 z m -65.14644,-8.32267 C 120,239.3326 130.5,237.50979 136,235.95998 c 5.5,-1.5498 12.25,-3.13783 15,-3.52895 2.75,-0.39111 5,-0.95485 5,-1.25275 0,-0.29789 2.15135,-7.58487 4.78078,-16.19328 8.49209,-27.80201 12.21334,-40.41629 21.13747,-71.65166 4.81891,-16.86667 11.23502,-39.185 14.25802,-49.596301 5.12803,-17.66103 5.74763,-23.07037 2.64253,-23.07037 -1.84887,0 -4.07048,6.908293 -16.72243,52.000001 -21.78975,77.65896 -20.80806,74.74393 -26.84794,79.72251 -7.5925,6.25838 -25.03916,14.82524 -36.10856,17.73044 -17.0947,4.48656 -33.410599,3.86724 -53.116765,-2.01622 -18.569242,-5.54403 -23.142662,-5.80284 -33.639754,-1.9037 -5.875424,2.18242 -9.864152,5.04363 -16.716684,11.99127 -4.95,5.0187 -9.0000001,10.02884 -9.0000001,11.13364 0,1.75174 5.9276921,2.00299 46.3333351,1.96383 25.483334,-0.0247 52.333338,-0.59969 59.666668,-1.27777 z M 252.69513,104.63708 c 12.18267,-3.48651 15.77304,-7.895503 9.63821,-11.835773 -10.19296,-6.546726 -36.19849,-1.77301 -41.19436,7.561863 -1.2556,2.3461 -0.98698,3.2037 1.68353,5.375 2.69471,2.19098 4.59991,2.47691 12.53928,1.88189 5.14899,-0.3859 12.94899,-1.72824 17.33334,-2.98298 z"/></svg>`;

  let lang = "fr";
  let orcaEnabled = () => false;
  let catalog = null;
  let dialog = null;
  // MR du dialogue ouvert, et ce que ses actions demandent : { mr, toFix, fixContext }.
  let current = null;
  // Prompts retouchés, modèles et niveaux d'effort choisis, par MR et par action, jusqu'au rechargement de la page : un
  // dialogue fermé par mégarde, ou une autre action essayée, ne perd pas ce qu'on y a changé.
  const drafts = new Map();
  const models = new Map();
  const efforts = new Map();

  function t(
    key,
    params = {}
  ) {
    const text = TEXTS[lang][key];
    return typeof text === "function" ? text(params) : text;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  async function request(
    path,
    init
  ) {
    const response = await fetch(
      path,
      init
    );
    let body = null;
    try {
      body = await response.json();
    } catch (ignored) { /* corps non JSON */ }
    if (!response.ok) throw new Error(`${response.status} ${body?.message || response.statusText}`);
    return body;
  }

  // options.orcaEnabled : fonction, la configuration du serveur pouvant arriver après.
  function init(options) {
    lang = options.lang;
    orcaEnabled = options.orcaEnabled;
    dialog = document.createElement("dialog");
    dialog.className = "ai-prompt";
    dialog.setAttribute("aria-labelledby", "ai-title");
    dialog.innerHTML = `
      <h2 id="ai-title"></h2>
      <div class="ai-actions" id="ai-actions" role="group"></div>
      <p class="ai-error" id="ai-error" hidden></p>
      <p id="ai-hint"></p>
      <textarea id="ai-text" spellcheck="false"></textarea>
      <div class="actions">
        <button type="button" id="ai-close" class="dismiss"></button>
        <span class="muted" id="ai-copied" aria-live="polite"></span>
        <button type="button" id="ai-reset" hidden></button>
        <label class="ai-model" id="ai-model-label" hidden><span id="ai-model-name"></span> <select id="ai-model"></select></label>
        <label class="ai-model" id="ai-effort-label" hidden><span id="ai-effort-name"></span> <select id="ai-effort"></select></label>
        <button type="button" id="ai-orca" class="with-icon" hidden>${ORCA_LOGO}<span id="ai-orca-label"></span></button>
        <button type="button" id="ai-copy" class="primary"></button>
      </div>`;
    document.body.append(dialog);
    applyTexts();
    part("ai-actions").addEventListener("click", event => {
      const button = event.target.closest("[data-ai-action]");
      if (button) select(actionsFor(current.toFix).find(action => action.id === button.dataset.aiAction));
    });
    part("ai-close").addEventListener("click", () => dialog.close());
    // Échap et un clic hors du dialogue le ferment aussi. Le clic doit commencer hors du dialogue : une
    // sélection du prompt relâchée au-dehors ne ferme rien.
    dialog.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      dialog.close();
    });
    let pressedOutside = false;
    dialog.addEventListener("pointerdown", event => pressedOutside = outside(event));
    dialog.addEventListener("click", event => {
      if (pressedOutside && outside(event)) dialog.close();
      pressedOutside = false;
    });
    part("ai-text").addEventListener("input", keepDraft);
    part("ai-model").addEventListener("change", keepModel);
    part("ai-effort").addEventListener("change", keepEffort);
    part("ai-reset").addEventListener("click", resetDraft);
    part("ai-copy").addEventListener("click", copy);
    part("ai-orca").addEventListener("click", openInOrca);
  }

  const part = id => dialog.querySelector(`#${id}`);

  // Un clic sur le fond d'un dialogue modal lui est adressé, comme un clic sur ses marges intérieures :
  // seule sa position les distingue.
  function outside(event) {
    if (event.target !== dialog) return false;
    const box = dialog.getBoundingClientRect();
    return event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom;
  }

  function applyTexts() {
    part("ai-actions").setAttribute("aria-label", t("dialog.actions"));
    part("ai-hint").textContent = t(dialog.dataset.action === "free" ? "dialog.hint.free" : "dialog.hint");
    part("ai-text").setAttribute("aria-label", t("dialog.aria"));
    part("ai-close").textContent = t("dialog.close");
    part("ai-orca").title = t("dialog.orca.title");
    part("ai-model-label").title = t("dialog.model.title");
    part("ai-model-name").textContent = t("dialog.model");
    const choice = part("ai-model").value;
    part("ai-model").innerHTML = ["", ...(catalog?.models ?? [])].map(model =>
      `<option value="${escapeHtml(model)}">${escapeHtml(model ? model[0].toUpperCase() + model.slice(1) : t("dialog.model.default"))}</option>`
    ).join("");
    part("ai-model").value = choice;
    part("ai-effort-label").title = t("dialog.effort.title");
    part("ai-effort-name").textContent = t("dialog.effort");
    const effort = part("ai-effort").value;
    part("ai-effort").innerHTML = ["", ...(catalog?.efforts ?? [])].map(level =>
      `<option value="${escapeHtml(level)}">${escapeHtml(t(`dialog.effort.${level || "default"}`) ?? level)}</option>`
    ).join("");
    part("ai-effort").value = effort;
    part("ai-orca-label").textContent = t("dialog.orca");
    part("ai-reset").textContent = t("dialog.reset");
    part("ai-reset").title = t("dialog.reset.title");
    part("ai-copy").textContent = t("dialog.copy");
  }

  function setLang(value) {
    lang = value;
    if (dialog) applyTexts();
  }

  // Relu à chaque ouverture du dialogue, pour essayer un prompt sans recharger la page.
  async function loadCatalog() {
    try {
      catalog = await request("ai/actions");
    } catch (error) {
      catalog = { actions: [], error: error.message };
    }
    return catalog;
  }

  // Les actions « to-fix » ne sont proposées qu'à une MR qui a quelque chose à corriger.
  const actionsFor = toFix => (catalog?.actions ?? []).filter(action => action.when !== "to-fix" || toFix);

  // Un catalogue illisible laisse le bouton : le dialogue dit pourquoi aucune action n'est proposée.
  const offered = toFix => !!catalog && (!!catalog.error || actionsFor(toFix).length > 0);

  const buttonTitle = toFix => t(toFix ? "ai.title.toFix" : "ai.title");

  // mr : { iid, title, source_branch, target_branch, web_url }. Variables inconnues laissées telles
  // quelles : le prompt affiché montre la faute de frappe. Il finit par une ligne vide : un clic sous le
  // texte y place le curseur, prêt pour ce qu'on veut ajouter. Celui de l'action libre reste vide.
  function prompt(action) {
    if (!action.prompt) return "";
    const { mr, fixContext } = current;
    const values = {
      iid: mr.iid,
      title: mr.title,
      source_branch: mr.source_branch,
      target_branch: mr.target_branch,
      web_url: mr.web_url,
      fix_context: fixContext,
    };
    const text = action.prompt.replace(/\{(\w+)\}/g, (variable, name) => values[name] != null ? String(values[name]) : variable);
    return `${text.trimEnd()}\n\n`;
  }

  // context : { toFix, fixContext }, ou une fonction qui le donne une fois le catalogue relu.
  async function open(
    mr,
    context
  ) {
    await loadCatalog();
    current = { mr, ...(typeof context === "function" ? context() : context) };
    const actions = actionsFor(current.toFix);
    dialog.dataset.iid = mr.iid;
    part("ai-title").textContent = t("dialog.title", { iid: mr.iid });
    part("ai-error").hidden = !catalog.error;
    part("ai-error").textContent = catalog.error ? t("dialog.catalogError", { message: catalog.error }) : "";
    part("ai-actions").innerHTML = actions.map(action =>
      `<button type="button" data-ai-action="${escapeHtml(action.id)}">${escapeHtml(action.label ?? t(`ai.${action.id}`))}</button>`
    ).join("");
    part("ai-actions").hidden = !actions.length;
    part("ai-orca").hidden = !orcaEnabled();
    part("ai-model-label").hidden = !orcaEnabled();
    part("ai-effort-label").hidden = !orcaEnabled();
    applyTexts();
    if (!dialog.open) dialog.showModal();
    select(actions[0]);
  }

  function select(action) {
    dialog.dataset.action = action?.id ?? "";
    // Le prompt libre, rédigé par qui l'envoie, n'a pas d'autre mode d'emploi que de l'écrire.
    part("ai-hint").textContent = t(action?.id === "free" ? "dialog.hint.free" : "dialog.hint");
    for (const button of part("ai-actions").querySelectorAll("[data-ai-action]")) {
      button.setAttribute("aria-pressed", String(button.dataset.aiAction === action?.id));
    }
    const text = part("ai-text");
    text.value = action ? drafts.get(draftKey()) ?? prompt(action) : "";
    text.readOnly = !action;
    part("ai-reset").hidden = !drafts.has(draftKey());
    part("ai-model").value = models.get(draftKey()) ?? action?.model ?? "";
    part("ai-effort").value = efforts.get(draftKey()) ?? action?.effort ?? "";
    part("ai-copied").textContent = "";
    part("ai-model").disabled = !action;
    part("ai-effort").disabled = !action;
    syncSendButtons();
    // Curseur sur la ligne vide de la fin, rien de sélectionné, le début du prompt à l'écran : ce qu'on
    // tape s'ajoute à la suite, sans rien remplacer.
    text.focus();
    text.setSelectionRange(text.value.length, text.value.length);
    text.scrollTop = 0;
  }

  const draftKey = () => `${dialog.dataset.iid} ${dialog.dataset.action}`;

  function keepDraft() {
    const action = actionsFor(current.toFix).find(candidate => candidate.id === dialog.dataset.action);
    const text = part("ai-text").value;
    if (!action || text === prompt(action)) drafts.delete(draftKey());
    else drafts.set(draftKey(), text);
    part("ai-reset").hidden = !drafts.has(draftKey());
    part("ai-copied").textContent = "";
    syncSendButtons();
  }

  // Rien à copier ni à lancer tant que le prompt est vide : celui de l'action libre, à son ouverture.
  function syncSendButtons() {
    const empty = !dialog.dataset.action || !promptToSend();
    for (const id of ["ai-orca", "ai-copy"]) part(id).disabled = empty;
  }

  // Modèle choisi pour l'action, gardé comme son prompt ; celui du catalogue n'a pas besoin de l'être.
  function keepModel() {
    const action = actionsFor(current.toFix).find(candidate => candidate.id === dialog.dataset.action);
    const model = part("ai-model").value;
    if (!action || model === (action.model ?? "")) models.delete(draftKey());
    else models.set(draftKey(), model);
  }

  // Niveau d'effort choisi pour l'action, gardé comme son modèle.
  function keepEffort() {
    const action = actionsFor(current.toFix).find(candidate => candidate.id === dialog.dataset.action);
    const effort = part("ai-effort").value;
    if (!action || effort === (action.effort ?? "")) efforts.delete(draftKey());
    else efforts.set(draftKey(), effort);
  }

  function resetDraft() {
    drafts.delete(draftKey());
    select(actionsFor(current.toFix).find(action => action.id === dialog.dataset.action));
  }

  // Ce qui part, copié ou lancé dans Orca : sans la ligne vide laissée pour écrire à la suite, ni les
  // blancs de fin, qui ne coûteraient que des tokens.
  const promptToSend = () => part("ai-text").value.trimEnd();

  async function copy() {
    const text = promptToSend();
    try {
      await navigator.clipboard.writeText(text);
    } catch (ignored) {
      // Copie de secours, qui ne copie que la sélection : le curseur revient ensuite où il était.
      const box = part("ai-text");
      const { selectionStart, selectionEnd } = box;
      box.setSelectionRange(0, text.length);
      document.execCommand("copy");
      box.setSelectionRange(selectionStart, selectionEnd);
    }
    part("ai-copied").textContent = t("dialog.copied");
  }

  // Le serveur ouvre un onglet Orca sur le worktree principal, qui lance Claude Code avec le prompt affiché.
  async function openInOrca() {
    const status = part("ai-copied");
    part("ai-orca").disabled = true;
    status.textContent = t("dialog.orca.opening");
    try {
      const body = await request(
        "orca/launch",
        {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-MR-Dashboard": "1" },
          body: JSON.stringify({
            iid: Number(dialog.dataset.iid),
            action: dialog.dataset.action,
            prompt: promptToSend(),
            model: part("ai-model").value || null,
            effort: part("ai-effort").value || null,
          }),
        }
      );
      status.textContent = t(body.confirmed ? "dialog.orca.opened" : "dialog.orca.unconfirmed", body);
    } catch (error) {
      status.textContent = t("dialog.orca.failed", { message: error.message });
    } finally {
      part("ai-orca").disabled = false;
    }
  }

  // contexts : { iid: { toFix, fixContext } }, pour toutes les MR ouvertes.
  function saveFixContexts(contexts) {
    try {
      localStorage.setItem(FIX_CONTEXTS_KEY, JSON.stringify({ at: Date.now(), contexts }));
    } catch (ignored) { /* stockage indisponible : le diff ne proposera pas la correction */ }
  }

  function readFixContext(iid) {
    try {
      const saved = JSON.parse(localStorage.getItem(FIX_CONTEXTS_KEY));
      if (saved && Date.now() - saved.at < FIX_CONTEXT_MAX_AGE_MS) return saved.contexts[iid] ?? { toFix: false };
    } catch (ignored) { /* stockage indisponible ou illisible */ }
    return { toFix: false };
  }

  return { FIX_CONTEXTS_KEY, init, setLang, t, loadCatalog, offered, buttonTitle, open, saveFixContexts, readFixContext };
})();
