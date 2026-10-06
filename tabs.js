// Un onglet par page et par MR : le diff de !226, ses commentaires. Un lien vers une page déjà ouverte
// y ramène, sans la recharger ni en ouvrir une autre. Partagé par index.html, diff.html et comments.html.
window.MrTabs = (() => {
  const name = (page, iid) => `mr-dashboard-${page}-${iid}`;

  // Onglet nommé : le navigateur rend celui qui porte déjà ce nom, ou en ouvre un vide à remplir.
  function open(url, page, iid) {
    const tab = window.open("", name(page, iid));
    if (!tab) return;
    try {
      if (tab.location.href === "about:blank") tab.location.href = url;
    } catch (ignored) {
      tab.location.href = url;
    }
    tab.focus();
  }

  // Nomme l'onglet courant, pour que les liens des autres pages le retrouvent.
  const claim = (page, iid) => { window.name = name(page, iid); };

  // Clic simple sur un lien a[data-tab] : onglet de la page, s'il est ouvert ; le clic du milieu et
  // Ctrl+clic gardent leur comportement habituel.
  document.addEventListener("click", event => {
    const link = event.target.closest("a[data-tab]");
    if (!link || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    open(link.href, link.dataset.tab, link.dataset.iid);
  });

  // Bouton [data-close-tab] : ferme l'onglet, sans confirmation. Le navigateur ne laisse une page fermer
  // que l'onglet qu'un lien ou un script a ouvert ; sinon rien ne se passe, et le bouton le dit
  // (data-close-refused).
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-close-tab]");
    if (!button) return;
    window.close();
    setTimeout(() => {
      if (window.closed) return;
      button.title = button.dataset.closeRefused;
      button.textContent = "Ctrl+W";
    }, 300);
  });

  return { open, claim };
})();
