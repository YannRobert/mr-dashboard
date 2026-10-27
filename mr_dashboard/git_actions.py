"""Git actions on the local clone of the tracked project: fetch and diff of a MR, open or merged, and what
the clone knows about an open MR when GitLab does not respond.

While automatic fetch is enabled, it also runs by itself at a regular interval: remote branches stay up
to date even with no page open, and stay in place during a GitLab outage, even when it serves a
maintenance page instead of the repository — one can then review and commit on origin/<branch>, and push
once it is back.

Fetch and diff run in the tracked repository (--repo-dir), main or secondary worktree, without ever
checking anything out there: it holds the work in progress.
"""
import os
import re
import subprocess
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

FETCH_TIMEOUT_S = 60
# A push runs the clone's hooks, which may build or test.
PUSH_TIMEOUT_S = 300
DIFF_TIMEOUT_S = 30
MAX_DIFF_BYTES = 5_000_000
# Context of a whole-file diff: more lines than any file has.
WHOLE_FILE_CONTEXT = 100_000_000
# Never prompt for credentials: with no terminal to answer, git would wait until the timeout.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
# MR states already reported, remembered so as not to fetch again when a page replays an old one.
SEEN_SIGNATURES = 100
# Commands that query the remote repository, hence GitLab.
REMOTE_COMMANDS = ("fetch", "ls-remote", "push")


class GitError(Exception):
    pass


