# MisteR Dashboard

Created and maintained by [Yann ROBERT](https://github.com/YannRobert)

A local dashboard of the open merge requests of a GitLab project, with their CI signals (pipeline,
SonarQube, mutation testing, unresolved threads, lag behind the target branch) and browser
notifications. It also offers an offline diff viewer built on the local clone, a comments page, and
an **AI** button that prepares Claude Code prompts for a merge request.

`mr_dashboard/server.py` serves the page (`web/index.html`) and relays the GitLab and SonarQube APIs, so that tokens
never reach the browser. It only listens on `127.0.0.1`.

## Prerequisites

- **Python 3.11 or later** (`tomllib`). Standard library only: nothing to install, no build step.
- **git**, and a local clone of the tracked project.
- **A GitLab token**, read from the [`glab`](https://gitlab.com/gitlab-org/cli) configuration
  (`~/.config/glab-cli/config.yml`): run `glab auth login --hostname gitlab.example.com` once.
- **`SONAR_TOKEN`** in the environment of the shell that starts the server, if the project uses
  SonarQube. Without it, the Sonar badges stay grey.
- Optional: [Orca](#orca-integration) and Claude Code, for the AI button's launch action.

## Running

```bash
python3 mr_dashboard/server.py \
    --gitlab-host https://gitlab.example.com \
    --gitlab-project group/project \
    --pipeline-branch main \
    --sonar-host https://sonarqube.example.com \
    --sonar-project group-project \
    --sonar-job sonar \
    --pit-job mutation_test \
    --pit-marker '<!-- mutation-report -->' \
    --repo-dir ~/src/project
```

A project without SonarQube analysis or without mutation testing says so:

```bash
python3 mr_dashboard/server.py \
    --gitlab-host https://gitlab.example.com \
    --gitlab-project group/project \
    --pipeline-branch main \
    --repo-dir ~/src/project \
    --no-sonar \
    --no-pit
```

Then open **http://localhost:8765/**. Under WSL, the Windows browser reaches it through `localhost`.

The server has **no default that points to a project**: a forgotten required option stops it at
startup instead of silently tracking another repository. To track several projects at once, start
one server per project, each on its own `--port`.

The server must outlive the terminal that started it if you want notifications all day. `start.sh`
does it for you: it reads the options from a profile, starts the server detached (`setsid nohup`),
checks that the page answers, and writes its log and PID to `~/.local/state/mr-dashboard-<profile>.*`.

```bash
mkdir -p ~/.config/mr-dashboard/profiles
cp profile.example.conf ~/.config/mr-dashboard/profiles/project.conf   # then edit it
./start.sh project            # or a path: ./start.sh ~/somewhere/project.conf
./stop.sh project             # without argument: stops every running profile
```

Options given after the profile are passed to `server.py` and win over the profile's. Set
`MR_DASHBOARD_PROFILES` to keep the profiles elsewhere. Under a user service (systemd, launchd…), run
`start.sh` as a forking service whose PID file is `~/.local/state/mr-dashboard-<profile>.pid`.

### Options

| Option | Required | Description |
|---|---|---|
| `--gitlab-host` | yes | GitLab server URL, such as `https://gitlab.example.com` |
| `--gitlab-project` | yes | project path, not encoded (`group/project`) |
| `--pipeline-branch` | yes | branch whose latest pipeline is shown below the MR table |
| `--repo-dir` | yes | local clone of the tracked project: git actions run there, Orca sessions open there, `.mr-dashboard/ai-actions.toml` is read there |
| `--port` | no | listening port (default `8765`) |
| `--target-branch` | no | target branch filtered when the page opens (default: all) |
| `--gitlab-token-host` | no | host name of the token in the glab configuration (default: the one of `--gitlab-host`) |
| `--glab-config` | no | glab configuration file (default `~/.config/glab-cli/config.yml`) |
| `--sonar-host` | unless `--no-sonar` | SonarQube server URL |
| `--sonar-project` | unless `--no-sonar` | SonarQube project key |
| `--sonar-job` | unless `--no-sonar` | name of the CI job that runs the Sonar analysis |
| `--no-sonar` | no | project without Sonar analysis: Sonar columns, data and notifications disappear |
| `--pit-job` | unless `--no-pit` | name of the CI job that posts the mutation testing note |
| `--pit-marker` | unless `--no-pit` | beginning of the mutation testing note posted on the MR — see [Mutation report format](#mutation-report-format) |
| `--no-pit` | no | project without mutation testing: its column, data and notifications disappear |
| `--git-fetch-interval` | no | seconds between two automatic `git fetch` of the local clone, `0` for none (default `300`) |
| `--quiet` | no | do not log each request |

## Using the dashboard

- **Notifications**: tick *Notifications* in the header and accept the browser prompt. On your own
  MRs, the notification stays on screen and comes back every 15 minutes while a problem remains. A
  new approval of a MR is notified too (except your own), as is a failure of the tracked branch's
  pipeline (closed when it turns green again).
- **Sounds**, independent of notifications: a bell when your MR is approved or when you approve
  someone else's, a chime when someone else approves, a low double thump on a new blocking problem
  of your MR, a siren when the tracked branch's pipeline fails, a cheerful arpeggio when a MR is
  merged. One sound per refresh, the most important one, all at the same perceived loudness. 🔊
  plays each of them on demand, to check they come out of the right device. After a reload, the
  browser only lets a sound play after a click or a key press in the page; with several dashboard
  tabs open, the sound comes out of the one used last.
- **Language**: English on the first visit, then whatever the FR / EN button selects, remembered by
  the browser; `?lang=fr` or `?lang=en` forces it for the page without changing that choice.
- **Search**: space-separated words must all match the MR (title, branch, author, labels, number); a
  comma separates alternatives. `!249` targets MR 249 alone, `249` searches it everywhere
  (`PROJ-2491` included): `!249,!250` shows only those two MRs.
- **Refresh**: reloading the page queries neither GitLab nor git. It redisplays the data saved in the
  browser and only queries GitLab when the 5-minute auto-refresh is due, counted from the last one,
  whichever tab triggered it. **Refresh** and **git fetch** always run. A refresh loads the signals of
  the displayed MRs first, top to bottom, then those hidden by the filters.
- **Text size**: text grows with the window width; **A− / A+** in the header adjust it from 70 to
  150 % (remembered, and applied to the diff page too). Prefer it to browser zoom, which applies to
  every dashboard tab.
- **🕶 Demo mode**, in the header of the dashboard and comments pages, for screenshots that can be
  shown outside the team: on screen only, people get fictitious names, titles and commit messages
  become lorem ipsum (Draft marker, leading emoji and ticket kept, the ticket as `DEMO-<n>`), branches
  become lorem slugs (type prefix, `main`, `master`, `develop` and the pipeline branch kept), labels
  become lorem words (`::` scope kept), MR numbers are shifted by one random offset (order kept), the
  project becomes `demo/project`, comment bodies become lorem ipsum, notifications included. Link
  addresses shown on hover become `https://example.com/demo/project`; the real one is restored for
  the click. The underlying data does not change: actions, links and filters still act on the real
  MRs. No original word is reused, and the fake values derive from a random salt kept in the browser,
  so the same person keeps the same fake name across screenshots. The diff is not anonymized.
- **Pipeline bar**: the latest pipeline of `--pipeline-branch` sits in a bar anchored at the bottom of
  the window, red when it failed. A click expands it: jobs by stage, previous pipeline, build
  durations and history.
- **Open | Merged**: the merged view (`?view=merged`) replays the history of MRs merged over a period
  (7, 30 — default —, 90 days or all) to understand afterwards why some took long: total duration,
  development (first commit → last push) and stabilization (last push → merge), in calendar time.
  Loaded on demand, 50 at a time while scrolling; neither saved, auto-refreshed nor notified.
- **GitLab requests · 1 / 5 / 15 min**: what the server sent to GitLab (API and `git fetch`) over the
  last minute, 5 and 15 minutes, all tabs combined — the browser never talks to GitLab directly. A
  click shows reads, writes and fetches per window, errors (connection, 4xx, 5xx, git fetch), totals
  since startup, and Sonar separately; an error other than 4xx in the last 5 minutes shows in orange.
- **Relay cache**: the server keeps successful GitLab and Sonar reads for 30 s, so tabs or browsers
  asking the same thing within that delay send a single request. A write (comment, reply, resolve)
  clears the cache; **Refresh** bypasses it. A change made in GitLab itself can thus take 30 s to show.

### No notification shows up

Ticking the box immediately sends a test notification. If it does not appear, the browser or the OS
is blocking it, not the dashboard:

1. site permission: icon left of the URL → *Notifications* → *Allow*;
2. OS settings: notifications must be enabled for the browser, and *Do not disturb* / *Focus* off;
3. untick and tick the box again to resend the test notification.

## Mutation report format

Mutation testing tools (PIT, Stryker, mutmut…) do not publish anything to GitLab by themselves: a CI
job of your project posts the result as a note on the merge request, and the dashboard reads that
note. To be read, the note must follow this format.

- The note **starts with the marker** given by `--pit-marker`, for instance `<!-- mutation-report -->`.
  An HTML comment does not show in GitLab. The CI job must update its note rather than add one on
  every pipeline: the dashboard reads the first note that starts with the marker.
- The note contains a **Markdown table** whose header names the columns below (case does not
  matter), followed by the alignment row and **one row of values**:

  | Column | Required | Value |
  |---|---|---|
  | `Mutants` | yes | mutants generated |
  | `Killed` | yes | mutants detected by a test |
  | `Survived` | yes | mutants no test detects |
  | `No coverage` | yes | mutants on code no test runs |
  | `Errors` | yes | mutants the tool could not run |
  | `Test strength` | no | `Killed / (Killed + Survived)`, in %, or `n/a` |

- Columns are read **by name**: their order is free, and other columns are ignored. In a cell, the
  first number is read, so emoji and bold are allowed (`:x: **2**`, `94 %`).
- When no mutant was generated (no production code changed), publish the table with `0` everywhere.
- Anything else in the note (title, verdict, details) is free and ignored by the dashboard.

```markdown
<!-- mutation-report -->
### Mutation testing

| Mutants | Killed | Survived | No coverage | Errors | Test strength |
|--:|--:|--:|--:|--:|--:|
| 40 | 35 | :x: **2** | :warning: **3** | 0 | 94 % |
```

`--pit-job` names the CI job that publishes the note: while it runs, the score shown is the previous
one, marked as refreshing; if it failed after the note was written, the score is marked as stale.

### Publishing the note from GitLab CI

The job below publishes `mutation-report.md`, written beforehand by your mutation testing step in the
format above. It creates the note on the first pipeline of the merge request and updates it on the
next ones. `GITLAB_API_TOKEN` is a project access token with the `api` scope, stored as a masked CI/CD
variable: the job token (`CI_JOB_TOKEN`) cannot write notes.

```yaml
mutation_test:
  stage: test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  variables:
    MARKER: "<!-- mutation-report -->"
  script:
    - ./run-mutation-testing.sh > mutation-report.md   # your tool, writing the table above
    - |
      notes="$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes"
      body="$(printf '%s\n%s' "$MARKER" "$(cat mutation-report.md)")"
      id="$(curl -sf --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" "$notes?per_page=100" \
        | jq -r --arg m "$MARKER" 'map(select(.body | startswith($m))) | first | .id // empty')"
      if [ -n "$id" ]; then
        curl -sf --request PUT --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
          --data-urlencode "body=$body" "$notes/$id" > /dev/null
      else
        curl -sf --request POST --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
          --data-urlencode "body=$body" "$notes" > /dev/null
      fi
  allow_failure: true
```

The image needs `curl` and `jq`. Then start the dashboard with `--pit-job mutation_test --pit-marker
'<!-- mutation-report -->'`.

## AI actions

The **AI** button of an open MR offers the actions of the tracked project's catalogue. The dialog
shows the chosen action's prompt, to copy into Claude Code or to launch in an Orca tab (see
[Orca integration](#orca-integration)). The prompt can be edited in the dialog before being copied or
launched: the edited text is what goes out. It is kept per MR and per action until the page is
reloaded; **Original prompt** restores it.

- **Model** selects the model of the launched session (`claude --model`): the action's one from the
  catalogue, preselected, or Claude Code's configured default. Aliases come first (they always map to
  the latest version), then older specific versions. The list is read from the cache Claude Code
  maintains itself (`~/.claude/cache/model-catalog/`, reread every time the dialog opens), so new
  models show up without changing anything here; without that cache, only the aliases are offered.
- **Effort** selects the effort level (`claude --effort`, from *Low* to *Max*). Only the levels the
  chosen model supports are listed, the recommended one flagged; a model without effort levels greys
  the list out.
- **Close**, Escape or a click outside the dialog close it. The button has a red outline when the MR
  has something to fix: branch behind or in conflict, imperfect quality indicator, unresolved thread.

The same button sits at the top of an open MR's diff, with the same actions: ask for an explanation
while reading the diff. The fix action is offered there only if a dashboard tab refreshed its data
within the last half hour, since only the dashboard loads the CI signals and threads its prompt is
built from.

### The `ai-actions.toml` catalogue

The catalogue is `.mr-dashboard/ai-actions.toml`, committed at the root of the tracked project and
read from `--repo-dir`. It is reread every time the dialog opens: an edited prompt can be tried
without restarting the server or committing. One `[[action]]` block per action, in dialog order:

```toml
[[action]]
id = "review"                 # unique within the file
label = "Review"              # label of the choice in the dialog
tab = "Review !{iid}"         # title of the Orca tab (default: label)
when = "to-fix"               # optional: offered only when the MR has something to fix
model = "sonnet"              # optional: preselected model, an alias (fable, opus, sonnet, haiku) or a version (claude-opus-4-8)
effort = "low"                # optional: preselected effort level (low, medium, high, xhigh or max)
voice = "Reviewing now."      # optional: line spoken after "Yes sir!" when launched in Orca, sounds on
prompt = """
Review merge request !{iid} ({title}), {source_branch} into {target_branch}: {web_url}
"""
```

Prompt variables: `{iid}`, `{title}`, `{source_branch}`, `{target_branch}`, `{web_url}`, and
`{fix_context}`, the fix prompt computed by the dashboard (branch update, imperfect indicators,
unresolved threads, a verification loop until all indicators are green). That loop does not say how
to read the indicators: the project's prompt adds it after `{fix_context}` if it has a tool for it. An
unknown variable is left as is in the displayed prompt.

Without a catalogue, only the fix action is offered, with `{fix_context}` as its prompt. An invalid
catalogue offers none, and the dialog says why. With or without a catalogue, the last action,
**Free**, opens an empty prompt to write in the dialog; its id `free` is reserved.

### Orca integration

When the server runs under WSL and Orca is installed on Windows
(`orca.exe` reachable through Windows interop), the dialog offers **Open in Orca**: it opens a new Orca
tab on `--repo-dir` and starts a Claude Code session there with the prompt, model and effort chosen.
The prompt goes through a short-lived file under `~/.cache/mr-dashboard/`, deleted by the session
once started. Without Orca, the button is not offered and prompts are copied instead.

## Local clone: fetch and diff

The server works on the local clone (`--repo-dir`, main or secondary worktree) and never checks
anything out there.

- **Fetch**: `git fetch --prune origin` every `--git-fetch-interval` seconds, even with no page open,
  and as soon as the page sees a MR receive commits, appear or disappear, or the pipeline branch move.
  **Auto-fetch** in the header suspends automatic fetches for the server, hence for every tab, until
  re-ticked or until the server restarts. **git fetch** runs one now; next to it, the time of the last
  fetch, or its failure in red. The `origin/<branch>` refs thus stay current during a GitLab outage.
- **Diff**: each open MR has a button showing its diff in a new tab, from the point where it leaves
  its target (`git diff origin/<target>...origin/<branch>`, like GitLab's *Changes* tab), computed on
  the local clone, so it stays available during a GitLab outage. A merged MR, even old with its branch
  deleted, has one too, found through its commits; a head missing from the clone after a squash comes
  from `refs/merge-requests/<iid>/head`. When the local branch is strictly ahead of `origin/<branch>`,
  its unpushed commits form a last **Not pushed** group.
- **Commits and pushes**: above the files, the MR's commits: a click shows that commit alone,
  Shift+click extends to another one, **All** returns to the full diff; the range is in the URL.
  Commits are grouped by push, from the MR versions in GitLab. **Last push** shows only the commits it
  brought; **New (n)** only those arrived since the last time this diff was read in the browser. A
  range containing a merge of the target says so.
- **Display**: file list in an always-visible side panel, side-by-side or line-by-line view
  (remembered), syntax highlighting, the dashboard theme. Text size follows the dashboard's, plus 25 %
  by default, adjustable from 80 to 300 % with the page's own **A− / A+**. Beyond 5 MB of diff, the page
  links to GitLab instead.
- **Space + drag**: hold Space over the diff to grab the code and move it with the mouse, so a long
  line can be read without reaching for the scrollbar. Space released without dragging scrolls a page,
  as usual.
- **Large diffs**: beyond 2000 changed lines, each file is highlighted only when it approaches the
  screen; any file of more than 1000 changed lines opens collapsed behind a button.
- **Review progress**, in the header and as a bar below it: share of changed lines seen on screen
  once scrolling settles, or in files ticked *Viewed*. Remembered per last commit and commit range: a
  push resets it.
- **💬 Diff notes** shows the MR's GitLab diff notes under the commented lines, resolved ones
  collapsed; notes on code that has changed since go to a section at the top. **‹ ›** move from one to
  the next. Off by default.
- **🗨 Comments** opens `comments.html`: the MR's comments not attached to a line (CI reports,
  reviews…), with their replies, rendered like in GitLab from the HTML GitLab provides, stripped of
  anything executable. The last 30 MRs viewed are kept in the browser, so they show immediately and
  survive a GitLab outage (orange banner).
- **One tab per page and per MR**: a link to a diff or comments page already open brings back its tab
  and reloads it. Middle-click and Ctrl+click still open a new tab.
- **Commenting**: on the full diff, with a local clone up to date with the last push, a click on a line
  number opens an editor below it, Shift+click extends it to a range; **Publish to GitLab** (Ctrl+Enter)
  creates the discussion. Under each thread, **Reply**, and **Resolve** or **Reopen**.
- **GitLab unreachable**: a MR whose refresh fails keeps its last good signals, flagged as stale.
  Commit count, last commit date and lag behind the target then come from the local clone, in grey
  italics.
- A manual `git fetch` or `git pull` run during an automatic fetch may answer "cannot lock ref": run it
  again.

## Security model

- The server listens on `127.0.0.1` only.
- The GitLab and SonarQube tokens stay in the server process; the browser never sees them, and never
  talks to GitLab or SonarQube directly.
- Every request must carry a `Host` header of `localhost` or `127.0.0.1`, which defeats DNS rebinding
  by a third-party page.
- Only GET is relayed to GitLab and SonarQube; GraphQL is relayed over GET, on which GitLab rejects
  mutations.
- Local actions (POST) require the `X-MR-Dashboard: 1` header and an `Origin` of the dashboard itself.
- The only writes to GitLab are a line discussion, a reply to a thread, and resolving or reopening a
  thread, each on a MR of the tracked project and validated before being forwarded.
- Comments and diff notes are rendered from GitLab's HTML after removing anything that could execute
  in the page.

See [SECURITY.md](.github/SECURITY.md) to report a vulnerability.

## Development

- The page (`web/`): `index.html`, `diff.html`, `comments.html` and the files they load are reread on every request: open
  tabs reload themselves within 30 s (`version.js`), except during typing. Each JS and CSS file is
  requested with a hash of its content (`?v=`), so only modified files are downloaded again. A new
  static file must be added to `STATIC_FILES` in `mr_dashboard/server.py`.
- Changes to `server.py` or the Python modules it imports require restarting the server.
- The server serves the files of the directory it was started from: to test a working copy, start the
  server from it.

See [CONTRIBUTING.md](.github/CONTRIBUTING.md).

## Third-party code

The diff view uses [diff2html](https://github.com/rtfpessoa/diff2html) (MIT), vendored in
`web/vendor/diff2html/` so that it works offline; its license is in
[`web/vendor/diff2html/LICENSE.md`](web/vendor/diff2html/LICENSE.md). To update it, replace
`diff2html-ui-slim.min.js` and `diff2html.min.css` with those of
`https://cdn.jsdelivr.net/npm/diff2html@<version>/bundles/`.

## License

Copyright © 2026 Yann ROBERT. Released under the [MIT License](LICENSE).
