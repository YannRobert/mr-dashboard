// One tab per page and per MR: the diff of !226, its comments. A link to an already open page
// brings it to front and reloads it, never to show a stale version of the MR. Shared by index.html,
// diff.html and comments.html.
window.MrTabs = (() => {
  const name = (page, iid) => `mr-dashboard-${page}-${iid}`;

  // Named tab: the browser returns the one already bearing this name, or opens an empty one to fill. An
  // already open tab is reloaded without adding a history entry.
  function open(url, page, iid) {
    const tab = window.open("", name(page, iid));
    if (!tab) return;
    try {
      if (tab.location.href === "about:blank") tab.location.href = url;
      else tab.location.replace(url);
    } catch (ignored) {
      tab.location.href = url;
    }
    tab.focus();
  }

  // Names the current tab, so links from other pages can find it.
  const claim = (page, iid) => { window.name = name(page, iid); };

  // Plain click on an a[data-tab] link: the page's tab, if open; middle click and
  // Ctrl+click keep their usual behavior.
  document.addEventListener("click", event => {
    const link = event.target.closest("a[data-tab]");
    if (!link || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    open(link.href, link.dataset.tab, link.dataset.iid);
  });

  // [data-close-tab] button: closes the tab, without confirmation. The browser only lets a page close
  // a tab that a link or script opened; otherwise nothing happens, and the button says so
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
