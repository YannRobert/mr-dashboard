"""The demo project as the fake GitLab serves it: merge requests, notes, discussions and pipelines, built from the
scenario's dataset and the commits of its repository, then changed by the dashboard's writes (comments, replies,
resolved threads).

Answers have the shapes of GitLab's REST and GraphQL APIs, limited to what MisteR Dashboard reads.
"""
import hashlib
import html
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .repository import MAIN

# Pipeline ids, job ids and note ids start where a project of a few years would be.
FIRST_PIPELINE_ID = 3100
FIRST_JOB_ID = 15400
FIRST_NOTE_ID = 52000
STATUS_DETAILS = {
    "success": ("passed", "passed", "success"),
    "failed": ("failed", "failed", "failed"),
    "running": ("running", "running", "running"),
    "created": ("created", "created", "created"),
    "skipped": ("skipped", "skipped", "skipped"),
}
# Main's pipelines: one per merge, plus the nightly one; their jobs, with minutes.
MAIN_JOBS = (
    ("lint", "build", 0.7),
    ("unit_tests", "test", 2.6),
    ("sonar", "quality", 1.9),
    ("deploy_staging", "deploy", 1.2),
)
NIGHTLY_DAYS = 30
# Days before the demo when the nightly build failed on a flaky test.
NIGHTLY_FAILURE_DAYS = (6,)


@dataclass
class Job:
    id: int
    name: str
    stage: str
    status: str
    started: float = None
    finished: float = None


@dataclass
class PipelineRun:
    id: int
    ref: str
    sha: str
    source: str
    created: float
    status: str
    jobs: list
    user: str

    def started(self):
        return self.jobs[0].started if self.jobs and self.jobs[0].started is not None else None

    def finished(self):
        ends = [job.finished for job in self.jobs if job.finished is not None]
        return min(ends) if ends and self.status in ("success", "failed") else None

    def duration_s(self):
        if self.started() is None or self.finished() is None:
            return None
        return round((self.started() - self.finished()) * 3600)


@dataclass
class Note:
    id: int
    author: str
    at: float
    body: str
    system: bool = False
    position: dict = None
    resolvable: bool = False
    resolved: bool = False


@dataclass
class Discussion:
    id: str
    notes: list


@dataclass
class MergeRequestState:
    iid: int
    spec: object
    branch: object
    record: object
    created: float
    notes: list = field(default_factory=list)
    discussions: list = field(default_factory=list)
    pipelines: list = field(default_factory=list)

    @property
    def merged(self):
        return self.branch.merged_at is not None

    @property
    def head(self):
        return self.record.pushes[-1].head


def markdown_html(text, base_url="", project_path="", people=()):
    """The Markdown the scenario writes, rendered as GitLab would: paragraphs, headings, lists and task lists,
    quotes, fenced code blocks (suggestions included), tables (the mutation report), and inline code, bold,
    italics, links, images, emoji and @mentions."""
    inline = lambda text: inline_html(text, base_url, project_path, people)
    blocks = []
    lines = [line for line in text.strip().splitlines() if not line.startswith("<!--")]
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = re.match(r"```(\w*)", line)
        if fence:
            end = next((number for number in range(index + 1, len(lines)) if lines[number].startswith("```")), len(lines))
            code = "\n".join(html.escape(code_line, quote=False) for code_line in lines[index + 1:end])
            language = fence.group(1) or "plaintext"
            blocks.append(f'<pre class="code highlight" lang="{language}"><code>{code}</code></pre>')
            index = end + 1
            continue
        if not line.strip():
            index += 1
            continue
        group = _same_kind(lines, index)
        if line.startswith("|"):
            rows = [row.strip("|").split("|") for row in group if not re.fullmatch(r"\|[-:| ]+\|", row)]
            head = "".join(f"<th>{inline(cell.strip())}</th>" for cell in rows[0])
            body = "".join("<tr>" + "".join(f"<td>{inline(cell.strip())}</td>" for cell in row) + "</tr>" for row in rows[1:])
            blocks.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        elif line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            blocks.append(f"<h{level}>{inline(line[level:].strip())}</h{level}>")
        elif re.match(r"[-*] ", line):
            if all(re.match(r"[-*] \[[ x]\] ", item) for item in group):
                blocks.append('<ul class="task-list">' + "".join(
                    f'<li class="task-list-item"><input type="checkbox" class="task-list-item-checkbox" disabled'
                    f'{" checked" if item[3] == "x" else ""}> {inline(item[6:])}</li>' for item in group) + "</ul>")
            else:
                blocks.append("<ul>" + "".join(f"<li>{inline(item[2:])}</li>" for item in group) + "</ul>")
        elif re.match(r"\d+\. ", line):
            blocks.append("<ol>" + "".join(f"<li>{inline(item.split('. ', 1)[1])}</li>" for item in group) + "</ol>")
        elif line.startswith(">"):
            blocks.append(f"<blockquote><p>{chr(10).join(inline(quoted.lstrip('> ')) for quoted in group)}</p></blockquote>")
        else:
            # As in CommonMark, a line break within a paragraph is a soft one: the browser shows a space.
            blocks.append(f"<p>{chr(10).join(inline(paragraph) for paragraph in group)}</p>")
        index += len(group)
    return "".join(blocks)


