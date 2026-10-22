# Contributing to MisteR Dashboard

Thank you for your interest! Bug reports, ideas and pull requests are all welcome.

## Improve it upstream rather than forking

If the dashboard does not quite fit your team, please propose the change here, through an issue or
a pull request, rather than maintaining a long-lived fork. Improvements shared upstream benefit every
user, and you will not have to keep merging later versions into your copy.

Before changing the code, check whether an extension point already covers your need:

- **command-line options** of `server.py` (GitLab and SonarQube hosts, CI job names, `--no-sonar`,
  `--no-pit`…);
- the per-repository **`.mr-dashboard/ai-actions.toml`** catalogue, for project-specific AI prompts.

If what you need is project-specific, a new option or extension point is usually a better
contribution than a hard-coded behavior. Open an issue to discuss it first if the change is large.

## Running locally

Python 3.11 or later, git, and a GitLab token in the `glab` configuration. Nothing to install and no
build step:

```bash
python3 mr_dashboard/server.py \
    --gitlab-host https://gitlab.example.com \
    --gitlab-project group/project \
    --pipeline-branch main \
    --repo-dir ~/src/project \
    --no-sonar \
    --no-pit
```

Then open http://localhost:8765/. HTML, JS and CSS changes are picked up by open tabs within 30 s;
Python changes require restarting the server. See the [README](../README.md) for every option.

## Style

- Match the surrounding code: naming, structure and comment style.
- **Python standard library only**, and no build step or JavaScript bundler: the dashboard must keep
  running from a plain clone.
- The UI is bilingual: every user-visible string goes into **both the `fr` and `en` dictionaries**.
- A method or function signature with more than one parameter puts one parameter per line, breaking
  after the opening parenthesis and before the closing one:

  ```python
  def record(
      self,
      category,
      error
  ):
  ```

- Comments explain why, not what. Code, comments and commit messages are in English.

## Pull requests

- Keep them short and focused: one change per pull request is easier to review and to revert.
- Describe what the change does and why, and how you checked it (screenshots welcome for UI changes;
  the 🕶 demo mode hides real names and titles).
- Keep the security model intact (see [SECURITY.md](SECURITY.md)); report vulnerabilities privately,
  not in a pull request.

By contributing, you agree that your contributions are licensed under the [MIT License](../LICENSE), and
to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