class GitActions:

    def __init__(
            self,
            repo_dir,
            fetch_interval_s,
            on_remote_call
    ):
        self._repo_dir = repo_dir
        # Path given by git, once and for all: in a secondary worktree, .git is a file and FETCH_HEAD
        # is in the common directory of the clone.
        self._fetch_head = Path(self._git_output(["rev-parse", "--path-format=absolute", "--git-path", "FETCH_HEAD"]))
        self._fetch_interval_s = fetch_interval_s
        # Called on each command that queries the remote repository, with whether it failed.
        self._on_remote_call = on_remote_call
        self._fetch_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._fetches = 0
        self._running = False
        self._last = None
        self._last_success_at = None
        # MR states already reported by the pages, across all tabs and browsers.
        self._seen_signatures = deque(maxlen=SEEN_SIGNATURES)
        self._auto = True
        self._wake = threading.Event()
        # Due time of the next automatic fetch, in monotonic time: each fetch, wherever it comes from,
        # pushes it back by one interval.
        self._next_due = 0.0
        self._next_at = None

    def start_periodic_fetch(self):
        if self._fetch_interval_s <= 0:
            return
        threading.Thread(target=self._fetch_forever, name="git-fetch", daemon=True).start()

    def _fetch_forever(self):
        while True:
            with self._state_lock:
                auto = self._auto
                delay = self._next_due - time.monotonic()
            if auto and delay <= 0:
                self.fetch()
                continue
            self._wake.wait(delay if auto else None)
            self._wake.clear()

    def set_auto(self, enabled):
        """Once re-enabled, the automatic fetch starts at once, without waiting for the end of the interval."""
        with self._state_lock:
            self._auto = enabled
            if enabled:
                self._next_due = 0.0
        self._wake.set()

    def fetch(self):
        """Starts a fetch, or waits for the one in progress and returns its result: two close requests
        make only one."""
        with self._state_lock:
            seen = self._fetches
        with self._fetch_lock:
            with self._state_lock:
                if self._fetches != seen:
                    return self._last
                self._running = True
            result = self._run_fetch()
            with self._state_lock:
                self._fetches += 1
                self._running = False
                self._last = result
                self._next_due = time.monotonic() + self._fetch_interval_s
                self._next_at = (datetime.now(timezone.utc) + timedelta(seconds=self._fetch_interval_s)).isoformat()
                if result["ok"]:
                    self._last_success_at = result["at"]
            return result

    def fetch_if_changed(self, signature):
        """Fetches if the MR state seen by the page has never been reported. A state already seen has already
        been fetched: a reloaded page, which replays its saved state before updating, or another browser
        with an older saved state, do not trigger fetches by alternating between two states."""
        with self._state_lock:
            if signature in self._seen_signatures:
                return self._last
            self._seen_signatures.append(signature)
        return self.fetch()

    def _run_fetch(self):
        at = datetime.now(timezone.utc).isoformat()
        try:
            # A maintenance page served with a 200 instead of the repository looks like a repository with no
            # branch: git reports nothing, and --prune would then delete every origin/* branch. No
            # advertised branch, no fetch.
            advertised = self._git(["ls-remote", "--heads", "origin"], timeout=FETCH_TIMEOUT_S)
            if advertised.returncode != 0:
                return {"at": at, "ok": False, "message": last_line(advertised.stderr) or f"code {advertised.returncode}"}
            if not advertised.stdout.strip():
                return {"at": at, "ok": False, "message": "origin advertises no branch (maintenance?): "
                                                          "fetch cancelled to keep the origin/* branches"}
            completed = self._git(["fetch", "--prune", "origin"], timeout=FETCH_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {"at": at, "ok": False, "message": f"no response from git fetch within {FETCH_TIMEOUT_S} s"}
        except OSError as error:
            return {"at": at, "ok": False, "message": str(error)}
        if completed.returncode != 0:
            return {"at": at, "ok": False, "message": last_line(completed.stderr) or f"code {completed.returncode}"}
        return {"at": at, "ok": True, "message": None}

    def status(self):
        with self._state_lock:
            periodic = self._auto and self._fetch_interval_s > 0 and not self._running
            return {
                "auto": self._auto,
                "nextAt": self._next_at if periodic else None,
                "running": self._running,
                "last": self._last,
                "lastSuccess": self._last_success_at,
            }

    def open_revisions(
            self,
            branch,
            target
    ):
        """Bounds of an open MR: its target on origin and its branch, with the commits not pushed yet when
        the clone has some. The third item is the branch as on origin, or None when it has no local
        commit to show."""
        self._check_branch_names(
            branch,
            target
        )
        self._fetch_missing(
            branch,
            target
        )
        published = f"refs/remotes/origin/{branch}"
        head = self._unpushed_head(branch)
        return f"refs/remotes/origin/{target}", head or published, published if head else None

    def merge_target(
            self,
            branch,
            target,
            head
    ):
        """Merges origin/<target> into the MR's branch and pushes it, to bring it up to date without rewriting
        its history; head is the branch's commit the user saw, the merge refused if it has moved since. Done in
        a temporary worktree, the tracked repository's checkout untouched; with conflicts, nothing is pushed.
        Returns the new head."""
        self._check_branch_names(
            branch,
            target
        )
        self._fetch(
            branch,
            target
        )
        published = f"refs/remotes/origin/{branch}"
        if self._git_output(["rev-parse", published]) != head:
            raise GitError(f"{branch} has moved on origin since it was displayed: reload")
        if self._git(["merge-base", "--is-ancestor", f"refs/remotes/origin/{target}", published]).returncode == 0:
            raise GitError(f"{branch} is already up to date with {target}")
        with tempfile.TemporaryDirectory(prefix="mr-dashboard-merge-") as parent:
            worktree = str(Path(parent) / "worktree")
            self._git_output(["worktree", "add", "--detach", worktree, published])
            try:
                merged = self._git(
                    ["merge", "--no-ff", "--no-edit", "-m", f"Merge branch '{target}' into '{branch}'",
                     f"refs/remotes/origin/{target}"],
                    timeout=FETCH_TIMEOUT_S,
                    cwd=worktree
                )
                if merged.returncode != 0:
                    conflicts = self._git(["diff", "--name-only", "--diff-filter=U"], cwd=worktree).stdout.split()
                    raise GitError(f"conflicts to resolve locally: {', '.join(conflicts)}" if conflicts
                                   else last_line(merged.stderr or merged.stdout) or "git merge failed")
                new_head = self._git_output(["rev-parse", "HEAD"], cwd=worktree)
                try:
                    # Not forced: GitLab refuses it if the branch has moved meanwhile.
                    pushed = self._git(
                        ["push", "origin", f"HEAD:refs/heads/{branch}"],
                        timeout=PUSH_TIMEOUT_S,
                        cwd=worktree
                    )
                except subprocess.TimeoutExpired as error:
                    raise GitError(f"no response from git push within {PUSH_TIMEOUT_S} s") from error
                if pushed.returncode != 0:
                    raise GitError(last_line(pushed.stderr) or "git push failed")
            finally:
                self._git(["worktree", "remove", "--force", worktree])
        self._fetch(branch)
        return new_head

    def _unpushed_head(self, branch):
        """The local branch when it is strictly ahead of origin/<branch>, otherwise None: a local branch that
        is behind or has diverged (rebase, force-push) would show a wrong state, so origin prevails."""
        local, published = f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"
        for ref in (local, published):
            if self._git(["rev-parse", "--verify", "--quiet", ref]).returncode != 0:
                return None
        if self._git(["rev-parse", local]).stdout == self._git(["rev-parse", published]).stdout:
            return None
        if self._git(["merge-base", "--is-ancestor", published, local]).returncode != 0:
            return None
        return local

    def merged_revisions(
            self,
            iid,
            head,
            merge_commit,
            target
    ):
        """Bounds of a merged MR, whether or not its source branch was deleted: the target just before the
        merge and the last commit of the MR. Everything is read from history, no worktree or local branch."""
        if not iid.isdigit() or not SHA.fullmatch(head) or not SHA.fullmatch(merge_commit):
            raise GitError("invalid MR or commit")
        self._check_branch_names(target)
        # Source branch deleted and MR squashed: GitLab keeps its head under refs/merge-requests.
        if not self._has_commit(head):
            self._fetch(f"refs/merge-requests/{iid}/head")
        if not self._has_commit(merge_commit):
            self._fetch(target)
        return f"{merge_commit}^1", head, None

    def diff(
            self,
            revisions,
            first=None,
            last=None,
            paths=()
    ):
        """Without a range, the MR diff from the point where it leaves its target, as in GitLab's Changes
        tab; with one, what its commits from first to last brought together. With paths, the diff of
        those files only, each in full: its unchanged lines as context."""
        base, head, _ = revisions
        options = [f"--unified={WHOLE_FILE_CONTEXT}", "--", *paths] if paths else []
        if first is None and last is None:
            return self._diff_range(f"{base}...{head}", *options)
        shas = [commit["sha"] for commit in self.commits(revisions)]
        if first not in shas or last not in shas or shas.index(first) > shas.index(last):
            raise GitError("commit range outside the MR")
        return self._diff_range(f"{first}^1", last, *options)

    def commits(self, revisions):
        """Commits of the MR, oldest first, without those of the target it merged in."""
        base, head, published = revisions
        completed = self._git(
            [
                "log", "--first-parent", "--reverse", "--format=%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%s",
                f"{base}..{head}",
            ],
            timeout=DIFF_TIMEOUT_S
        )
        if completed.returncode != 0:
            raise GitError(last_line(completed.stderr) or "git log failed")
        unpushed = set()
        if published:
            listed = self._git(["rev-list", "--first-parent", f"{published}..{head}"], timeout=DIFF_TIMEOUT_S)
            if listed.returncode == 0:
                unpushed = set(listed.stdout.split())
        commits = []
        for line in completed.stdout.splitlines():
            sha, parents, author, email, date, title = line.split("\x1f", 5)
            commits.append({
                "sha": sha,
                "merge": len(parents.split()) > 1,
                "author": author,
                "email": email,
                "date": date,
                "title": title,
                "local": sha in unpushed,
            })
        return commits

    def branch_signals(
            self,
            branch,
            target
    ):
        """Commit count, date of the last one and lag behind the target of an open MR, from the origin/*
        branches of the last fetch, without network: enough to show them during a GitLab outage. The lag
        runs, as in the page, from the target commit that follows the last common commit."""
        self._check_branch_names(
            branch,
            target
        )
        head, base = f"refs/remotes/origin/{branch}", f"refs/remotes/origin/{target}"
        for ref, name in ((head, branch), (base, target)):
            if self._git(["rev-parse", "--verify", "--quiet", ref]).returncode != 0:
                raise GitError(f"branch missing from the local git clone: {name}")
        common = self._git_output(["merge-base", head, base])
        count = int(self._git_output(["rev-list", "--count", f"{base}..{head}"]))
        commit_date, author_date = self._git_output(["log", "-1", "--format=%cI%x1f%aI", head]).split("\x1f")
        behind = int(self._git_output(["rev-list", "--count", f"{head}..{base}"]))
        since = next_short = None
        if behind:
            successors = [
                line.split("\x1f")
                for line in self._git_output(
                    ["log", "--first-parent", "--reverse", "--format=%P%x1f%h%x1f%cI", f"{common}..{base}"]
                ).splitlines()
            ]
            successor = next((s for s in successors if s[0].split()[0] == common), successors[0] if successors else None)
            if successor:
                next_short, since = successor[1], successor[2]
        unpushed = 0
        if self._unpushed_head(branch):
            unpushed = int(self._git_output(["rev-list", "--count", "--first-parent", f"{head}..refs/heads/{branch}"]))
        return {
            "unpushed": unpushed,
            "count": count,
            "commitDate": commit_date,
            "authorDate": author_date,
            "behind": {"count": behind, "since": since, "base": self._git_output(["rev-parse", "--short", common]), "next": next_short},
            "fetchedAt": self._last_fetch_at(),
        }

    def worktree_of(self, branch):
        """The worktree that has the branch checked out, among those of the repository, or None: a MR's session then
        opens on its branch, rather than at the root of the repository."""
        try:
            self._check_branch_names(branch)
            listing = self._git_output(["worktree", "list", "--porcelain"])
        except GitError:
            return None
        path = None
        for line in listing.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):]
            elif line == f"branch refs/heads/{branch}" and path and Path(path).is_dir():
                return Path(path)
        return None

    def _last_fetch_at(self):
        """Date of the last successful fetch, even one run outside the server: that of FETCH_HEAD."""
        try:
            mtime = self._fetch_head.stat().st_mtime
        except OSError:
            return None
        return datetime.fromtimestamp(mtime, timezone.utc).isoformat()

    def _git_output(
            self,
            args,
            cwd=None
    ):
        completed = self._git(
            args,
            cwd=cwd
        )
        if completed.returncode != 0:
            raise GitError(last_line(completed.stderr) or f"git {args[0]} failed")
        return completed.stdout.strip()

    def _diff_range(self, *revisions):
        try:
            completed = subprocess.run(
                [
                    "git", "-C", str(self._repo_dir), "diff", "--no-color", "--no-ext-diff", "--find-renames",
                    *revisions,
                ],
                capture_output=True,
                env=GIT_ENV,
                timeout=DIFF_TIMEOUT_S
            )
        except subprocess.TimeoutExpired as error:
            raise GitError(f"no response from git diff within {DIFF_TIMEOUT_S} s") from error
        if completed.returncode != 0:
            raise GitError(last_line(completed.stderr.decode(errors="replace")) or "git diff failed")
        # Beyond that, the browser would struggle to display it.
        if len(completed.stdout) > MAX_DIFF_BYTES:
            raise GitError(
                f"{len(completed.stdout) // 1_000_000} MB diff, beyond the {MAX_DIFF_BYTES // 1_000_000} MB "
                "that can be displayed: read it in GitLab"
            )
        return completed.stdout.decode(errors="replace")

    def _check_branch_names(
            self,
            *names
    ):
        for name in names:
            if self._git(["check-ref-format", "--branch", name]).returncode != 0:
                raise GitError(f"invalid branch name: {name}")

    def _fetch_missing(
            self,
            branch,
            target
    ):
        """Branch pushed since the last fetch: fetch it, and only it."""
        missing = [name for name in (branch, target) if not self._has_remote_branch(name)]
        if missing:
            self._fetch(*missing)

    def _fetch(self, *refspecs):
        try:
            completed = self._git(["fetch", "origin", *refspecs], timeout=FETCH_TIMEOUT_S)
        except subprocess.TimeoutExpired as error:
            raise GitError(f"no response from git fetch within {FETCH_TIMEOUT_S} s") from error
        if completed.returncode != 0:
            raise GitError(last_line(completed.stderr) or "not found on origin")

    def _has_remote_branch(self, name):
        return self._git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}"]).returncode == 0

    def _has_commit(self, sha):
        return self._git(["cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0

    def _git(
            self,
            args,
            timeout=10,
            cwd=None
    ):
        remote = args[0] in REMOTE_COMMANDS
        try:
            completed = subprocess.run(
                ["git", "-C", str(cwd or self._repo_dir), *args],
                capture_output=True,
                text=True,
                env=GIT_ENV,
                timeout=timeout
            )
        except (subprocess.TimeoutExpired, OSError):
            if remote:
                self._on_remote_call(True)
            raise
        if remote:
            self._on_remote_call(completed.returncode != 0)
        return completed


def last_line(text):
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""
