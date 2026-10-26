"""The scenario's git repository, built from its history: a bare repository that plays GitLab's, and a clone of it
for MisteR Dashboard's --repo-dir.

Every commit is dated relative to the moment the demo starts, so that the dashboard always shows pushes of the
day, a review of yesterday and merges of last week. The fake GitLab reads its commits back from the bare
repository: the shas, counts and dates it serves are those of real commits.
"""
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MAIN = "main"
SEPARATOR = "\x1f"
COMMIT_FORMAT = SEPARATOR.join(("%H", "%h", "%P", "%an", "%ae", "%aI", "%cI", "%s"))
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


@dataclass
class PushRecord:
    at: float
    head: str
    # Main as it was at the push (GitLab's start_commit_sha), and the fork point of the branch (base_commit_sha).
    start: str
    base: str
    commits: list


@dataclass
class BranchRecord:
    name: str
    target: str
    pushes: list = field(default_factory=list)
    merge_commit: str = None
    squash_commit: str = None


class GitError(Exception):
    pass


def git(directory, *args, env=None, check=True):
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **(env or {})},
        check=False
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result


def build(
        root,
        history,
        people,
        email_domain,
        started_at
):
    """Builds the repository under root (origin.git, clone) and returns a Repository on it."""
    work = root / "work"
    work.mkdir(parents=True)
    git(work, "init", "--quiet", "--initial-branch", MAIN)
    builder = _Builder(
        work,
        people,
        email_domain,
        started_at
    )
    branches = {iid: BranchRecord(branch.name, branch.target) for iid, branch in history.BRANCHES.items()}
    for _, _, action in sorted(_events(history), key=lambda event: (-event[0], event[1])):
        action(builder, branches)
    later = {iid: builder.later(branches[iid], commits) for iid, commits in history.LATER.items()}
    origin = root / "origin.git"
    # A mirror, so that the later commits, kept under refs/demo/later, come along.
    git(root, "clone", "--quiet", "--mirror", str(work), str(origin))
    # The clone checks out main, whichever branch the building left the work repository on.
    git(origin, "symbolic-ref", "HEAD", f"refs/heads/{MAIN}")
    for iid, branch in history.BRANCHES.items():
        record = branches[iid]
        git(origin, "update-ref", f"refs/merge-requests/{iid}/head", record.pushes[-1].head)
        # GitLab deletes the source branch of a merged merge request.
        if branch.merged_at is not None:
            git(origin, "update-ref", "-d", f"refs/heads/{branch.name}")
    clone = root / "clone"
    git(root, "clone", "--quiet", str(origin), str(clone))
    shutil.rmtree(work)
    return Repository(
        origin,
        clone,
        branches,
        later,
        builder
    )


def _events(history):
    """(hours before start, order among simultaneous events, action): main commits, release branches cut from
    main, merge request branch creations, the commits of each push and its publication, merges."""
    events = [(commit.before, 0, _main_commit(commit)) for commit in history.MAIN]
    for name, at in history.RELEASES.items():
        events.append((at, 0.5, lambda builder, branches, name=name: git(builder.work, "branch", name, MAIN)))
    for iid, branch in history.BRANCHES.items():
        events.append((branch.created_at, 1, _create(iid, branch, history.BRANCHES)))
        for push in branch.pushes:
            for commit in push.commits:
                events.append((push.at + commit.before, 2, _branch_commit(iid, branch, commit)))
            events.append((push.at, 3, _publish(iid, push)))
        if branch.merged_at is not None:
            events.append((branch.merged_at, 4, _merge(iid, branch)))
    return events


def _main_commit(commit):
    return lambda builder, branches: builder.commit(MAIN, commit, commit.before)


def _create(iid, branch, all_branches):
    start = all_branches[branch.parent].name if branch.parent else branch.target
    return lambda builder, branches: git(builder.work, "branch", branch.name, start)


def _branch_commit(iid, branch, commit):
    def action(builder, branches):
        push = next(push for push in branch.pushes if commit in push.commits)
        builder.commit(branch.name, commit, push.at + commit.before)
    return action


def _publish(iid, push):
    def action(builder, branches):
        record = branches[iid]
        head = builder.rev(record.name)
        start = builder.rev(record.target)
        base = git(builder.work, "merge-base", head, start).stdout.strip()
        previous = record.pushes[-1].head if record.pushes else base
        commits = git(builder.work, "rev-list", "--reverse", f"{previous}..{head}").stdout.split()
        record.pushes.append(PushRecord(push.at, head, start, base, commits))
    return action


