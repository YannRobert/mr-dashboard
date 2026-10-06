// Commentaires GitLab tels que GitLab les rend : son HTML, déjà nettoyé par GitLab, y gagne en plus des
// liens absolus vers GitLab et perd tout ce qui pourrait s'exécuter dans la page.
// Partagé par diff.html (diff notes) et comments.html (commentaires de la MR).
window.GitlabNotes = (() => {
  const DROPPED = "script, style, iframe, frame, object, embed, form, button, textarea, select, link, meta, base";
  const URL_ATTRIBUTES = ["href", "src"];

  // GitLab, par la requête GraphQL relayée par le serveur ; en GET, GitLab refuse les mutations.
  async function graphql(query) {
    const response = await fetch(`graphql?query=${encodeURIComponent(query)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    if (result.errors?.length) throw new Error(result.errors.map(e => e.message).join(" ; "));
    return result.data;
  }

  // Toutes les pages d'une connexion GraphQL ; page(after) renvoie la connexion, nodes et pageInfo.
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
    // Seules les cases des listes de tâches restent, en lecture seule.
    for (const input of doc.querySelectorAll("input")) {
      if (input.type === "checkbox") input.setAttribute("disabled", "");
      else input.remove();
    }
    for (const element of doc.body.querySelectorAll("*")) {
      // Images chargées à l'affichage par le script de GitLab : leur adresse attend dans data-src.
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

  // Identifiant numérique d'une note, d'après son identifiant GraphQL « gid://gitlab/DiffNote/123 ».
  const noteId = gid => Number(String(gid).split("/").pop());

  return { graphql, allNodes, render, noteId };
})();