def _kind(line):
    if line.startswith("|"):
        return "table"
    if line.startswith("#"):
        return "heading"
    if re.match(r"[-*] ", line):
        return "bullets"
    if re.match(r"\d+\. ", line):
        return "numbers"
    if line.startswith(">"):
        return "quote"
    return "paragraph"


def _same_kind(lines, start):
    """The lines from start that belong to the same block: up to a blank line, a fence or another kind of line; a
    heading stands alone."""
    kind = _kind(lines[start])
    group = [lines[start]]
    if kind == "heading":
        return group
    for line in lines[start + 1:]:
        if not line.strip() or line.startswith("```") or _kind(line) != kind:
            break
        group.append(line)
    return group


EMOJI = {"x": "❌", "warning": "⚠️", "white_check_mark": "✅", "tada": "🎉", "+1": "👍", "eyes": "👀"}
# What a browser shows while GitLab's script has not yet loaded a lazy image: the address waits in data-src.
LAZY_IMAGE = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="


def inline_html(text, base_url="", project_path="", people=()):
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<![*\w])\*([^*\s][^*]*)\*(?!\w)", r"<em>\1</em>", escaped)
    escaped = re.sub(
        r"!\[([^\]]*)\]\((/uploads/[^)\s]+)\)",
        lambda match: f'<a class="no-attachment-icon" href="/{project_path}{match.group(2)}" target="_blank">'
                      f'<img src="{LAZY_IMAGE}" data-src="/{project_path}{match.group(2)}" alt="{match.group(1)}" class="lazy"></a>',
        escaped
    )
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', escaped)
    escaped = re.sub(
        r":([a-z_+0-9]+):",
        lambda match: f'<gl-emoji data-name="{match.group(1)}">{EMOJI[match.group(1)]}</gl-emoji>' if match.group(1) in EMOJI else match.group(0),
        escaped
    )
    return re.sub(
        r"(?<![\w/])@([a-z][\w.]*)",
        lambda match: f'<a href="{base_url}/{match.group(1)}" data-user="{match.group(1)}" class="gfm gfm-project_member">@{match.group(1)}</a>'
        if match.group(1) in people else match.group(0),
        escaped
    )