def _merge(iid, branch):
    def action(builder, branches):
        builder.merge(branches[iid], iid, branch.merged_by, branch.merged_at, branch.squash)
    return action


class _Builder:

    def __init__(
            self,
            work,
            people,
            email_domain,
            started_at
    ):
        self.work = work
        self._people = people
        self._domain = email_domain
        self._started_at = started_at
        self._current = MAIN

    def rev(self, ref):
        return git(self.work, "rev-parse", ref).stdout.strip()

    def commit(self, branch, commit, hours_before):
        self._checkout(branch)
        for path, content in commit.files.items():
            target = self.work / path
            if content is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        for old, new in commit.moves.items():
            (self.work / new).parent.mkdir(parents=True, exist_ok=True)
            git(self.work, "mv", old, new)
        for path, old, new in commit.edits:
            target = self.work / path
            text = target.read_text(encoding="utf-8")
            if text.count(old) != 1:
                raise GitError(f"{commit.title}: the text to replace in {path} is found {text.count(old)} times")
            target.write_text(text.replace(old, new), encoding="utf-8")
        git(self.work, "add", "--all")
        git(self.work, "commit", "--quiet", "--message", commit.title, env=self._identity(commit.author, hours_before))

    def later(self, record, commits):
        """Commits made on a branch now but published later: kept under refs/demo/later, the branch left as is."""
        self._checkout(record.name)
        published = self.rev(record.name)
        for commit in commits:
            self.commit(record.name, commit, 0)
        head = self.rev(record.name)
        git(self.work, "update-ref", f"refs/demo/later/{record.name}", head)
        git(self.work, "reset", "--quiet", "--hard", published)
        return head

    def identity(self, username, hours_before):
        return self._identity(username, hours_before)

    def merge(self, record, iid, merger, hours_before, squash=False):
        self._checkout(record.target)
        identity = self._identity(merger, hours_before)
        if squash:
            title = git(self.work, "log", "-1", "--format=%s", record.pushes[0].commits[0]).stdout.strip()
            git(self.work, "merge", "--quiet", "--squash", record.name, env=identity)
            git(self.work, "commit", "--quiet", "--message", f"{title}\n\nSee merge request !{iid}", env=identity)
            record.squash_commit = self.rev(record.target)
            return
        message = f"Merge branch '{record.name}' into '{record.target}'\n\nSee merge request !{iid}"
        git(self.work, "merge", "--quiet", "--no-ff", "--message", message, record.name, env=identity)
        record.merge_commit = self.rev(record.target)

    def _checkout(self, branch):
        if branch != self._current:
            git(self.work, "checkout", "--quiet", branch)
            self._current = branch

    def _identity(self, username, hours_before):
        name = self._people[username]
        email = f"{username}@{self._domain}"
        date = f"{int(self._started_at - hours_before * 3600)} +0000"
        return {
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": date,
        }


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    short: str
    parents: tuple
    author: str
    email: str
    authored: str
    committed: str
    title: str


