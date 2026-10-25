// AI button of an MR: a dialog offers the actions of the tracked project's catalog (see ai_actions.py),
// and the prompt of the chosen action, to copy into Claude Code or to launch in a tab of the launch target
// (Orca, herdr, a terminal).
// Shared by index.html (one row per MR) and diff.html (the diff's MR).
window.MrAi = (() => {
  const TEXTS = {
    fr: {
      "ai": "AI",
      "ai.title": "Afficher un prompt pour un agent de code, sur cette MR",
      "ai.title.toFix": "Afficher un prompt pour un agent de code, sur cette MR qui a quelque chose à corriger",
      "ai.fix": "Corriger",
      "ai.free": "Libre",
      "dialog.title": p => `${p.agent} sur la MR !${p.iid}`,
      "dialog.actions": "Action",
      "dialog.catalogError": p => `Catalogue des actions AI illisible : ${p.message}`,
      "dialog.hint": p => `Prompt à compléter ou retoucher ici si besoin, puis à coller dans ${p.agent}, lancé à la racine du dépôt${p.target ? ` — ou à lancer directement dans ${p.target}` : ""}.`,
      "dialog.hint.free": p => `Prompt à rédiger ici, puis à coller dans ${p.agent}, lancé à la racine du dépôt${p.target ? ` — ou à lancer directement dans ${p.target}` : ""}.`,
      "dialog.reset": "Prompt d'origine",
      "dialog.reset.title": "Remplace le prompt modifié par celui de l'action",
      "dialog.aria": p => `Prompt pour ${p.agent}`,
      "dialog.close": "Fermer",
      "dialog.copy": "Copier",
      "dialog.copied": "Copié",
      "dialog.launch": p => `Ouvrir dans ${p.target}`,
      "dialog.launch.title": p => `Lance ${p.agent} avec ce prompt dans un nouvel onglet de ${p.target}, sur le worktree principal`,
      "dialog.launch.in": "Ouvrir dans",
      "dialog.launch.again": "Lancer une autre session ?",
      "dialog.target.unavailable": p => `${p.name} (${{ "not running": "pas lancé", "not answering": "ne répond pas", "no session": "aucune session" }[p.reason] ?? p.reason})`,
      "dialog.launch.recent": p => `${p.agent} a déjà démarré dans ${p.target} pour ce prompt il y a ${p.seconds} s : clique à nouveau pour lancer une autre session.`,
      "dialog.target.title": "Où lancer la session : choisi ici au dernier moment, retenu par le navigateur",
      "dialog.agent": "Agent",
      "dialog.agent.title": "Agent de code qui reçoit le prompt, retenu par le navigateur",
      "dialog.model": "Modèle",
      "dialog.model.title": p => `Modèle de la session lancée dans ${p.target}. Un prompt copié prend celui de la session où on le colle : /model pour en changer.`,
      "dialog.model.default": "par défaut",
      "dialog.model.latest": "Dernière version",
      "dialog.model.versions": "Version précise",
      "dialog.effort": "Effort",
      "dialog.effort.title": p => `Niveau d'effort de la session lancée dans ${p.target} : bas pour une tâche simple, qui coûte moins, élevé pour une tâche difficile. Un prompt copié prend celui de la session où on le colle : /effort pour en changer.`,
      "dialog.effort.default": "par défaut",
      "dialog.effort.off": "Aucune",
      "dialog.effort.minimal": "Minimal",
      "dialog.effort.low": "Bas",
      "dialog.effort.medium": "Moyen",
      "dialog.effort.high": "Élevé",
      "dialog.effort.xhigh": "Très élevé",
      "dialog.effort.max": "Maximal",
      "dialog.effort.recommended": p => `${p.level} (recommandé)`,
      "dialog.launch.opening": p => `Ouverture dans ${p.target}…`,
      "dialog.launch.opened": p => `Onglet ouvert dans ${p.target}, en attente du démarrage de ${p.agent}…`,
      "dialog.launch.unconfirmed": p => `${p.target} n'a pas confirmé à temps : bascule sur ${p.target}, l'onglet s'y ouvre dès que sa fenêtre est au premier plan. En attente du démarrage de ${p.agent}…`,
      "dialog.launch.read": p => `Session ${p.agent} démarrée dans ${p.target}`,
      "dialog.launch.noShell": p => `Le shell du terminal n'a pas démarré en ${p.seconds} s : regarde dans ${p.target}`,
      "dialog.launch.unread": p => `Le shell a démarré, mais pas ${p.agent} en ${p.seconds} s : regarde dans ${p.target}`,
      "dialog.launch.failed": p => `Échec : ${p.message}`,
    },
    en: {
      "ai": "AI",
      "ai.title": "Show a prompt for a coding agent, on this MR",
      "ai.title.toFix": "Show a prompt for a coding agent, on this MR, which has something to fix",
      "ai.fix": "Fix",
      "ai.free": "Free",
      "dialog.title": p => `${p.agent} on MR !${p.iid}`,
      "dialog.actions": "Action",
      "dialog.catalogError": p => `Unreadable AI actions catalogue: ${p.message}`,
      "dialog.hint": p => `Prompt to complete or adjust here if needed, then paste into ${p.agent}, started at the repository root${p.target ? ` — or to start directly in ${p.target}` : ""}.`,
      "dialog.hint.free": p => `Prompt to write here, then paste into ${p.agent}, started at the repository root${p.target ? ` — or to start directly in ${p.target}` : ""}.`,
      "dialog.reset": "Original prompt",
      "dialog.reset.title": "Replace the edited prompt with the action's own",
      "dialog.aria": p => `Prompt for ${p.agent}`,
      "dialog.close": "Close",
      "dialog.copy": "Copy",
      "dialog.copied": "Copied",
      "dialog.launch": p => `Open in ${p.target}`,
      "dialog.launch.title": p => `Start ${p.agent} with this prompt in a new ${p.target} tab, on the main worktree`,
      "dialog.launch.in": "Open in",
      "dialog.launch.again": "Start another session?",
      "dialog.target.unavailable": p => `${p.name} (${p.reason})`,
      "dialog.launch.recent": p => `${p.agent} already started in ${p.target} for this prompt ${p.seconds} s ago: click again to start another session.`,
      "dialog.target.title": "Where to start the session: picked here at the last moment, remembered by the browser",
      "dialog.agent": "Agent",
      "dialog.agent.title": "Coding agent the prompt goes to, remembered by the browser",
      "dialog.model": "Model",
      "dialog.model.title": p => `Model of the session started in ${p.target}. A copied prompt runs on the model of the session it is pasted into: /model to change it.`,
      "dialog.model.default": "default",
      "dialog.model.latest": "Latest version",
      "dialog.model.versions": "Specific version",
      "dialog.effort": "Effort",
      "dialog.effort.title": p => `Effort level of the session started in ${p.target}: low for a simple task, which costs less, high for a hard one. A copied prompt runs at the effort of the session it is pasted into: /effort to change it.`,
      "dialog.effort.default": "default",
      "dialog.effort.off": "Off",
      "dialog.effort.minimal": "Minimal",
      "dialog.effort.low": "Low",
      "dialog.effort.medium": "Medium",
      "dialog.effort.high": "High",
      "dialog.effort.xhigh": "Extra high",
      "dialog.effort.max": "Max",
      "dialog.effort.recommended": p => `${p.level} (recommended)`,
      "dialog.launch.opening": p => `Opening in ${p.target}…`,
      "dialog.launch.opened": p => `Tab opened in ${p.target}, waiting for ${p.agent} to start…`,
      "dialog.launch.unconfirmed": p => `${p.target} did not confirm in time: switch to ${p.target}, the tab opens as soon as its window is in front. Waiting for ${p.agent} to start…`,
      "dialog.launch.read": p => `${p.agent} session started in ${p.target}`,
      "dialog.launch.noShell": p => `The terminal shell did not start within ${p.seconds} s: check ${p.target}`,
      "dialog.launch.unread": p => `The shell started, but not ${p.agent} within ${p.seconds} s: check ${p.target}`,
      "dialog.launch.failed": p => `Failed: ${p.message}`,
    },
  };
  // Fix prompt of each open MR, computed by the dashboard on every refresh of its data: only the
  // dashboard loads the CI indicators and threads it is built from. The diff reads it back.
  const FIX_CONTEXTS_KEY = "mr-dashboard.aiFixContexts";
  // Id of the launch target last picked in the dialog's menu.
  const LAUNCH_TARGET_KEY = "mr-dashboard.launchTarget";
  // Id of the coding agent last picked in the dialog's menu.
  const AGENT_KEY = "mr-dashboard.agent";
  // Model and effort level last picked for each agent: {agentId: {model, effort}}.
  const AGENT_CHOICES_KEY = "mr-dashboard.agentChoices";
  // Why each launch target cannot open a tab now, by id, as the server told when the dialog opened.
  let unavailable = {};
  // Beyond that, no dashboard tab keeps it up to date anymore: the fix is no longer offered.
  const FIX_CONTEXT_MAX_AGE_MS = 30 * 60 * 1000;
  const ORCA_LOGO = `<svg class="target-icon" viewBox="6.67 70.67 318.6 202.67" aria-hidden="true"><path fill="currentColor" d="m 177.81311,248.33334 c 23.82304,-41.29793 40.54045,-66.84626 49.51207,-75.66667 6.81685,-6.70196 10.07373,-8.7374 20.07265,-12.54475 34.57822,-13.16655 61.04674,-26.78733 72.37222,-37.24295 9.62924,-8.88966 9.34286,-9.01142 -23.43671,-9.964 -35.71756,-1.03796 -43.72989,0.42119 -62.17546,11.323 -16.72118,9.88265 -34.20103,30.11225 -42.74704,49.47157 -2.57353,5.82985 -14.81294,44.3056 -27.96399,87.90747 -2.86036,9.48343 -3.02466,11.71633 -0.86213,11.71633 0.44382,0 7.29659,-11.25 15.22839,-25 z m -65.14644,-8.32267 C 120,239.3326 130.5,237.50979 136,235.95998 c 5.5,-1.5498 12.25,-3.13783 15,-3.52895 2.75,-0.39111 5,-0.95485 5,-1.25275 0,-0.29789 2.15135,-7.58487 4.78078,-16.19328 8.49209,-27.80201 12.21334,-40.41629 21.13747,-71.65166 4.81891,-16.86667 11.23502,-39.185 14.25802,-49.596301 5.12803,-17.66103 5.74763,-23.07037 2.64253,-23.07037 -1.84887,0 -4.07048,6.908293 -16.72243,52.000001 -21.78975,77.65896 -20.80806,74.74393 -26.84794,79.72251 -7.5925,6.25838 -25.03916,14.82524 -36.10856,17.73044 -17.0947,4.48656 -33.410599,3.86724 -53.116765,-2.01622 -18.569242,-5.54403 -23.142662,-5.80284 -33.639754,-1.9037 -5.875424,2.18242 -9.864152,5.04363 -16.716684,11.99127 -4.95,5.0187 -9.0000001,10.02884 -9.0000001,11.13364 0,1.75174 5.9276921,2.00299 46.3333351,1.96383 25.483334,-0.0247 52.333338,-0.59969 59.666668,-1.27777 z M 252.69513,104.63708 c 12.18267,-3.48651 15.77304,-7.895503 9.63821,-11.835773 -10.19296,-6.546726 -36.19849,-1.77301 -41.19436,7.561863 -1.2556,2.3461 -0.98698,3.2037 1.68353,5.375 2.69471,2.19098 4.59991,2.47691 12.53928,1.88189 5.14899,-0.3859 12.94899,-1.72824 17.33334,-2.98298 z"/></svg>`;
  // Icons drawn for this page, by kind of target, so as not to borrow other products' logos: panes for a
  // terminal multiplexer, a window for a terminal without tabs, a prompt for the others.
  const PANES_ICON = `<svg class="target-icon" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5"/><path d="M8 2.5v11M8 8h6.5"/></svg>`;
  const WINDOW_ICON = `<svg class="target-icon" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5"/><path d="M1.5 5.5h13"/></svg>`;
  const PROMPT_ICON = `<svg class="target-icon" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5"/><path d="M4.5 6.5l2 1.5-2 1.5M8 10.5h3.5"/></svg>`;
  const targetIcon = id => ({ orca: ORCA_LOGO, herdr: PANES_ICON, "terminal:tmux": PANES_ICON, "terminal:xterm": WINDOW_ICON }[id] ?? PROMPT_ICON);
  // Agents shown by a monogram, not by their makers' logos.
  const AGENT_MONOGRAMS = { claude: "C", codex: "Cx", pi: "π" };

  let lang = "fr";
  // Launch targets the server offers, [{id, name}] (Orca, herdr, terminals), in the order of its menu: none, and
  // prompts are only copied.
  let launchTargets = () => [];
  let catalog = null;
  let dialog = null;
  // MR of the open dialog, and what its actions need: { mr, toFix, fixContext }.
  let current = null;
  // Edited prompts, chosen models and effort levels, per MR and per action, until the page reloads: a
  // dialog closed by mistake, or another action tried, does not lose what was changed in it.
  const drafts = new Map();
  // A session launched lately, by MR, action, agent and target: { at, armed }. A second launch of the same within
  // RELAUNCH_CONFIRM_S asks for a second click, so that a click on a tab slow to show does not open two.
  const launched = new Map();
  const RELAUNCH_CONFIRM_S = 120;
  const RELAUNCH_ARMED_S = 5;
  let launching = false;
  const models = new Map();
  const efforts = new Map();

  function t(
    key,
    params = {}
  ) {
    const text = TEXTS[lang][key];
    return typeof text === "function" ? text({ target: launchTarget()?.name, agent: agent()?.name ?? "Claude Code", ...params }) : text;
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
    } catch (ignored) { /* non-JSON body */ }
    if (!response.ok) throw new Error(`${response.status} ${body?.message || response.statusText}`);
    return body;
  }

  // options.launchTargets: a function, since the server configuration may arrive later.
  function init(options) {
    lang = options.lang;
    launchTargets = options.launchTargets;
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
        <label class="ai-model" id="ai-agent-label" hidden><span id="ai-agent-name"></span> <span class="ai-monogram" id="ai-agent-monogram" aria-hidden="true"></span><select id="ai-agent"></select></label>
        <label class="ai-model" id="ai-model-label" hidden><span id="ai-model-name"></span> <select id="ai-model"></select></label>
        <label class="ai-model" id="ai-effort-label" hidden><span id="ai-effort-name"></span> <select id="ai-effort"></select></label>
        <span class="ai-launch" id="ai-launch-group" hidden><button type="button" id="ai-launch" class="with-icon"><span class="ai-icon" id="ai-launch-icon"></span><span id="ai-launch-label"></span></button><select id="ai-target"></select></span>
        <button type="button" id="ai-copy" class="primary"></button>
      </div>`;
    document.body.append(dialog);
    applyTexts();
    part("ai-actions").addEventListener("click", event => {
      const button = event.target.closest("[data-ai-action]");
      if (button) select(actionsFor(current.toFix).find(action => action.id === button.dataset.aiAction));
    });
    part("ai-close").addEventListener("click", () => dialog.close());
    // Escape and a click outside the dialog close it too. The click must start outside the dialog: a
    // prompt selection released outside closes nothing.
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
    part("ai-model").addEventListener("change", () => {
      keepModel();
      syncEfforts(part("ai-effort").value);
      keepEffort();
    });
    part("ai-effort").addEventListener("change", keepEffort);
    part("ai-reset").addEventListener("click", resetDraft);
    part("ai-copy").addEventListener("click", copy);
    part("ai-launch").addEventListener("click", launchSession);
    part("ai-agent").addEventListener("change", () => {
      try {
        localStorage.setItem(AGENT_KEY, part("ai-agent").value);
      } catch (ignored) { /* storage unavailable: the choice lasts until the page reloads */ }
      // Another agent, other models: back to its default model, and the action's one for Claude Code.
      part("ai-model").value = "";
      applyTexts();
      part("ai-title").textContent = t("dialog.title", { iid: dialog.dataset.iid });
      select(actionsFor(current.toFix).find(action => action.id === dialog.dataset.action));
    });
    part("ai-target").addEventListener("change", () => {
      try {
        localStorage.setItem(LAUNCH_TARGET_KEY, part("ai-target").value);
      } catch (ignored) { /* storage unavailable: the choice lasts until the page reloads */ }
      applyTexts();
    });
  }

  // The coding agent picked in the menu, else the one picked last time, else the first installed; null without any.
  function agent() {
    const agents = catalog?.agents ?? [];
    let saved = null;
    try {
      saved = localStorage.getItem(AGENT_KEY);
    } catch (ignored) { /* storage unavailable */ }
    const picked = dialog ? part("ai-agent").value : "";
    return agents.find(candidate => candidate.id === picked) ?? agents.find(candidate => candidate.id === saved) ?? agents[0] ?? null;
  }

  // The launch target picked in the menu, else the one picked last time, else the first offered, among those that can
  // open a tab now; null without any.
  function launchTarget() {
    const targets = launchTargets();
    let saved = null;
    try {
      saved = localStorage.getItem(LAUNCH_TARGET_KEY);
    } catch (ignored) { /* storage unavailable */ }
    const picked = dialog ? part("ai-target").value : "";
    const usable = targets.filter(target => !unavailable[target.id]);
    return usable.find(target => target.id === picked) ?? usable.find(target => target.id === saved) ?? usable[0] ?? null;
  }

  const part = id => dialog.querySelector(`#${id}`);

  // A click on the backdrop of a modal dialog targets the dialog itself, like a click on its padding:
  // only its position tells them apart.
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
    part("ai-launch").title = t("dialog.launch.title");
    // The chosen target's icon on the button, the chosen agent's monogram before its menu.
    part("ai-launch-icon").innerHTML = launchTarget() ? targetIcon(launchTarget().id) : "";
    part("ai-agent-monogram").textContent = AGENT_MONOGRAMS[agent()?.id] ?? "";
    part("ai-target").title = t("dialog.target.title");
    part("ai-target").setAttribute("aria-label", t("dialog.target.title"));
    part("ai-agent-label").title = t("dialog.agent.title");
    part("ai-agent-name").textContent = t("dialog.agent");
    const agents = catalog?.agents ?? [];
    const chosenAgent = agent();
    part("ai-agent").innerHTML = agents.map(candidate =>
      `<option value="${escapeHtml(candidate.id)}"${candidate.id === chosenAgent?.id ? " selected" : ""}>${escapeHtml(candidate.name)}</option>`
    ).join("");
    part("ai-model-label").title = t("dialog.model.title");
    part("ai-model-name").textContent = t("dialog.model");
    const choice = part("ai-model").value;
    const choices = chosenAgent?.models ?? [];
    const option = model => `<option value="${escapeHtml(model.id)}">${escapeHtml(modelLabel(model))}</option>`;
    const group = (label, list) => (list.length ? `<optgroup label="${escapeHtml(label)}">${list.map(option).join("")}</optgroup>` : "");
    // Aliases and versions apart for Claude Code; one group per provider for an agent that names them (Pi).
    const providers = [...new Set(choices.map(model => model.provider).filter(Boolean))];
    part("ai-model").innerHTML = `<option value="">${escapeHtml(t("dialog.model.default"))}</option>`
      + (choices.some(model => model.alias)
        ? group(t("dialog.model.latest"), choices.filter(model => model.alias)) + group(t("dialog.model.versions"), choices.filter(model => !model.alias))
        : providers.length
          ? providers.map(provider => group(provider, choices.filter(model => model.provider === provider))).join("")
          : choices.map(option).join(""));
    choose(part("ai-model"), choice);
    part("ai-effort-label").title = t("dialog.effort.title");
    part("ai-effort-name").textContent = t("dialog.effort");
    syncEfforts(part("ai-effort").value);
    // With a menu, the button reads "Open in" and the menu beside it names the target.
    part("ai-launch-label").textContent = t(launchTargets().length > 1 ? "dialog.launch.in" : "dialog.launch");
    part("ai-reset").textContent = t("dialog.reset");
    part("ai-reset").title = t("dialog.reset.title");
    part("ai-copy").textContent = t("dialog.copy");
  }

  // Alias: the version it points to today, if Claude Code provides it ("Opus (5.5)").
  function modelLabel(model) {
    if (!model.alias) return model.label;
    const version = model.version?.startsWith(model.label) ? model.version.slice(model.label.length).trim() : model.version;
    return version ? `${model.label} (${version})` : model.label;
  }

  // A value missing from the list, a model retired by Anthropic or a level the model refuses, keeps
  // the default choice.
  function choose(
    select,
    value
  ) {
    select.value = value;
    if (select.value !== value) select.value = "";
  }

  const chosenModel = () => (agent()?.models ?? []).find(model => model.id === part("ai-model").value);

  // Effort levels of the chosen model, its recommended level flagged; all the agent's for the default model,
  // which only the agent's configuration knows. A model without effort greys out the list.
  function syncEfforts(wanted) {
    const model = chosenModel();
    const levels = model ? model.efforts : agent()?.efforts ?? [];
    part("ai-effort").innerHTML = ["", ...levels].map(level => {
      const label = t(`dialog.effort.${level || "default"}`) ?? level;
      const text = level && level === model?.recommended ? t("dialog.effort.recommended", { level: label }) : label;
      return `<option value="${escapeHtml(level)}">${escapeHtml(text)}</option>`;
    }).join("");
    choose(part("ai-effort"), wanted);
    part("ai-effort").disabled = !dialog.dataset.action || !levels.length;
  }

  function setLang(value) {
    lang = value;
    if (dialog) applyTexts();
  }

  // Whether each launch target can open a tab now, asked on each dialog opening; on failure, all are offered.
  async function loadAvailability() {
    unavailable = {};
    if (launchTargets().length < 1) return;
    try {
      for (const target of await request("launch/targets")) if (target.unavailable) unavailable[target.id] = target.unavailable;
    } catch (ignored) { /* unknown: every target stays offered */ }
  }

  // Re-read on each dialog opening, to try a prompt without reloading the page.
  async function loadCatalog() {
    try {
      catalog = await request("ai/actions");
    } catch (error) {
      catalog = { actions: [], error: error.message };
    }
    return catalog;
  }

  // "to-fix" actions are offered only to an MR that has something to fix.
  const actionsFor = toFix => (catalog?.actions ?? []).filter(action => action.when !== "to-fix" || toFix);

  // An unreadable catalog keeps the button: the dialog says why no action is offered.
  const offered = toFix => !!catalog && (!!catalog.error || actionsFor(toFix).length > 0);

  const buttonTitle = toFix => t(toFix ? "ai.title.toFix" : "ai.title");

  // mr: { iid, title, source_branch, target_branch, web_url }. Unknown variables are left as
  // is: the displayed prompt shows the typo. It ends with an empty line: a click below the
  // text puts the cursor there, ready for whatever is added. The free action's prompt stays empty.
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

  // context: { toFix, fixContext }, or a function returning it once the catalog is re-read.
  async function open(
    mr,
    context
  ) {
    await Promise.all([loadCatalog(), loadAvailability()]);
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
    const targets = launchTargets();
    const chosen = launchTarget();
    // A target that cannot open a tab now stays listed, greyed out with the reason.
    part("ai-target").innerHTML = targets.map(target => {
      const reason = unavailable[target.id];
      const label = reason ? t("dialog.target.unavailable", { name: target.name, reason }) : target.name;
      return `<option value="${escapeHtml(target.id)}"${target.id === chosen?.id ? " selected" : ""}${reason ? " disabled" : ""}>${escapeHtml(label)}</option>`;
    }).join("");
    part("ai-target").hidden = targets.length < 2;
    // Shown even when no target can open a tab now: the greyed-out button and its menu say why.
    part("ai-launch-group").hidden = !targets.length;
    // The agent, its model and level only matter for a launch. They stay in place for every agent, greyed out on
    // the default when it offers none, so that changing agents moves nothing.
    part("ai-agent-label").hidden = !targets.length || (catalog?.agents ?? []).length < 2;
    part("ai-model-label").hidden = !targets.length;
    part("ai-effort-label").hidden = !targets.length;
    applyTexts();
    if (!dialog.open) dialog.showModal();
    select(actions[0]);
  }

  function select(action) {
    dialog.dataset.action = action?.id ?? "";
    // The free prompt, written by whoever sends it, needs no instructions beyond writing it.
    part("ai-hint").textContent = t(action?.id === "free" ? "dialog.hint.free" : "dialog.hint");
    for (const button of part("ai-actions").querySelectorAll("[data-ai-action]")) {
      button.setAttribute("aria-pressed", String(button.dataset.aiAction === action?.id));
    }
    const text = part("ai-text");
    text.value = action ? drafts.get(draftKey()) ?? prompt(action) : "";
    text.readOnly = !action;
    part("ai-reset").hidden = !drafts.has(draftKey());
    choose(part("ai-model"), models.get(choiceKey()) ?? actionModel(action));
    part("ai-model").disabled = !action || !agent()?.models.length;
    syncEfforts(efforts.get(choiceKey()) ?? actionEffort(action));
    part("ai-copied").textContent = "";
    syncSendButtons();
    // Cursor on the trailing empty line, nothing selected, the start of the prompt on screen: what is
    // typed is appended, replacing nothing.
    text.focus();
    text.setSelectionRange(text.value.length, text.value.length);
    text.scrollTop = 0;
  }

  // Model and level kept per MR, action and agent: each agent has its own.
  const draftKey = () => `${dialog.dataset.iid} ${dialog.dataset.action}`;
  const choiceKey = () => `${draftKey()} ${agent()?.id}`;

  // The catalog's model and level are Claude Code's, and win for it; otherwise those last picked for the agent.
  const actionModel = action => (agent()?.id === "claude" && action?.model) || agentChoice(agent()?.id).model || "";
  const actionEffort = action => (agent()?.id === "claude" && action?.effort) || agentChoice(agent()?.id).effort || "";

  function keepDraft() {
    const action = actionsFor(current.toFix).find(candidate => candidate.id === dialog.dataset.action);
    const text = part("ai-text").value;
    if (!action || text === prompt(action)) drafts.delete(draftKey());
    else drafts.set(draftKey(), text);
    part("ai-reset").hidden = !drafts.has(draftKey());
    part("ai-copied").textContent = "";
    syncSendButtons();
  }

  // Nothing to copy or launch while the prompt is empty: the free action's one, when opened.
  function syncSendButtons() {
    const empty = !dialog.dataset.action || !promptToSend();
    part("ai-copy").disabled = empty;
    // Greyed out while a launch runs, until its agent starts: a second click would open a second tab.
    part("ai-launch").disabled = empty || launching || !launchTarget();
  }

  // The model and level last picked for an agent, remembered by the browser: {model, effort}.
  function agentChoice(agentId) {
    try {
      return JSON.parse(localStorage.getItem(AGENT_CHOICES_KEY))?.[agentId] ?? {};
    } catch (ignored) {
      return {};
    }
  }

  function rememberAgentChoice(field, value) {
    try {
      const choices = JSON.parse(localStorage.getItem(AGENT_CHOICES_KEY)) ?? {};
      choices[agent()?.id] = { ...choices[agent()?.id], [field]: value };
      localStorage.setItem(AGENT_CHOICES_KEY, JSON.stringify(choices));
    } catch (ignored) { /* storage unavailable: the choice lasts until the page reloads */ }
  }

  // Model chosen for the action, kept like its prompt; the catalog's one need not be. Also remembered for the agent.
  function keepModel() {
    const action = actionsFor(current.toFix).find(candidate => candidate.id === dialog.dataset.action);
    const model = part("ai-model").value;
    rememberAgentChoice("model", model);
    if (!action || model === actionModel(action)) models.delete(choiceKey());
    else models.set(choiceKey(), model);
  }

  // Effort level chosen for the action, kept like its model.
  function keepEffort() {
    const action = actionsFor(current.toFix).find(candidate => candidate.id === dialog.dataset.action);
    const effort = part("ai-effort").value;
    rememberAgentChoice("effort", effort);
    if (!action || effort === actionEffort(action)) efforts.delete(choiceKey());
    else efforts.set(choiceKey(), effort);
  }

  function resetDraft() {
    drafts.delete(draftKey());
    select(actionsFor(current.toFix).find(action => action.id === dialog.dataset.action));
  }

  // What is sent, copied or launched: without the empty line left for appending, nor the
  // trailing whitespace, which would only cost tokens.
  const promptToSend = () => part("ai-text").value.trimEnd();

  async function copy() {
    const text = promptToSend();
    try {
      await navigator.clipboard.writeText(text);
    } catch (ignored) {
      // Fallback copy, which only copies the selection: the cursor then returns where it was.
      const box = part("ai-text");
      const { selectionStart, selectionEnd } = box;
      box.setSelectionRange(0, text.length);
      document.execCommand("copy");
      box.setSelectionRange(selectionStart, selectionEnd);
    }
    part("ai-copied").textContent = t("dialog.copied");
  }

  // The prompt file disappears once the agent starts (see launches.py): the only proof it runs, since the
  // tab may wait for its shell more than ten seconds (Orca on Windows, through WSL).
  const PROMPT_READ_TIMEOUT_S = 90;
  const PROMPT_READ_POLL_MS = 1000;

  // {shell, agent} once the agent starts, or the last known state once the delay has elapsed.
  async function sessionProgress(launch) {
    const deadline = Date.now() + PROMPT_READ_TIMEOUT_S * 1000;
    let progress = { shell: false, agent: false };
    while (Date.now() < deadline && !progress.agent) {
      await new Promise(resolve => setTimeout(resolve, PROMPT_READ_POLL_MS));
      progress = await request(`launch/status?launch=${encodeURIComponent(launch)}`);
    }
    return progress;
  }

  // Launch step (ordered, launched, unreachable, lostContact, aborted), with what the voice says
  // after its line: the action's name on order, the tab title afterwards. The page that has sounds
  // (index.html) plays it; the others ignore the event.
  function announce(
    step,
    subject = null
  ) {
    document.dispatchEvent(new CustomEvent("mr-dashboard:launch", { detail: { step, subject } }));
  }

  // The server opens a tab of the launch target on the main worktree, which starts Claude Code with the
  // displayed prompt.
  const launchKey = () => `${draftKey()} ${agent()?.id} ${launchTarget()?.id}`;

  async function launchSession() {
    const status = part("ai-copied");
    const recent = launched.get(launchKey());
    const ago = recent ? Math.round((Date.now() - recent.at) / 1000) : Infinity;
    if (ago < RELAUNCH_CONFIRM_S && !(recent.armed && Date.now() - recent.armed < RELAUNCH_ARMED_S * 1000)) {
      recent.armed = Date.now();
      part("ai-launch-label").textContent = t("dialog.launch.again");
      status.textContent = t("dialog.launch.recent", { seconds: ago });
      setTimeout(applyTexts, RELAUNCH_ARMED_S * 1000);
      return;
    }
    launched.delete(launchKey());
    applyTexts();
    launching = true;
    part("ai-launch").disabled = true;
    // The messages keep naming the target launched in, even if the menu changes meanwhile.
    const target = { target: launchTarget().name, agent: agent()?.name ?? "Claude Code" };
    const key = launchKey();
    status.textContent = t("dialog.launch.opening");
    const action = (catalog?.actions ?? []).find(candidate => candidate.id === dialog.dataset.action);
    announce(
      "ordered",
      action?.voice
    );
    try {
      const body = await request(
        "launch",
        {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-MR-Dashboard": "1" },
          body: JSON.stringify({
            iid: Number(dialog.dataset.iid),
            action: dialog.dataset.action,
            prompt: promptToSend(),
            model: part("ai-model").value || null,
            effort: part("ai-effort").value || null,
            target: launchTarget().id,
            agent: agent()?.id ?? "claude",
          }),
        }
      );
      status.textContent = t(body.confirmed ? "dialog.launch.opened" : "dialog.launch.unconfirmed", { ...body, ...target });
      const progress = await sessionProgress(body.launch);
      const outcome = progress.agent ? "launched" : progress.shell ? "aborted" : "lostContact";
      const message = { launched: "dialog.launch.read", aborted: "dialog.launch.unread", lostContact: "dialog.launch.noShell" }[outcome];
      status.textContent = t(message, { seconds: PROMPT_READ_TIMEOUT_S, ...target });
      if (outcome === "launched") launched.set(key, { at: Date.now(), armed: 0 });
      announce(
        outcome,
        body.title
      );
    } catch (error) {
      status.textContent = t("dialog.launch.failed", { message: error.message });
      announce("unreachable");
    } finally {
      launching = false;
      syncSendButtons();
    }
  }

  // contexts: { iid: { toFix, fixContext } }, for all open MRs.
  function saveFixContexts(contexts) {
    try {
      localStorage.setItem(FIX_CONTEXTS_KEY, JSON.stringify({ at: Date.now(), contexts }));
    } catch (ignored) { /* storage unavailable: the diff will not offer the fix */ }
  }

  function readFixContext(iid) {
    try {
      const saved = JSON.parse(localStorage.getItem(FIX_CONTEXTS_KEY));
      if (saved && Date.now() - saved.at < FIX_CONTEXT_MAX_AGE_MS) return saved.contexts[iid] ?? { toFix: false };
    } catch (ignored) { /* storage unavailable or unreadable */ }
    return { toFix: false };
  }

  return { FIX_CONTEXTS_KEY, init, setLang, t, loadCatalog, offered, buttonTitle, open, saveFixContexts, readFixContext };
})();