class Project:

    def __init__(
            self,
            base_url,
            dataset,
            history,
            repository,
            started_at
    ):
        self.base_url = base_url
        self.dataset = dataset
        self.repository = repository
        self.started_at = started_at
        self.path = dataset.PROJECT_PATH
        self.web_url = f"{base_url}/{self.path}"
        self.lock = threading.Lock()
        self._next_pipeline = FIRST_PIPELINE_ID
        self._next_job = FIRST_JOB_ID
        self.mrs = {}
        for iid, branch in sorted(history.BRANCHES.items()):
            self.mrs[iid] = MergeRequestState(
                iid,
                dataset.MERGE_REQUESTS[iid],
                branch,
                repository.branches[iid],
                branch.created_at
            )
        self.main_pipelines = []
        self._build_pipelines()
        self._build_notes()

    # ---------- Time ----------

    def iso(self, hours_before):
        if hours_before is None:
            return None
        moment = datetime.fromtimestamp(self.started_at - hours_before * 3600, timezone.utc)
        return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def now(self):
        """The present, in hours before the demo started: negative once it runs."""
        return (self.started_at - time.time()) / 3600

    # ---------- Building ----------

    def _build_pipelines(self):
        runs = []
        for mr in self.mrs.values():
            for index, push in enumerate(mr.record.pushes):
                last = index == len(mr.record.pushes) - 1
                spec = mr.spec.pipeline if last else None
                runs.append((push.at - 0.01, lambda mr=mr, push=push, spec=spec: self._mr_pipeline(mr, push, spec)))
        merges = self.repository.log([f"refs/heads/{MAIN}"], first_parent=True)
        for commit in merges:
            hours = (self.started_at - datetime.fromisoformat(commit.committed).timestamp()) / 3600
            if hours <= NIGHTLY_DAYS * 24:
                runs.append((hours - 0.01, lambda commit=commit, hours=hours: self._main_pipeline(commit.sha, hours - 0.01, "push", commit.email.split("@")[0])))
        for day in range(NIGHTLY_DAYS, 0, -1):
            at = day * 24 - 3.0 + (day % 5) * 0.1
            runs.append((at, lambda at=at, day=day: self._main_pipeline(self._main_at(at), at, "schedule", None, failed=day in NIGHTLY_FAILURE_DAYS)))
        for _, make in sorted(runs, key=lambda run: -run[0]):
            make()

    def _main_at(self, hours_before):
        for commit in self.repository.log([f"refs/heads/{MAIN}"], first_parent=True):
            if (self.started_at - datetime.fromisoformat(commit.committed).timestamp()) / 3600 >= hours_before:
                return commit.sha
        return commit.sha

    def _jobs(self, plan, created, failed_job=None, running_since=None):
        """Jobs one stage after the other from created; after a failure, the next stages are skipped; a running
        pipeline has its current job running and the next ones created."""
        jobs, clock, state = [], created, "done"
        for name, stage, minutes in plan:
            job = Job(self._next_job, name, stage, "skipped" if state == "failed" else "created")
            self._next_job += 1
            if state == "done":
                job.started = clock
                end = clock - minutes / 60
                if running_since is not None and end < 0:
                    job.status, state = "running", "running"
                else:
                    job.finished = end
                    job.status = "failed" if name == failed_job else "success"
                    state = "failed" if name == failed_job else "done"
                    clock = end
            jobs.append(job)
        return jobs

    def _mr_pipeline(self, mr, push, spec):
        created = spec.running_since if spec and spec.running_since is not None else push.at - 0.01
        jobs = self._jobs(
            self.dataset.JOBS,
            created,
            spec.failed_job if spec else None,
            spec.running_since if spec else None
        )
        status = spec.status if spec else "success"
        run = PipelineRun(self._take_pipeline_id(), mr.branch.name, push.head, "merge_request_event", created, status, jobs, mr.spec.author)
        mr.pipelines.append(run)

    def _main_pipeline(self, sha, created, source, user, failed=False):
        jobs = self._jobs(MAIN_JOBS, created, "unit_tests" if failed else None)
        run = PipelineRun(self._take_pipeline_id(), MAIN, sha, source, created, "failed" if failed else "success", jobs, user)
        self.main_pipelines.append(run)

    def _take_pipeline_id(self):
        self._next_pipeline += 1
        return self._next_pipeline

    def _build_notes(self):
        """Every note of every merge request, numbered in the order they were written across the project."""
        pending = []
        for mr in self.mrs.values():
            pushes = mr.record.pushes
            for index, push in enumerate(pushes[1:], 1):
                count = len(push.commits)
                lines = "\n".join(f"* {self.repository.commit(sha).short} - {self.repository.commit(sha).title}" for sha in push.commits)
                body = f"added {count} commit{'s' if count > 1 else ''}\n\n{lines}"
                pending.append((push.at, mr, None, Note(0, mr.spec.author, push.at, body, system=True)))
            for username, at in mr.spec.approvals:
                pending.append((at, mr, None, Note(0, username, at, "approved this merge request", system=True)))
            for number, thread in enumerate(mr.spec.threads):
                discussion = Discussion(self._discussion_id(mr.iid, number), [])
                position = self._position(mr, thread) if thread.path else None
                first = Note(0, thread.author, thread.at, thread.body, position=position, resolvable=bool(position), resolved=thread.resolved)
                pending.append((thread.at, mr, discussion, first))
                for author, at, body in thread.replies:
                    pending.append((at, mr, discussion, Note(0, author, at, body, position=position, resolvable=bool(position), resolved=thread.resolved)))
            if mr.spec.mutation:
                for run in mr.pipelines:
                    job = next((job for job in run.jobs if job.name == self.dataset.PIT_JOB and job.status == "success"), None)
                    if job:
                        at = job.finished - 0.005
                        pending.append((at, mr, "mutation", Note(0, self.dataset.BOT, at, self._mutation_body(mr.spec.mutation))))
        mutation_discussions = {}
        note_id = FIRST_NOTE_ID
        for _, mr, discussion, note in sorted(pending, key=lambda entry: -entry[0]):
            note.id = note_id
            note_id += 1
            mr.notes.append(note)
            if discussion == "mutation":
                # The job edits its single note rather than adding one per pipeline.
                previous = mutation_discussions.get(mr.iid)
                if previous:
                    mr.notes.remove(note)
                    previous.notes[0].at = note.at
                    continue
                discussion = Discussion(self._discussion_id(mr.iid, "mutation"), [])
                mutation_discussions[mr.iid] = discussion
            if discussion is None:
                discussion = Discussion(self._discussion_id(mr.iid, f"note-{note.id}"), [])
            if not discussion.notes:
                mr.discussions.append(discussion)
            discussion.notes.append(note)
        self._next_note = note_id

    @staticmethod
    def _discussion_id(iid, key):
        return hashlib.sha1(f"folio-{iid}-{key}".encode()).hexdigest()

    def _position(self, mr, thread):
        """Where a review comment sits: on the line of its text, at the last push before it was written. As GitLab
        does, a later push carries the comment along while its line is still there; once a push changes the line,
        the comment stays on the push it was written on, outdated. On the "old" side, the line is one the merge
        request removes, found at the fork point."""
        push = [push for push in mr.record.pushes if push.at >= thread.at][-1]
        latest = mr.record.pushes[-1]
        old_path = self.repository.renamed_from(push.base, push.head, thread.path)
        if thread.side == "old":
            if self.repository.has_line(latest.base, old_path, thread.line):
                push = latest
            old_line = self.repository.line_of(push.base, old_path, thread.line)
            ends = [(old_line - thread.lines + 1, None), (old_line, None)]
            new_line = None
        else:
            if self.repository.has_line(latest.head, thread.path, thread.line):
                push = latest
            new_line = self.repository.line_of(push.head, thread.path, thread.line)
            start = new_line - thread.lines + 1
            ends = [(self.repository.same_line(push.base, old_path, push.head, thread.path, number), number) for number in (start, new_line)]
            old_line = ends[1][0]
        position = {
            "base_sha": push.base, "start_sha": push.start, "head_sha": push.head,
            "position_type": "text", "old_path": old_path, "new_path": thread.path,
            "old_line": old_line, "new_line": new_line,
            "line_range": None,
        }
        if thread.lines > 1:
            code = hashlib.sha1(thread.path.encode()).hexdigest()
            position["line_range"] = {name: {
                "line_code": f"{code}_{old or 0}_{new or 0}",
                "type": "old" if new is None else ("new" if old is None else None),
                "old_line": old, "new_line": new,
            } for name, (old, new) in zip(("start", "end"), ends)}
        return position

    def _mutation_body(self, mutation):
        if mutation.unreadable:
            return f"{self.dataset.PIT_MARKER}\n### Mutation testing\n\nThe report could not be generated: see the job's log.\n"
        strength = round(100 * mutation.killed / max(1, mutation.mutants - mutation.no_coverage))
        survived = f":x: **{mutation.survived}**" if mutation.survived else "0"
        no_coverage = f":warning: **{mutation.no_coverage}**" if mutation.no_coverage else "0"
        return (
            f"{self.dataset.PIT_MARKER}\n### Mutation testing\n\n"
            "| Mutants | Killed | Survived | No coverage | Errors | Test strength |\n"
            "|--:|--:|--:|--:|--:|--:|\n"
            f"| {mutation.mutants} | {mutation.killed} | {survived} | {no_coverage} | {mutation.errors} | {strength} % |\n"
        )

    # ---------- People ----------

    def user(self, username):
        return {
            "id": sorted(self.dataset.PEOPLE).index(username) + 2,
            "username": username,
            "name": self.dataset.PEOPLE[username],
            "state": "active",
            "avatar_url": None,
            "web_url": f"{self.base_url}/{username}",
        }

    def html(self, text):
        """A note's body as GitLab renders it, with the project's people and uploads."""
        return markdown_html(text, self.base_url, self.path, self.dataset.PEOPLE)

    # ---------- REST ----------

    def rest_mr(self, mr, detail=False):
        spec = mr.spec
        last_push = mr.record.pushes[-1]
        updated = min([last_push.at, *(note.at for note in mr.notes)] + ([mr.branch.merged_at] if mr.merged else []))
        body = {
            "id": 900 + mr.iid,
            "iid": mr.iid,
            "project_id": self.dataset.PROJECT_ID,
            "title": spec.title,
            "description": "",
            "state": "merged" if mr.merged else "opened",
            "created_at": self.iso(mr.created),
            "updated_at": self.iso(updated),
            "merged_at": self.iso(mr.branch.merged_at),
            "merged_by": self.user(mr.branch.merged_by) if mr.merged else None,
            "source_branch": mr.branch.name,
            "target_branch": mr.branch.target,
            "sha": mr.head,
            "merge_commit_sha": mr.record.merge_commit,
            "squash_commit_sha": mr.record.squash_commit,
            "squash": mr.branch.squash,
            "draft": spec.draft,
            "work_in_progress": spec.draft,
            "has_conflicts": not mr.merged and self.repository.conflicts(mr.head, f"refs/heads/{mr.branch.target}"),
            "labels": list(spec.labels),
            "user_notes_count": sum(1 for note in mr.notes if not note.system),
            "author": self.user(spec.author),
            "assignees": [self.user(username) for username in (spec.assignees or (spec.author,))],
            "reviewers": [self.user(reviewer) for reviewer in spec.reviewers],
            "web_url": f"{self.web_url}/-/merge_requests/{mr.iid}",
            "references": {"short": f"!{mr.iid}", "full": f"{self.path}!{mr.iid}"},
        }
        if detail:
            run = mr.pipelines[-1] if mr.pipelines else None
            body["head_pipeline"] = self.rest_pipeline(run) if run else None
            body["diverged_commits_count"] = 0 if mr.merged else self.repository.count(f"{mr.head}..refs/heads/{mr.branch.target}")
        return body

    def rest_pipeline(self, run):
        text, label, group = STATUS_DETAILS[run.status]
        return {
            "id": run.id,
            "iid": run.id - FIRST_PIPELINE_ID,
            "project_id": self.dataset.PROJECT_ID,
            "sha": run.sha,
            "ref": run.ref,
            "status": run.status,
            "source": run.source,
            "created_at": self.iso(run.created),
            "updated_at": self.iso(run.finished() or run.created),
            "started_at": self.iso(run.started()),
            "finished_at": self.iso(run.finished()),
            "duration": run.duration_s(),
            "web_url": f"{self.web_url}/-/pipelines/{run.id}",
            "detailed_status": {"text": text, "label": label, "group": group, "icon": f"status_{group}"},
        }

    def rest_job(self, job):
        return {
            "id": job.id,
            "name": job.name,
            "stage": job.stage,
            "status": job.status,
            "started_at": self.iso(job.started),
            "finished_at": self.iso(job.finished),
            "web_url": f"{self.web_url}/-/jobs/{job.id}",
        }

    def rest_commit(self, commit):
        return {
            "id": commit.sha,
            "short_id": commit.short,
            "title": commit.title,
            "message": commit.title,
            "author_name": commit.author,
            "author_email": commit.email,
            "authored_date": commit.authored,
            "committed_date": commit.committed,
            "parent_ids": list(commit.parents),
            "web_url": f"{self.web_url}/-/commit/{commit.sha}",
        }

    def rest_note(self, mr, note):
        body = {
            "id": note.id,
            "type": "DiffNote" if note.position else ("DiscussionNote" if note.resolvable else None),
            "body": note.body,
            "author": self.user(note.author),
            "created_at": self.iso(note.at),
            "updated_at": self.iso(note.at),
            "system": note.system,
            "noteable_type": "MergeRequest",
            "noteable_iid": mr.iid,
            "resolvable": note.resolvable,
            "resolved": note.resolved if note.resolvable else False,
        }
        if note.position:
            body["position"] = note.position
        return body

    def rest_discussion(self, mr, discussion):
        return {
            "id": discussion.id,
            "individual_note": len(discussion.notes) == 1 and not discussion.notes[0].resolvable,
            "notes": [self.rest_note(mr, note) for note in discussion.notes],
        }

    def rest_versions(self, mr):
        versions = []
        for index, push in enumerate(mr.record.pushes):
            versions.append({
                "id": 7000 + mr.iid * 10 + index,
                "head_commit_sha": push.head,
                "base_commit_sha": push.base,
                "start_commit_sha": push.start,
                "created_at": self.iso(push.at),
                "merge_request_id": 900 + mr.iid,
                "state": "collected",
                "real_size": str(self.repository.diff_stats(push.base, push.head)[2]),
            })
        return versions[::-1]

    def mr_commits(self, mr):
        last = mr.record.pushes[-1]
        return self.repository.log([f"{last.base}..{last.head}"])

    def pipeline(self, pipeline_id):
        for run in self.main_pipelines + [run for mr in self.mrs.values() for run in mr.pipelines]:
            if run.id == pipeline_id:
                return run
        return None

    # ---------- GraphQL ----------

    def gid(self, kind, number):
        return f"gid://gitlab/{kind}/{number}"

    def graphql_mr(self, mr, open_view):
        last = mr.record.pushes[-1]
        commits = self.mr_commits(mr)
        additions, deletions, files = self.repository.diff_stats(last.base, last.head)
        approved = [username for username, _ in mr.spec.approvals]
        threads = [discussion for discussion in mr.discussions if discussion.notes[0].resolvable]
        node = {
            "iid": str(mr.iid),
            "diffStatsSummary": {"additions": additions, "deletions": deletions, "fileCount": files},
            "commitCount": len(commits),
            "commits": {"nodes": [{"committedDate": commits[0].committed, "authoredDate": commits[0].authored}]},
            "mergeRequestDiffs": {"nodes": [{"createdAt": self.iso(last.at)}]},
            "approvedBy": {"nodes": [{"name": self.dataset.PEOPLE[username], "username": username} for username in approved]},
            "reviewers": {"nodes": [{
                "name": self.dataset.PEOPLE[reviewer],
                "mergeRequestInteraction": {"reviewState": "APPROVED" if reviewer in approved else mr.spec.review_states.get(reviewer, "UNREVIEWED")},
            } for reviewer in mr.spec.reviewers]},
            "resolvableDiscussionsCount": len(threads),
            "resolvedDiscussionsCount": sum(1 for discussion in threads if all(note.resolved for note in discussion.notes)),
        }
        if open_view:
            comments = [note for note in mr.notes if not note.system][-10:]
            activity = [note for note in mr.notes if note.system][-10:]
            node["lastComments"] = {"nodes": [{
                "id": self.gid("Note", note.id), "createdAt": self.iso(note.at),
                "author": {"username": note.author, "name": self.dataset.PEOPLE[note.author]},
            } for note in comments]}
            node["lastActivity"] = {"nodes": [{
                "bodyFirstLineHtml": f"<p>{html.escape(note.body.splitlines()[0])}</p>", "createdAt": self.iso(note.at),
                "author": {"username": note.author, "name": self.dataset.PEOPLE[note.author]},
            } for note in activity]}
            run = mr.pipelines[-1] if mr.pipelines else None
            node["headPipeline"] = {
                "id": self.gid("Ci::Pipeline", run.id),
                "jobs": {"nodes": [{
                    "id": self.gid("Ci::Build", job.id), "name": job.name, "status": job.status.upper(),
                    "startedAt": self.iso(job.started), "finishedAt": self.iso(job.finished),
                    "webPath": f"/{self.path}/-/jobs/{job.id}",
                } for job in run.jobs]},
            } if run else None
        else:
            node["firstCommit"] = {"nodes": [{"authoredDate": commits[-1].authored}]}
        return node

    def graphql_pipeline(self, run):
        if run is None:
            return None
        text, label, group = STATUS_DETAILS[run.status]
        stages = []
        for job in run.jobs:
            if not stages or stages[-1]["name"] != job.stage:
                stages.append({"name": job.stage, "jobs": []})
            stages[-1]["jobs"].append(job)
        commit = self.repository.commit(run.sha)
        return {
            "id": self.gid("Ci::Pipeline", run.id),
            "path": f"/{self.path}/-/pipelines/{run.id}",
            "duration": run.duration_s(),
            "createdAt": self.iso(run.created),
            "startedAt": self.iso(run.started()),
            "detailedStatus": {"text": text, "label": label, "group": group},
            "sha": commit.short,
            "user": {"name": self.dataset.PEOPLE[run.user]} if run.user else {"name": "Folio CI"},
            "commit": {"title": commit.title, "webPath": f"/{self.path}/-/commit/{commit.sha}"},
            "stages": {"nodes": [{
                "name": stage["name"],
                "detailedStatus": dict(zip(("label", "group"), self._stage_status(stage["jobs"]))),
                "jobs": {"nodes": [{
                    "name": job.name, "webPath": f"/{self.path}/-/jobs/{job.id}",
                    "duration": round((job.started - job.finished) * 3600) if job.finished is not None else None,
                    "detailedStatus": {"text": STATUS_DETAILS[job.status][0], "group": STATUS_DETAILS[job.status][2]},
                } for job in stage["jobs"]]},
            } for stage in stages]},
        }

    @staticmethod
    def _stage_status(jobs):
        for status in ("failed", "running", "created", "skipped"):
            if any(job.status == status for job in jobs):
                return STATUS_DETAILS[status][1:]
        return STATUS_DETAILS["success"][1:]

    def graphql_note(self, mr, note):
        return {
            "id": self.gid("DiffNote" if note.position else "Note", note.id),
            "system": note.system,
            "url": f"{self.web_url}/-/merge_requests/{mr.iid}#note_{note.id}",
            "createdAt": self.iso(note.at),
            "author": {"name": self.dataset.PEOPLE[note.author]},
            "position": {"positionType": "text"} if note.position else None,
            "bodyHtml": self.html(note.body),
        }

    # ---------- Writes ----------

    def add_discussion(self, mr, body, position):
        note = Note(self._take_note_id(), self.dataset.ME, self.now(), body, position=position, resolvable=True)
        discussion = Discussion(hashlib.sha1(f"folio-{mr.iid}-new-{note.id}".encode()).hexdigest(), [note])
        mr.notes.append(note)
        mr.discussions.append(discussion)
        return discussion

    def add_reply(self, mr, discussion, body):
        first = discussion.notes[0]
        note = Note(self._take_note_id(), self.dataset.ME, self.now(), body, position=first.position, resolvable=first.resolvable,
                    resolved=first.resolved)
        mr.notes.append(note)
        discussion.notes.append(note)
        return note

    def resolve(self, discussion, resolved):
        for note in discussion.notes:
            if note.resolvable:
                note.resolved = resolved

    def _take_note_id(self):
        self._next_note += 1
        return self._next_note
