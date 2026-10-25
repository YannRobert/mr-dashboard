"""A fake GitLab and SonarQube, answering the requests MisteR Dashboard makes with the merge requests of a scenario.

Only what the dashboard reads and writes is served: anything else gets a JSON 404, which shows at once when the
dashboard starts using a new endpoint. Any token is accepted. GitLab's API lives under /api/v4 and /api/graphql,
SonarQube's under the other /api paths, so one server plays both; the other paths answer the links a browser
follows, with a page saying where they lead in the real GitLab.
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .project import Project
from .repository import MAIN

MAX_BODY_BYTES = 65536
DEFAULT_PER_PAGE = 20
# Sonar keeps the analysis of an inactive pull request this many days.
SONAR_RETENTION_DAYS = "30"
MR_PATH = re.compile(r"^merge_requests/(\d+)(/.*)?\Z")
DISCUSSION_PATH = re.compile(r"^/discussions/([0-9a-f]{40})(/notes)?\Z")
PIPELINE_PATH = re.compile(r"^pipelines/(\d+)(/jobs)?\Z")
GRAPHQL_STRING = r'"((?:[^"\\]|\\.)*)"'
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Demo GitLab</title>
<style>body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem; }}</style></head>
<body><h1>Demo GitLab</h1><p>In a real GitLab, this link opens <code>{path}</code>.</p>
<p>The demo GitLab only answers MisteR Dashboard's API requests: its merge requests exist nowhere else.</p></body></html>
"""


class FakeGitlabServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
            self,
            port,
            dataset,
            history,
            repository,
            started_at
    ):
        super().__init__(
            ("127.0.0.1", port),
            FakeGitlabHandler
        )
        self.base_url = f"http://127.0.0.1:{self.server_address[1]}"
        self.project = Project(
            self.base_url,
            dataset,
            history,
            repository,
            started_at
        )
        self.quiet = False


class NotServed(Exception):
    pass


