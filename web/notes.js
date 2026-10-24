// GitLab comments as GitLab renders them: its HTML, already sanitized by GitLab, additionally gets
// absolute links to GitLab and loses anything that could run in the page.
// Shared by diff.html (diff notes) and comments.html (MR comments).
window.GitlabNotes = (() => {
  const DROPPED = "script, style, iframe, frame, object, embed, form, button, textarea, select, link, meta, base";
  const URL_ATTRIBUTES = ["href", "src"];

  // GitLab, through the GraphQL query relayed by the server; over GET, GitLab rejects mutations.
  async function graphql(query) {
    const response = await fetch(`graphql?query=${encodeURIComponent(query)}`);
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(failure.message ?? `HTTP ${response.status}`);
    }
    const result = await response.json();
    if (result.errors?.length) throw new Error(result.errors.map(e => e.message).join(" ; "));
    return result.data;
  }

  // All pages of a GraphQL connection; page(after) returns the connection, nodes and pageInfo.
  async function allNodes(page) {
    const nodes = [];
    for (let after = null, more = true; more;) {
      const connection = await page(after);
      nodes.push(...connection.nodes);
      more = connection.pageInfo.hasNextPage;
      after = connection.pageInfo.endCursor;
    }
    return nodes;
  }

  function render(html, gitlabWeb) {
    const doc = new DOMParser().parseFromString(`<body>${html ?? ""}</body>`, "text/html");
    doc.querySelectorAll(DROPPED).forEach(element => element.remove());
    // Only task list checkboxes remain, read-only.
    for (const input of doc.querySelectorAll("input")) {
      if (input.type === "checkbox") input.setAttribute("disabled", "");
      else input.remove();
    }
    for (const element of doc.body.querySelectorAll("*")) {
      // Images loaded on display by GitLab's script: their address waits in data-src.
      if (element.dataset.src) element.setAttribute("src", element.dataset.src);
      for (const attribute of [...element.attributes]) {
        if (/^on/i.test(attribute.name) || attribute.name === "style") element.removeAttribute(attribute.name);
      }
      for (const name of URL_ATTRIBUTES) {
        const value = element.getAttribute(name);
        if (value === null) continue;
        let url;
        try {
          url = new URL(value, gitlabWeb);
        } catch (ignored) {
          element.removeAttribute(name);
          continue;
        }
        if (!["https:", "http:", "mailto:"].includes(url.protocol) && !(name === "src" && url.protocol === "data:")) {
          element.removeAttribute(name);
        } else if (!value.startsWith("#")) {
          element.setAttribute(name, url.href);
        }
      }
      if (element.tagName === "A" && element.hasAttribute("href") && !element.getAttribute("href").startsWith("#")) {
        element.setAttribute("target", "_blank");
        element.setAttribute("rel", "noopener noreferrer");
      }
    }
    return doc.body.innerHTML;
  }

  // Id of a note or thread, from its GraphQL id: "gid://gitlab/DiffNote/123"
  // gives 123, "gid://gitlab/Discussion/<sha>" the thread SHA.
  const noteId = gid => Number(String(gid).split("/").pop());
  const discussionId = gid => String(gid).split("/").pop();

  const TEXTS = {
    fr: {
      reply: "Répondre",
      resolve: "Résoudre",
      reopen: "Rouvrir",
      cancel: "Annuler",
      publish: "Publier dans GitLab",
      placeholder: "Réponse, en markdown — Ctrl+Entrée pour publier, Échap pour annuler",
      publishing: "Publication…",
      failed: p => `GitLab a refusé : ${p}`,
    },
    en: {
      reply: "Reply",
      resolve: "Resolve",
      reopen: "Reopen",
      cancel: "Cancel",
      publish: "Publish to GitLab",
      placeholder: "Reply, in markdown — Ctrl+Enter to publish, Escape to cancel",
      publishing: "Publishing…",
      failed: p => `GitLab refused: ${p}`,
    },
  };
  const escapeHtml = text => String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // Write to GitLab through a server action, which forwards only what it has validated.
  async function write(action, payload) {
    const response = await fetch(`gitlab/${action}`, {
      method: "POST",
      headers: { "X-MR-Dashboard": "1", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = result.message ?? result.error ?? `HTTP ${response.status}`;
      throw new Error(typeof message === "string" ? message : JSON.stringify(message));
    }
    return result;
  }

  // Thread footer, to place in the element holding data-discussion: Reply, and Resolve or Reopen
  // for a thread that can be.
  function threadActionsHtml(discussion, lang) {
    const texts = TEXTS[lang] ?? TEXTS.en;
    const resolve = discussion.resolvable
      ? `<button type="button" data-thread-resolve="${!discussion.resolved}">${escapeHtml(discussion.resolved ? texts.reopen : texts.resolve)}</button>`
      : "";
    return `<div class="thread-actions"><span class="thread-error"></span>${resolve}`
      + `<button type="button" data-thread-reply>${escapeHtml(texts.reply)}</button></div>`;
  }

  // Reply, resolve, reopen, in the threads of root; refresh(discussion) re-renders the thread after
  // the write and returns a promise.
  function handleThreads(root, { iid, lang, refresh }) {
    const texts = TEXTS[lang] ?? TEXTS.en;
    const threadOf = element => element.closest("[data-discussion]");

    async function run(thread, controls, operation) {
      const error = thread.querySelector(".thread-error");
      controls.forEach(c => { c.disabled = true; });
      error.textContent = texts.publishing;
      try {
        await operation();
        await refresh(thread.dataset.discussion);
      } catch (failure) {
        controls.forEach(c => { c.disabled = false; });
        error.textContent = texts.failed(failure.message);
      }
    }

    function openReply(thread) {
      const actions = thread.querySelector(".thread-actions");
      actions.hidden = true;
      actions.insertAdjacentHTML("afterend", `<form class="thread-reply">`
        + `<textarea placeholder="${escapeHtml(texts.placeholder)}"></textarea>`
        + `<div class="thread-actions"><span class="thread-error"></span>`
        + `<button type="button" data-reply-cancel>${escapeHtml(texts.cancel)}</button>`
        + `<button type="submit">${escapeHtml(texts.publish)}</button></div></form>`);
      thread.querySelector(".thread-reply textarea").focus();
    }

    function closeReply(form) {
      form.previousElementSibling.hidden = false;
      form.remove();
    }

    root.addEventListener("click", event => {
      const replyButton = event.target.closest("[data-thread-reply]");
      if (replyButton) {
        openReply(threadOf(replyButton));
        return;
      }
      const cancel = event.target.closest("[data-reply-cancel]");
      if (cancel) {
        closeReply(cancel.closest(".thread-reply"));
        return;
      }
      const resolveButton = event.target.closest("[data-thread-resolve]");
      if (resolveButton) {
        const thread = threadOf(resolveButton);
        run(thread, [resolveButton], () => write("resolve", {
          iid: Number(iid),
          discussion: thread.dataset.discussion,
          resolved: resolveButton.dataset.threadResolve === "true",
        }));
      }
    });
    root.addEventListener("submit", event => {
      const form = event.target.closest(".thread-reply");
      if (!form) return;
      event.preventDefault();
      const body = form.querySelector("textarea").value;
      if (!body.trim()) return;
      const thread = threadOf(form);
      run(thread, [...form.querySelectorAll("button, textarea")], () => write("reply", {
        iid: Number(iid),
        discussion: thread.dataset.discussion,
        body,
      }));
    });
    root.addEventListener("keydown", event => {
      const form = event.target.closest?.(".thread-reply");
      if (!form) return;
      if (event.key === "Escape") closeReply(form);
      else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) form.requestSubmit();
    });
  }

  return { graphql, allNodes, render, noteId, discussionId, threadActionsHtml, handleThreads };
})();