class Repository:
    """What the fake GitLab asks the bare repository: commits, ranges, diff sizes, conflicts, file contents."""

    def __init__(
            self,
            origin,
            clone,
            branches,
            later=None,
            builder=None
    ):
        self.origin = origin
        self.clone = clone
        self.branches = branches
        self.later = later or {}
        self._builder = builder
        self._commits = {}

    def set_reachable(self, reachable):
        """Moves the bare repository aside, or back: the clone's fetches fail meanwhile, as during a GitLab
        outage, while the fake GitLab keeps reading it at its other path."""
        down = self.origin.with_name("origin.git-down")
        if reachable and self.origin == down:
            self.origin = down.rename(down.with_name("origin.git"))
        elif not reachable and self.origin != down:
            self.origin = self.origin.rename(down)

    def publish_later(self, iid, hours_before):
        """Pushes the later commits of a merge request: its branch and its merge request ref move to them."""
        record = self.branches[iid]
        head = self.later.pop(iid)
        previous = record.pushes[-1].head
        git(self.origin, "update-ref", f"refs/heads/{record.name}", head)
        git(self.origin, "update-ref", f"refs/merge-requests/{iid}/head", head)
        start = self.tip(record.target)
        push = PushRecord(hours_before, head, start, self.merge_base(head, start),
                          git(self.origin, "rev-list", "--reverse", f"{previous}..{head}").stdout.split())
        record.pushes.append(push)
        return push

    def merge_now(self, iid, username, hours_before):
        """Merges a merge request into its target with a merge commit, as GitLab does on the server: no checkout."""
        record = self.branches[iid]
        target = self.tip(record.target)
        head = record.pushes[-1].head
        tree = git(self.origin, "merge-tree", "--write-tree", target, head).stdout.split()[0]
        message = f"Merge branch '{record.name}' into '{record.target}'\n\nSee merge request !{iid}"
        commit = git(self.origin, "commit-tree", tree, "-p", target, "-p", head, "-m", message,
                     env=self._builder.identity(username, hours_before)).stdout.strip()
        git(self.origin, "update-ref", f"refs/heads/{record.target}", commit)
        git(self.origin, "update-ref", "-d", f"refs/heads/{record.name}")
        record.merge_commit = commit
        return commit

    def commit(self, sha):
        if sha not in self._commits:
            self._commits[sha] = self._parse(git(self.origin, "show", "--no-patch", f"--format={COMMIT_FORMAT}", sha).stdout)[0]
        return self._commits[sha]

    def log(self, revisions, first_parent=False):
        """Commits of a range, newest first, as GitLab lists them."""
        options = ["--first-parent"] if first_parent else []
        return self._parse(git(self.origin, "log", *options, f"--format={COMMIT_FORMAT}", *revisions).stdout)

    def merge_base(self, first, second):
        return git(self.origin, "merge-base", first, second).stdout.strip()

    def count(self, revisions):
        return int(git(self.origin, "rev-list", "--count", revisions).stdout)

    def tip(self, branch):
        return git(self.origin, "rev-parse", f"refs/heads/{branch}").stdout.strip()

    def diff_stats(self, base, head):
        """(additions, deletions, files) of the merge request's changes, renames found."""
        lines = git(self.origin, "diff", "--numstat", "--find-renames", base, head).stdout.splitlines()
        additions = deletions = 0
        for line in lines:
            added, deleted, _ = line.split("\t", 2)
            additions += int(added) if added.isdigit() else 0
            deletions += int(deleted) if deleted.isdigit() else 0
        return additions, deletions, len(lines)

    def conflicts(self, head, target):
        """True when merging head into target stops on a conflict."""
        return git(self.origin, "merge-tree", "--write-tree", target, head, check=False).returncode == 1

    def renamed_from(self, base, head, path):
        """The path a file had at base, when the range renamed it; else the same path."""
        for line in git(self.origin, "diff", "--name-status", "--find-renames", base, head).stdout.splitlines():
            status, *paths = line.split("\t")
            if status.startswith("R") and paths[1] == path:
                return paths[0]
        return path

    def same_line(self, base, old_path, head, new_path, new_line):
        """The line number at base of a line the range left unchanged, None for a line it added."""
        diff = git(self.origin, "diff", "--unified=0", "--find-renames", base, head, "--", old_path, new_path).stdout
        if "\nnew file mode" in diff or diff.startswith("new file mode"):
            return None
        shift = 0
        for old_start, old_count, new_start, new_count in HUNK.findall(diff):
            old_count = 1 if old_count == "" else int(old_count)
            new_count = 1 if new_count == "" else int(new_count)
            new_start = int(new_start)
            if new_line < new_start or (new_count == 0 and new_line == new_start):
                break
            if new_line < new_start + new_count:
                return None
            shift += new_count - old_count
        return new_line - shift

    def has_line(self, sha, path, text):
        """True when a file, at a commit, has a line that contains text."""
        result = git(self.origin, "show", f"{sha}:{path}", check=False)
        return result.returncode == 0 and any(text in line for line in result.stdout.splitlines())

    def line_of(self, sha, path, text):
        """Number of the first line of a file that contains text, at a commit."""
        content = git(self.origin, "show", f"{sha}:{path}").stdout
        for number, line in enumerate(content.splitlines(), 1):
            if text in line:
                return number
        raise GitError(f"{text!r} is not in {path} at {sha[:8]}")

    @staticmethod
    def _parse(output):
        commits = []
        for line in output.splitlines():
            sha, short, parents, author, email, authored, committed, title = line.split(SEPARATOR, 7)
            commits.append(CommitInfo(sha, short, tuple(parents.split()), author, email, authored, committed, title))
        return commits