class FakeGitlabHandler(BaseHTTPRequestHandler):

    # The dashboard keeps its upstream connections open: every response carries its Content-Length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        target = urlsplit(self.path)
        query = parse_qs(target.query)
        project = self.server.project
        try:
            if target.path.startswith("/api/v4/"):
                self.gitlab_get(target.path[len("/api/v4/"):], query)
            elif target.path == "/api/graphql":
                with project.lock:
                    data = self.graphql(first(query, "query") or "", json.loads(first(query, "variables") or "{}"))
                self.send_json(200, {"data": data})
            elif target.path.startswith("/api/"):
                self.sonar_get(target.path[len("/api/"):], query)
            elif target.path.startswith(f"/{project.path}/uploads/"):
                image = project.dataset.UPLOADS.get(target.path.rsplit("/", 1)[-1])
                if image is None:
                    raise NotServed()
                self.send_body(200, image.encode(), "image/svg+xml")
            else:
                self.send_body(200, PAGE.format(path=unquote(target.path)).encode(), "text/html; charset=utf-8")
        except NotServed:
            self.not_served()

    def do_POST(self):
        self.write("POST")

    def do_PUT(self):
        self.write("PUT")

    # ---------- GitLab REST ----------

    def gitlab_get(self, path, query):
        project = self.server.project
        if path == "user":
            return self.send_json(200, project.user(project.dataset.ME))
        if path == "users":
            username = first(query, "username")
            return self.send_json(200, [project.user(username)] if username in project.dataset.PEOPLE else [])
        rest = self.project_rest(path)
        with project.lock:
            if rest == "merge_requests":
                return self.merge_requests(query)
            mr_match = MR_PATH.match(rest)
            if mr_match:
                return self.merge_request(project.mrs.get(int(mr_match.group(1))), mr_match.group(2) or "", query)
            pipeline_match = PIPELINE_PATH.match(rest)
            if pipeline_match:
                run = project.pipeline(int(pipeline_match.group(1)))
                if run is None:
                    return self.send_json(404, {"message": "404 Pipeline Not Found"})
                if pipeline_match.group(2):
                    jobs = [] if "canceled" in query.get("scope[]", []) else run.jobs
                    return self.send_page([project.rest_job(job) for job in jobs], query)
                return self.send_json(200, project.rest_pipeline(run))
            if rest == "repository/merge_base":
                refs = query.get("refs[]", [])
                sha = project.repository.merge_base(*(self.resolve(ref) for ref in refs))
                return self.send_json(200, project.rest_commit(project.repository.commit(sha)))
            if rest == "repository/commits":
                ref = self.resolve(first(query, "ref_name") or MAIN)
                options = [f"--since={first(query, 'since')}"] if first(query, "since") else []
                commits = project.repository.log([*options, ref], first_parent=first(query, "first_parent") == "true")
                return self.send_page([project.rest_commit(commit) for commit in commits], query)
        raise NotServed()

    def project_rest(self, path):
        """The part after projects/<id or path>/ for the demo project; NotServed for another one."""
        project = self.server.project
        for prefix in (f"projects/{project.path.replace('/', '%2F')}/", f"projects/{project.path.replace('/', '%2f')}/",
                       f"projects/{project.dataset.PROJECT_ID}/"):
            if path.startswith(prefix):
                return path[len(prefix):]
        raise NotServed()

    def resolve(self, ref):
        """A sha or a branch name, as a revision of the bare repository."""
        ref = unquote(ref)
        return ref if re.fullmatch(r"[0-9a-f]{40}", ref) else f"refs/heads/{ref}"

    def merge_requests(self, query):
        project = self.server.project
        state = first(query, "state") or "all"
        iids = {int(iid) for iid in query.get("iids[]", [])}
        mrs = [
            mr for mr in sorted(project.mrs.values(), key=lambda mr: mr.created)
            if state == "all" or (state == "merged") == mr.merged
            if not iids or mr.iid in iids
        ]
        self.send_page([project.rest_mr(mr) for mr in mrs], query)

    def merge_request(self, mr, rest, query):
        project = self.server.project
        if mr is None:
            return self.send_json(404, {"message": "404 Not found"})
        if rest == "":
            return self.send_json(200, project.rest_mr(mr, detail=True))
        if rest == "/commits":
            return self.send_page([project.rest_commit(commit) for commit in project.mr_commits(mr)], query)
        if rest == "/versions":
            return self.send_page(project.rest_versions(mr), query)
        if rest == "/notes":
            notes = sorted(mr.notes, key=lambda note: note.at, reverse=first(query, "sort") != "desc")
            return self.send_page([project.rest_note(mr, note) for note in notes], query)
        if rest == "/discussions":
            return self.send_page([project.rest_discussion(mr, discussion) for discussion in mr.discussions], query)
        discussion_match = DISCUSSION_PATH.match(rest)
        if discussion_match and not discussion_match.group(2):
            discussion = self.discussion(mr, discussion_match.group(1))
            return self.send_json(200, project.rest_discussion(mr, discussion)) if discussion else self.send_json(404, {"message": "404 Not found"})
        if rest == "/approvals":
            return self.send_json(200, {"approved_by": [{"user": project.user(username)} for username, _ in mr.spec.approvals]})
        if rest == "/reviewers":
            return self.send_json(200, [{
                "user": project.user(reviewer),
                "state": mr.spec.review_states.get(reviewer, "unreviewed").lower(),
            } for reviewer in mr.spec.reviewers])
        if rest == "/blocks":
            return self.send_page([{"blocking_merge_request": project.rest_mr(project.mrs[iid])} for iid in mr.spec.blocked_by], query)
        if rest == "/blockees":
            return self.send_page([{"blocked_merge_request": project.rest_mr(other)} for other in project.mrs.values()
                                   if mr.iid in other.spec.blocked_by], query)
        if rest == "/pipelines":
            return self.send_page([project.rest_pipeline(run) for run in reversed(mr.pipelines)], query)
        raise NotServed()

    @staticmethod
    def discussion(mr, discussion_id):
        return next((discussion for discussion in mr.discussions if discussion.id == discussion_id), None)

    # ---------- GitLab GraphQL ----------

    def graphql(self, query, variables):
        """Recognises the dashboard's queries by a piece of their text: their fields are fixed, so each answer
        carries all of them."""
        project = self.server.project
        open_mrs = [mr for mr in project.mrs.values() if not mr.merged]
        if "mergeRequests(state: opened" in query:
            nodes = [project.graphql_mr(mr, open_view=True) for mr in open_mrs]
            return {"project": {"mergeRequests": {"pageInfo": NO_NEXT_PAGE, "nodes": nodes}}}
        if "mergeRequests(state: merged" in query:
            since = variables.get("mergedAfter")
            merged = [mr for mr in project.mrs.values() if mr.merged and (not since or project.iso(mr.branch.merged_at) >= since)]
            merged.sort(key=lambda mr: mr.branch.merged_at)
            return {"project": {"mergeRequests": {
                "count": len(merged), "pageInfo": NO_NEXT_PAGE,
                "nodes": [project.graphql_mr(mr, open_view=False) for mr in merged],
            }}}
        if "successfulPipelines:" in query:
            branch = variables.get("branch", MAIN)
            runs = [run for run in reversed(project.main_pipelines) if run.ref == branch]
            successes = [run for run in runs if run.status == "success"]
            failures = [run for run in runs if run.status == "failed"]
            return {"project": {
                "successfulPipelines": {"nodes": [{"duration": run.duration_s()} for run in successes[:5]]},
                "pipelines": {"nodes": [project.graphql_pipeline(run) for run in runs[:1]]},
                "lastSuccess": {"nodes": [project.graphql_pipeline(run) for run in successes[:1]]},
                "lastFailure": {"nodes": [project.graphql_pipeline(run) for run in failures[:1]]},
            }}
        if 'source: "merge_request_event"' in query:
            runs = sorted((run for mr in project.mrs.values() for run in mr.pipelines if run.status == "success"), key=lambda run: run.created)
            return {"project": {"pipelines": {"nodes": [{
                "duration": run.duration_s(), "canceledJobs": {"count": 0},
            } for run in runs[:20]]}}}
        if "pipelines(ref: $branch, status: SUCCESS, first: 100" in query:
            runs = [run for run in reversed(project.main_pipelines) if run.status == "success"]
            return {"project": {"pipelines": {"pageInfo": NO_NEXT_PAGE, "nodes": [{
                "id": project.gid("Ci::Pipeline", run.id), "duration": run.duration_s(), "createdAt": project.iso(run.created),
            } for run in runs[:100]]}}}
        mr = self.graphql_mr(query)
        if "discussions(first: 50" in query:
            return {"project": {"mergeRequest": self.comments(mr) if mr else None}}
        if "notes(first: 100" in query:
            return {"project": {"mergeRequest": {"notes": {"pageInfo": NO_NEXT_PAGE, "nodes": [{
                "id": project.gid("DiffNote" if note.position else "Note", note.id), "bodyHtml": project.html(note.body),
            } for note in mr.notes]}} if mr else None}}
        raise NotServed()

    def graphql_mr(self, query):
        project = self.server.project
        path = re.search(r"fullPath: " + GRAPHQL_STRING, query)
        iid = re.search(r"mergeRequest\(iid: " + GRAPHQL_STRING, query)
        if not path or not iid or json.loads(f'"{path.group(1)}"') != project.path:
            return None
        return project.mrs.get(int(iid.group(1))) if iid.group(1).isdigit() else None

    def comments(self, mr):
        project = self.server.project
        return {
            "title": mr.spec.title,
            "webUrl": f"{project.web_url}/-/merge_requests/{mr.iid}",
            "state": "merged" if mr.merged else "opened",
            "sourceBranch": mr.branch.name,
            "targetBranch": mr.branch.target,
            "diffHeadSha": mr.head,
            "mergeCommitSha": mr.record.merge_commit,
            "author": {"name": project.dataset.PEOPLE[mr.spec.author]},
            "discussions": {"pageInfo": NO_NEXT_PAGE, "nodes": [{
                "id": project.gid("Discussion", discussion.id),
                "resolvable": discussion.notes[0].resolvable,
                "resolved": discussion.notes[0].resolvable and all(note.resolved for note in discussion.notes),
                "notes": {"nodes": [project.graphql_note(mr, note) for note in discussion.notes]},
            } for discussion in mr.discussions]},
        }

    # ---------- SonarQube ----------

    def sonar_get(self, path, query):
        project = self.server.project
        dataset = project.dataset
        if first(query, "project") not in (None, dataset.SONAR_PROJECT) or first(query, "component") not in (None, dataset.SONAR_PROJECT):
            return self.send_json(404, {"errors": [{"msg": "Component key not found"}]})
        with project.lock:
            if path == "project_pull_requests/list":
                return self.send_json(200, {"pullRequests": [self.sonar_pull_request(mr) for mr in project.mrs.values() if self.sonar_kept(mr)]})
            if path == "settings/values":
                return self.send_json(200, {"settings": [{"key": first(query, "keys"), "value": SONAR_RETENTION_DAYS}]})
            mr = project.mrs.get(int(first(query, "pullRequest") or 0))
            if mr is None:
                return self.send_json(404, {"errors": [{"msg": "Pull request not found"}]})
            if path == "issues/search":
                return self.send_json(200, {"total": mr.spec.sonar.issues, "p": 1, "ps": 1, "issues": []})
            if path == "measures/component":
                return self.send_json(200, {"component": {"key": dataset.SONAR_PROJECT, "measures": self.sonar_measures(mr)}})
        raise NotServed()

    def sonar_kept(self, mr):
        """Whether Sonar still holds the analysis of an open merge request: not when it lost it, nor once the
        analysis is older than the retention period."""
        analysis = self.sonar_analysis(mr)
        return (not mr.merged and analysis is not None and not mr.spec.sonar.missing
                and analysis - self.server.project.now() < int(SONAR_RETENTION_DAYS) * 24)

    def sonar_analysis(self, mr):
        """When Sonar last analysed the merge request: the end of the last sonar job that succeeded."""
        jobs = [job for run in mr.pipelines for job in run.jobs if job.name == self.server.project.dataset.SONAR_JOB and job.status == "success"]
        return jobs[-1].finished if jobs else None

    def sonar_pull_request(self, mr):
        project = self.server.project
        return {
            "key": str(mr.iid),
            "title": mr.spec.title,
            "branch": mr.branch.name,
            "base": mr.branch.target,
            "status": {"qualityGateStatus": mr.spec.sonar.gate, "bugs": 0, "vulnerabilities": 0, "codeSmells": mr.spec.sonar.issues},
            "analysisDate": project.iso(self.sonar_analysis(mr)).replace("Z", "+0000"),
            "url": f"{project.base_url}/sonar/{mr.iid}",
        }

    def sonar_measures(self, mr):
        project = self.server.project
        last = mr.record.pushes[-1]
        additions, _, _ = project.repository.diff_stats(last.base, last.head)
        to_cover = max(1, additions // 2)
        uncovered = round(to_cover * (100 - mr.spec.sonar.coverage) / 100)
        values = {
            "new_coverage": f"{mr.spec.sonar.coverage:.1f}",
            "new_lines_to_cover": str(to_cover),
            "new_uncovered_lines": str(uncovered),
            "new_uncovered_conditions": "0",
        }
        return [{"metric": metric, "period": {"index": 1, "value": value}} for metric, value in values.items()]

    # ---------- Writes ----------

    def write(self, method):
        project = self.server.project
        try:
            rest = self.project_rest(urlsplit(self.path).path[len("/api/v4/"):])
            match = MR_PATH.match(rest)
            mr = project.mrs.get(int(match.group(1))) if match else None
            if mr is None:
                raise NotServed()
            body = self.read_json()
            with project.lock:
                tail = match.group(2) or ""
                if method == "POST" and tail == "/discussions":
                    discussion = project.add_discussion(mr, body["body"], body.get("position"))
                    return self.send_json(201, project.rest_discussion(mr, discussion))
                discussion_match = DISCUSSION_PATH.match(tail)
                discussion = self.discussion(mr, discussion_match.group(1)) if discussion_match else None
                if discussion is None:
                    raise NotServed()
                if method == "POST" and discussion_match.group(2):
                    note = project.add_reply(mr, discussion, body["body"])
                    return self.send_json(201, project.rest_note(mr, note))
                if method == "PUT" and not discussion_match.group(2):
                    project.resolve(discussion, bool(body.get("resolved")))
                    return self.send_json(200, project.rest_discussion(mr, discussion))
            raise NotServed()
        except NotServed:
            self.not_served()
        except (ValueError, KeyError, TypeError):
            self.send_json(400, {"message": "400 Bad request"})

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(length) or b"{}")

    # ---------- Responses ----------

    def send_page(self, items, query):
        """A page of a list, with GitLab's pagination headers."""
        per_page = int(first(query, "per_page") or DEFAULT_PER_PAGE)
        page = int(first(query, "page") or 1)
        pages = max(1, -(-len(items) // per_page))
        headers = {
            "X-Total": str(len(items)),
            "X-Total-Pages": str(pages),
            "X-Page": str(page),
            "X-Per-Page": str(per_page),
            "X-Next-Page": str(page + 1) if page < pages else "",
        }
        self.send_json(200, items[(page - 1) * per_page:page * per_page], headers)

    def not_served(self):
        self.send_json(404, {"message": f"404 Not served by the demo GitLab: {self.command} {urlsplit(self.path).path}"})

    def send_json(self, status, body, headers=None):
        self.send_body(
            status,
            json.dumps(body).encode(),
            "application/json",
            headers
        )

    def send_body(self, status, body, content_type, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if not self.server.quiet:
            super().log_message(format, *args)


NO_NEXT_PAGE = {"hasNextPage": False, "endCursor": None}


def first(query, name):
    values = query.get(name)
    return values[0] if values else None


def start(
        port,
        dataset,
        history,
        repository,
        started_at,
        quiet
):
    """Starts the fake GitLab in the background and returns it."""
    server = FakeGitlabServer(
        port,
        dataset,
        history,
        repository,
        started_at
    )
    server.quiet = quiet
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
