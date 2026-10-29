// Keyboard shortcuts of a page, listed in a panel under a keyboard icon, also opened with "?". Single
// keys without modifier: the browser binds none of them, and they are ignored while typing. Shared by
// index.html, diff.html and comments.html.
window.MrShortcuts = (() => {
  // The browser's own shortcuts use Cmd on macOS, Ctrl everywhere else.
  const mac = /mac/i.test(navigator.userAgentData?.platform ?? navigator.platform);
  const closeTabKeys = `<kbd>${mac ? "⌘ Cmd" : "Ctrl"}</kbd> <kbd>w</kbd>`;
  // Existing markup: a .shortcuts element holding the button and the .shortcuts-panel. keys maps a
  // key to its action; an action returning false leaves the key to the browser.
  function attach(
      root,
      keys
  ) {
    const button = root.querySelector("button");
    const panel = root.querySelector(".shortcuts-panel");
    const toggle = open => {
      panel.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
    };
    button.addEventListener("click", () => toggle(panel.hidden));
    document.addEventListener("click", e => {
      if (!panel.hidden && !root.contains(e.target)) toggle(false);
    });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && !panel.hidden) {
        toggle(false);
        button.focus();
        return;
      }
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.isComposing) return;
      if (e.target.closest?.("input, textarea, select, [contenteditable]")) return;
      const action = e.key === "?" ? () => toggle(panel.hidden) : keys[e.key];
      if (action && action() !== false) e.preventDefault();
    });
  }

  // Fills the panel next to the button already in the markup (shown before the scripts are loaded);
  // rows: [keys, description], keys as HTML (<kbd>…</kbd>). browser: { heading, rows }, the browser's
  // shortcuts worth recalling, listed apart since the page does not own them.
  function fill(
      root,
      {
          label,
          heading,
          rows,
          keys,
          browser
      }
  ) {
    const table = rows => `<table>` + rows.map(([key, text]) => `<tr><td>${key}</td><td>${text}</td></tr>`).join("") + `</table>`;
    const button = root.querySelector("button");
    button.setAttribute("aria-label", label);
    button.title = `${label} (?)`;
    button.insertAdjacentHTML("afterend", `<div class="shortcuts-panel" hidden><h4>${heading}</h4>${table(rows)}`
      + (browser ? `<h4>${browser.heading}</h4>${table(browser.rows)}` : "")
      + `</div>`);
    attach(root, keys);
  }

  return { closeTabKeys, attach, fill };
})();
