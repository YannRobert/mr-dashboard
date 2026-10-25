#!/usr/bin/env python3
"""MisteR Dashboard: the Merge Requests dashboard.

Local dashboard of open MRs, with CI signals (pipeline, PIT, Sonar) as badges.

The page (index.html) only talks to this server, which relays these prefixes:
    /gitlab/<path>    →  <gitlab>/api/v4/<path>     (glab token, PRIVATE-TOKEN header)
    /sonar/<path>     →  <sonar>/api/<path>         (SONAR_TOKEN, Bearer header)
    /graphql?query=…  →  <gitlab>/api/graphql?…     (glab token; over GET, GitLab rejects mutations)

The relay is required for Sonar, which returns no CORS header: a browser cannot query it directly. It
also keeps both tokens out of the browser. Only GET is relayed, and the server only listens on
127.0.0.1: the only writes to GitLab are the /gitlab/… actions below, which validate their request
before forwarding it.

Local actions, over POST:
    /launch       starts a coding agent with the prompt of a MR's AI button action, in a tab of one of the
                launch targets (see launch_targets.py): {"iid", "action", "prompt", "agent", "model", "effort",
                "target"}, agent being an installed agent's id (default: claude, see agents.py) and target a
                launch target's id (default: the first one);
                GET /ai/actions returns the catalog (see ai_actions.py),
                GET /launch/status?launch= tells whether the shell, then the agent, started in a launch's tab,
                GET /launch/targets whether each launch target can open a tab now
    /git/fetch  git fetch of the local git clone, which also runs by itself every --git-fetch-interval
                seconds; GET /git/status returns the last result (see git_actions.py)
    /git/auto   enables or suspends automatic fetch: {"enabled": true|false}
    /gitlab/discussion  opens a discussion on one or more diff lines of a MR of the tracked project:
                {"iid", "body", "position"}, position in the GitLab API format
    /gitlab/reply       replies to a thread of a MR of the tracked project: {"iid", "discussion", "body"}
    /gitlab/resolve     resolves a thread, or reopens it: {"iid", "discussion", "resolved": true|false}
    /git/diff   GET ?branch=&target=: diff of a MR from the point where it leaves its target, displayed
                by diff.html; ?iid=&head=&merge=&target= for a merged MR, found through its commits;
                &first=&last= for what its commits from first to last brought together
    /git/commits GET, same parameters: commits of the MR, oldest first
    /git/branch GET ?branch=&target=: commit count, date of the last one and lag behind the target of
                an open MR, from the local git clone, without network — the page's fallback when GitLab is down
    /avatars    avatar color of each person, the same in every browser (see avatar_colors.py): GET
                returns the assignment, POST {"names", "count"} gives one, out of count, to each name
                that has none yet
    /version    GET: version of the served HTML, JS and CSS, which version.js compares with that of the
                loaded page to reload it (see front_version.py)
    /stats      GET: requests sent to GitLab (API, git fetch) and to Sonar over 1, 5 and 15 min, by
                category, including connection errors, 4xx and 5xx, and since startup
                (see request_stats.py)

Usage:
    python3 mr_dashboard/server.py --gitlab-host https://gitlab.example.com --gitlab-project <group/project> \
        --pipeline-branch <branch> --sonar-host https://sonarqube.example.com --sonar-project <key> --sonar-job <job> --pit-job <job> --pit-marker <marker> \
        --repo-dir <local git clone of the project> --git-fetch-interval 300 --port 8766
    python3 mr_dashboard/server.py --gitlab-host https://gitlab.example.com --gitlab-project <group/project> \
        --pipeline-branch main --no-sonar --no-pit   # project without Sonar analysis or mutation testing

No default points to a project: a forgotten option stops the server instead of making it track
another repository than intended.

Prerequisites:
    SONAR_TOKEN in the environment — without it, Sonar badges stay grey.
    ~/.config/glab-cli/config.yml authenticated against the GitLab host.
"""
import argparse
import base64
import http.client
import json
import os
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from copy import copy
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from ai_actions import AiActions, AiActionsError
from avatar_colors import DEFAULT_PATH as AVATAR_COLORS_PATH, AvatarColors
from front_version import FrontVersion, tag as front_version_tag
from git_actions import GitActions, GitError
import agents
import launches
from launch_targets import LaunchTargetError, TARGETS as LAUNCH_TARGETS, availability as launch_availability, choose_all as choose_launch_targets
from launches import LaunchError
from relay_cache import TTL_S, RelayCache
from request_stats import RequestStats, http_error

DEFAULT_PORT = 8765
DEFAULT_GIT_FETCH_INTERVAL_S = 300
DEFAULT_GLAB_CONFIG = os.path.expanduser("~/.config/glab-cli/config.yml")
# Content-Encoding: gzip responses are relayed as is, the browser decompresses them.
FORWARDED_RESPONSE_HEADERS = ("Content-Encoding", "X-Total", "X-Total-Pages", "X-Next-Page", "X-Page", "X-Per-Page")
UPSTREAM_TIMEOUT_S = 30
# A connection idle for longer is closed rather than reused: the proxy or the server has probably
# already cut it, and trying it would cost a round trip for nothing.
UPSTREAM_IDLE_S = 30
# The page loads 4 MRs in parallel, up to 3 requests each.
UPSTREAM_MAX_IDLE_PER_HOST = 12
STATIC_DIR = Path(__file__).resolve().parent.parent / "web"
# Libraries served from the repository rather than a CDN: the diff page also works without network.
STATIC_FILES = {
    "/vendor/diff2html/diff2html-ui-slim.min.js": "text/javascript; charset=utf-8",
    "/vendor/diff2html/diff2html.min.css": "text/css; charset=utf-8",
    "/notes.js": "text/javascript; charset=utf-8",
    "/notes.css": "text/css; charset=utf-8",
    "/tabs.js": "text/javascript; charset=utf-8",
    "/ai.js": "text/javascript; charset=utf-8",
    "/ai.css": "text/css; charset=utf-8",
    "/avatars.js": "text/javascript; charset=utf-8",
    "/anonymize.js": "text/javascript; charset=utf-8",
    "/dates.js": "text/javascript; charset=utf-8",
    "/avatars.css": "text/css; charset=utf-8",
    "/version.js": "text/javascript; charset=utf-8",
}
PAGES = {
    "/index.html": "text/html; charset=utf-8",
    "/diff.html": "text/html; charset=utf-8",
    "/comments.html": "text/html; charset=utf-8",
}
# A JS or CSS requested with ?v=<tag> never changes under that URL: the browser keeps it without
# revalidating, and reuses it even when the server does not respond.
IMMUTABLE_CACHE_CONTROL = "max-age=31536000, immutable"
# Required on POST: a non-standard header forces the browser into a CORS preflight, which this server
# never satisfies — a third-party page therefore cannot trigger the action.
ACTION_HEADER = "X-MR-Dashboard"
MAX_POST_BYTES = 64 * 1024


def gitlab_token(config_path, target_host):
    host = None
    with open(config_path) as f:
        for line in f:
            s = line.strip()
            if s.endswith(":") and "gitlab" in s:
                host = s[:-1]
            if s.startswith("token:") and host == target_host:
                return s.split(":", 1)[1].strip()
    raise RuntimeError(f"no token found for {target_host} in {config_path}")


class UpstreamPool:
    """Connections kept open per upstream host.

    Through an HTTPS proxy, opening a connection (CONNECT + TLS handshake) costs ~500 ms: more
    than the request itself. A refresh chains dozens of them; reusing them cuts their duration by ~4.
    Proxy read from the environment (https_proxy / no_proxy), like urllib.
    """

    def __init__(self):
        self._idle = {}
        self._lock = threading.Lock()

    def get(
            self,
            url,
            headers
    ):
        """GET, returning (status, body, headers); a reused connection the upstream has closed meanwhile
        is replaced once, the request being idempotent."""
        target = urlsplit(url)
        path = target.path + ("?" + target.query if target.query else "")
        connection, reused = self._acquire(target)
        try:
            return self._send(
                target,
                connection,
                "GET",
                path,
                headers
            )
        except (ConnectionError, http.client.HTTPException, ssl.SSLError):
            if not reused:
                raise
            return self._send(
                target,
                self._connect(target),
                "GET",
                path,
                headers
            )

    def write(
            self,
            method,
            url,
            headers,
            body
    ):
        """Writing request (POST, PUT), returning (status, body, headers); always on a fresh
        connection, without retry: a writing request is not replayed blindly."""
        target = urlsplit(url)
        return self._send(
            target,
            self._connect(target),
            method,
            target.path,
            headers,
            body
        )

    def _send(
            self,
            target,
            connection,
            method,
            path,
            headers,
            body=None
    ):
        try:
            connection.request(
                method,
                path,
                body=body,
                headers=headers
            )
            response = connection.getresponse()
            content = response.read()
        except BaseException:
            connection.close()
            raise
        if response.will_close:
            connection.close()
        else:
            self._release(
                target,
                connection
            )
        return response.status, content, response.headers

    def _acquire(self, target):
        now = time.monotonic()
        with self._lock:
            idle = self._idle.get(target.netloc, [])
            while idle:
                connection, released_at = idle.pop()
                if now - released_at < UPSTREAM_IDLE_S:
                    return connection, True
                connection.close()
        return self._connect(target), False

    def _release(
            self,
            target,
            connection
    ):
        with self._lock:
            idle = self._idle.setdefault(target.netloc, [])
            if len(idle) < UPSTREAM_MAX_IDLE_PER_HOST:
                idle.append((connection, time.monotonic()))
                return
        connection.close()

    @staticmethod
    def _connect(target):
        secure = target.scheme == "https"
        connection_class = http.client.HTTPSConnection if secure else http.client.HTTPConnection
        port = target.port or (443 if secure else 80)
        proxy = urllib.request.getproxies().get(target.scheme)
        if not proxy or urllib.request.proxy_bypass(target.hostname):
            return connection_class(
                target.hostname,
                port,
                timeout=UPSTREAM_TIMEOUT_S
            )
        proxy = urlsplit(proxy if "://" in proxy else "http://" + proxy)
        tunnel_headers = {}
        if proxy.username:
            credentials = f"{unquote(proxy.username)}:{unquote(proxy.password or '')}"
            tunnel_headers["Proxy-Authorization"] = "Basic " + base64.b64encode(credentials.encode()).decode()
        connection = connection_class(
            proxy.hostname,
            proxy.port or 80,
            timeout=UPSTREAM_TIMEOUT_S
        )
        connection.set_tunnel(
            target.hostname,
            port,
            headers=tunnel_headers
        )
        return connection


def make_handler(
        settings,
        launch_targets,
        git,
        ai_actions,
        stats,
        avatar_colors
):
    upstream = UpstreamPool()
    relay_cache = RelayCache()
    front_version = FrontVersion(STATIC_DIR, {**PAGES, **STATIC_FILES})

    class Handler(BaseHTTPRequestHandler):

        # Connection kept between two browser requests; each response carries its Content-Length.
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if not self.host_allowed():
                return
            path = urlsplit(self.path).path
            if path == "/":
                path = "/index.html"
            if path in PAGES:
                self.send_file(path, front_version.versioned_html(self.read_static(path)), False)
            elif path in STATIC_FILES:
                self.send_file(path, self.read_static(path), "v=" in urlsplit(self.path).query)
            elif self.path == "/config":
                self.send_json(200, settings["public"])
            elif self.path == "/version":
                self.send_json(200, {"version": front_version.version()})
            elif self.path == "/ai/actions":
                try:
                    self.send_json(200, ai_actions.catalog())
                except AiActionsError as error:
                    self.send_json(500, {"message": str(error)})
            elif self.path == "/git/status":
                self.send_json(200, git.status())
            elif self.path == "/stats":
                self.send_json(200, stats.snapshot())
            elif self.path == "/avatars":
                self.send_json(200, avatar_colors.snapshot())
            elif self.path == "/launch/targets":
                self.send_json(200, launch_availability(launch_targets))
            elif self.path.startswith("/launch/status?"):
                self.launch_status(parse_qs(urlsplit(self.path).query))
            elif self.path.startswith("/git/diff?"):
                self.git_diff(parse_qs(urlsplit(self.path).query))
            elif self.path.startswith("/git/commits?"):
                self.git_commits(parse_qs(urlsplit(self.path).query))
            elif self.path.startswith("/git/branch?"):
                self.git_branch(parse_qs(urlsplit(self.path).query))
            elif self.path.startswith("/gitlab/"):
                self.relay(
                    "GitLab",
                    settings["gitlab_host"] + "/api/v4/" + self.path[len("/gitlab/"):],
                    {"PRIVATE-TOKEN": settings["gitlab_token"]}
                )
            elif self.path.startswith("/graphql?"):
                self.relay(
                    "GitLab",
                    settings["gitlab_host"] + "/api" + self.path,
                    {"PRIVATE-TOKEN": settings["gitlab_token"]}
                )
            elif self.path.startswith("/sonar/"):
                if not settings["sonar_token"]:
                    self.send_json(503, {"message": "SONAR_TOKEN missing from the server environment"})
                    return
                self.relay(
                    "Sonar",
                    settings["sonar_host"] + "/api/" + self.path[len("/sonar/"):],
                    {"Authorization": "Bearer " + settings["sonar_token"]}
                )
            else:
                self.send_json(404, {"message": "not found"})

        def do_POST(self):
            if not self.host_allowed():
                return
            actions = {
                "/launch": self.launch,
                "/git/fetch": self.git_fetch,
                "/git/auto": self.git_auto,
                "/gitlab/discussion": self.gitlab_discussion,
                "/gitlab/reply": self.gitlab_reply,
                "/gitlab/resolve": self.gitlab_resolve,
                "/avatars": self.avatars
            }
            action = actions.get(self.path)
            if not action:
                self.close_connection = True
                self.send_json(404, {"message": "not found"})
                return
            origins = {f"http://{host}:{self.server.server_port}" for host in ("localhost", "127.0.0.1")}
            if self.headers.get(ACTION_HEADER) != "1" or self.headers.get("Origin") not in origins:
                self.close_connection = True
                self.send_json(403, {"message": "origin rejected"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_POST_BYTES:
                self.close_connection = True
                self.send_json(413, {"message": "request too large"})
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self.send_json(400, {"message": "invalid request"})
                return
            action(payload)

        def launch(self, payload):
            try:
                iid = int(payload["iid"])
                action = str(payload["action"])
                prompt = str(payload["prompt"])
                model = payload.get("model")
                effort = payload.get("effort")
                target_id = payload.get("target")
                agent = agents.find(str(payload.get("agent") or "claude"))
            except (ValueError, KeyError, TypeError):
                self.send_json(400, {"message": "invalid request"})
                return
            if agent is None:
                self.send_json(400, {"message": f"agent not installed: {payload.get('agent')}"})
                return
            # Only an offered model and level get through: the command launched goes through a shell.
            if model is not None and agent.find(model) is None:
                self.send_json(400, {"message": f"model not offered by {agent.name}: {model}"})
                return
            if effort is not None and effort not in agent.efforts(model):
                self.send_json(400, {"message": f"effort level not offered for this model: {effort}"})
                return
            if not launch_targets:
                self.send_json(503, {"message": "no launch target: prompts are copied (see --launch-in)"})
                return
            launch_target = next((target for target in launch_targets if target.id == target_id), None) if target_id else launch_targets[0]
            if launch_target is None:
                self.send_json(400, {"message": f"launch target not offered: {target_id}"})
                return
            try:
                title = ai_actions.tab_title(
                    action,
                    iid
                )
            except AiActionsError as error:
                self.send_json(400, {"message": str(error)})
                return
            try:
                result = launch_target.launch(
                    iid,
                    title,
                    prompt,
                    model,
                    effort,
                    agent
                )
            except LaunchError as error:
                self.send_json(502, {"message": str(error)})
                return
            self.send_json(200, {**result, "title": title})

        def launch_status(self, query):
            try:
                progress = launches.progress(query.get("launch", [""])[0])
            except LaunchError as error:
                self.send_json(400, {"message": str(error)})
                return
            self.send_json(200, progress)

        def git_fetch(self, payload):
            signature = payload.get("signature") if isinstance(payload, dict) else None
            if signature is None:
                git.fetch()
            elif isinstance(signature, str):
                git.fetch_if_changed(signature)
            else:
                self.send_json(400, {"message": "invalid request"})
                return
            self.send_json(200, git.status())

        def avatars(self, payload):
            names = payload.get("names") if isinstance(payload, dict) else None
            count = payload.get("count") if isinstance(payload, dict) else None
            if (not isinstance(names, list) or not all(isinstance(name, str) and name for name in names)
                    or not isinstance(count, int) or isinstance(count, bool) or count < 1):
                self.send_json(400, {"message": "invalid request"})
                return
            self.send_json(200, avatar_colors.assign(
                names,
                count
            ))

        def git_auto(self, payload):
            enabled = payload.get("enabled") if isinstance(payload, dict) else None
            if not isinstance(enabled, bool):
                self.send_json(400, {"message": "invalid request"})
                return
            git.set_auto(enabled)
            self.send_json(200, git.status())

        def gitlab_discussion(self, payload):
            request = discussion_request(payload)
            if not request:
                self.send_json(400, {"message": "invalid request"})
                return
            iid, body = request
            self.gitlab_write(
                "POST",
                f"merge_requests/{iid}/discussions",
                body
            )

        def gitlab_reply(self, payload):
            request = reply_request(payload)
            if not request:
                self.send_json(400, {"message": "invalid request"})
                return
            iid, discussion, body = request
            self.gitlab_write(
                "POST",
                f"merge_requests/{iid}/discussions/{discussion}/notes",
                body
            )

        def gitlab_resolve(self, payload):
            request = resolve_request(payload)
            if not request:
                self.send_json(400, {"message": "invalid request"})
                return
            iid, discussion, body = request
            self.gitlab_write(
                "PUT",
                f"merge_requests/{iid}/discussions/{discussion}",
                body
            )

        def gitlab_write(
                self,
                method,
                path,
                body
        ):
            """Forwards to GitLab, for the tracked project, an already validated write; path relative to the project."""
            project = quote(settings["public"]["gitlabProject"], safe="")
            try:
                status, content, upstream_headers = upstream.write(
                    method,
                    f"{settings['gitlab_host']}/api/v4/projects/{project}/{path}",
                    {"PRIVATE-TOKEN": settings["gitlab_token"], "Content-Type": "application/json"},
                    body
                )
            except (OSError, http.client.HTTPException) as error:
                stats.record(
                    "gitlab-write",
                    "connection"
                )
                # Without a response, the write may have succeeded anyway.
                relay_cache.clear()
                self.send_json(
                    502,
                    {"message": f"relay failed: {error}"}
                )
                return
            stats.record(
                "gitlab-write",
                http_error(status)
            )
            relay_cache.clear()
            self.send_body(
                status,
                content,
                upstream_headers
            )

        def git_diff(self, query):
            first, last = (query.get(name, [None])[0] for name in ("first", "last"))
            try:
                diff = git.diff(
                    self.mr_revisions(query),
                    first,
                    last,
                    query.get("path", [])
                )
            except (GitError, ValueError) as error:
                self.send_json(409 if isinstance(error, GitError) else 400, {"message": str(error)})
                return
            self.send_body(200, diff.encode(), {"Content-Type": "text/plain; charset=utf-8"})

        def git_commits(self, query):
            try:
                commits = git.commits(self.mr_revisions(query))
            except (GitError, ValueError) as error:
                self.send_json(409 if isinstance(error, GitError) else 400, {"message": str(error)})
                return
            self.send_json(200, commits)

        def git_branch(self, query):
            branch, target = (query.get(name, [""])[0] for name in ("branch", "target"))
            if not branch or not target:
                self.send_json(400, {"message": "invalid request"})
                return
            try:
                signals = git.branch_signals(
                    branch,
                    target
                )
            except GitError as error:
                self.send_json(409, {"message": str(error)})
                return
            self.send_json(200, signals)

        # Open MR through its branches, merged MR through its commits.
        def mr_revisions(self, query):
            branch, target, iid, head, merge = (
                query.get(name, [""])[0] for name in ("branch", "target", "iid", "head", "merge")
            )
            if not target or not (branch or (iid and head and merge)):
                raise ValueError("invalid request")
            if branch:
                return git.open_revisions(
                    branch,
                    target
                )
            return git.merged_revisions(
                iid,
                head,
                merge,
                target
            )

        def host_allowed(self):
            # Rejects any other host name: a third-party page pointing its domain to 127.0.0.1
            # (DNS rebinding) would otherwise read GitLab and Sonar with the workstation's tokens.
            if self.headers.get("Host", "").split(":")[0] in ("localhost", "127.0.0.1"):
                return True
            self.close_connection = True
            self.send_json(403, {"message": "host rejected"})
            return False

        def relay(
                self,
                service,
                url,
                headers
        ):
            kind = service.lower()

            def load():
                try:
                    response = upstream.get(
                        url,
                        {**headers, "Accept-Encoding": "gzip"}
                    )
                except (OSError, http.client.HTTPException):
                    stats.record(
                        kind,
                        "connection"
                    )
                    raise
                # Maintenance page: relayed as a 503, counted as such.
                stats.record(
                    kind,
                    "5xx" if is_html(response[2]) else http_error(response[0])
                )
                return response

            try:
                (status, body, upstream_headers), cached = relay_cache.get(
                    url,
                    load,
                    lambda response: response[0] == 200 and not is_html(response[2]),
                    # Sent by the Refresh button: it wants GitLab's state, not a kept response.
                    self.headers.get("Cache-Control") == "no-cache"
                )
            except (OSError, http.client.HTTPException) as error:
                self.send_json(
                    502,
                    {"message": f"relay failed: {error}"}
                )
                return
            if cached:
                stats.record(
                    kind + "-cache",
                    None
                )
                # GitLab's time in a kept response has aged: the page would infer a false clock
                # skew from it.
                upstream_headers = copy(upstream_headers)
                del upstream_headers["Date"]
            # Which the page could not read.
            if is_html(upstream_headers):
                self.send_json(
                    503,
                    {"message": f"{service} seems under maintenance: it returns a web page instead of "
                                f"answering the API (HTTP {status})"}
                )
                return
            self.send_body(
                status,
                body,
                upstream_headers
            )

        def send_body(
                self,
                status,
                body,
                upstream_headers
        ):
            self.send_response(status)
            self.send_header("Content-Type", upstream_headers.get("Content-Type", "application/json"))
            for name in FORWARDED_RESPONSE_HEADERS:
                if upstream_headers.get(name) is not None:
                    self.send_header(name, upstream_headers[name])
            # Upstream server time, under another name: send_response has just written this server's
            # Date, i.e. the PC time, whose skew is precisely what the page looks for.
            if upstream_headers.get("Date") is not None:
                self.send_header("X-Upstream-Date", upstream_headers["Date"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_json(
                self,
                status,
                payload
        ):
            self.send_body(status, json.dumps(payload).encode(), {"Content-Type": "application/json"})

        @staticmethod
        def read_static(path):
            return (STATIC_DIR / path.lstrip("/")).read_bytes()

        def send_file(
                self,
                path,
                body,
                immutable
        ):
            """Page file, with its ETag: a browser that already has this content gets an empty 304."""
            etag = f'"{front_version_tag(body)}"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", {**PAGES, **STATIC_FILES}[path])
            self.send_header("ETag", etag)
            if immutable:
                self.send_header("Cache-Control", IMMUTABLE_CACHE_CONTROL)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(
                self,
                fmt,
                *args
        ):
            if not settings["quiet"]:
                super().log_message(fmt, *args)

    return Handler


def is_html(upstream_headers):
    """An API never answers in HTML: it is the maintenance or error page of an unavailable
    server."""
    return upstream_headers.get("Content-Type", "").startswith("text/html")


def discussion_request(payload):
    """(iid, JSON body for GitLab) of a diff discussion request, None if it is invalid.

    Only the expected fields get through, with the expected type: the page cannot make GitLab write
    anything other than a line comment on a MR of the tracked project.
    """
    if not isinstance(payload, dict):
        return None
    iid, body, position = payload.get("iid"), payload.get("body"), payload.get("position")
    if not is_positive(iid):
        return None
    if not isinstance(body, str) or not body.strip() or not isinstance(position, dict):
        return None
    if not all(is_sha(position.get(name)) for name in ("base_sha", "start_sha", "head_sha")):
        return None
    if not all(isinstance(position.get(name), str) and position[name] for name in ("old_path", "new_path")):
        return None
    lines = {name: position.get(name) for name in ("old_line", "new_line")}
    if not all(line is None or is_positive(line) for line in lines.values()):
        return None
    if lines == {"old_line": None, "new_line": None}:
        return None
    clean = {
        "position_type": "text",
        **{name: position[name] for name in ("base_sha", "start_sha", "head_sha", "old_path", "new_path")},
        **{name: line for name, line in lines.items() if line is not None}
    }
    line_range = position.get("line_range")
    if line_range is not None:
        ends = [line_range.get(end) if isinstance(line_range, dict) else None for end in ("start", "end")]
        if not all(range_end(end) for end in ends):
            return None
        clean["line_range"] = {name: range_end(end) for name, end in zip(("start", "end"), ends)}
    return iid, json.dumps({"body": body, "position": clean}).encode()


def reply_request(payload):
    """(iid, discussion, JSON body for GitLab) of a reply to a thread, None if it is invalid."""
    target = discussion_target(payload)
    body = payload.get("body") if target else None
    if not isinstance(body, str) or not body.strip():
        return None
    return *target, json.dumps({"body": body}).encode()


def resolve_request(payload):
    """(iid, discussion, JSON body for GitLab) of a request to resolve or reopen a thread, None if it
    is invalid."""
    target = discussion_target(payload)
    resolved = payload.get("resolved") if target else None
    if not isinstance(resolved, bool):
        return None
    return *target, json.dumps({"resolved": resolved}).encode()


def discussion_target(payload):
    """(iid, discussion) of a MR thread, None if the request does not designate it unambiguously: a
    GitLab thread id is a SHA, nothing else can get into the API path."""
    if not isinstance(payload, dict):
        return None
    iid, discussion = payload.get("iid"), payload.get("discussion")
    if not is_positive(iid) or not is_sha(discussion):
        return None
    return iid, discussion


def is_positive(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def is_sha(value):
    return isinstance(value, str) and len(value) in (40, 64) and all(c in "0123456789abcdef" for c in value)


def range_end(end):
    """An end of line_range reduced to its fields, None if it is invalid."""
    if not isinstance(end, dict) or end.get("type") not in ("old", "new"):
        return None
    line_code = end.get("line_code")
    if not isinstance(line_code, str) or len(line_code) > 200:
        return None
    lines = {name: end.get(name) for name in ("old_line", "new_line")}
    if not all(line is None or is_positive(line) for line in lines.values()):
        return None
    return {"line_code": line_code, "type": end["type"], **{n: v for n, v in lines.items() if v is not None}}


def require_unless_disabled(
        parser,
        args,
        switch,
        names
):
    """A tracked indicator requires all its options; --no-<indicator> declares that it does not exist."""
    if getattr(args, switch):
        return
    missing = [name for name in names if not getattr(args, name)]
    if missing:
        options = ", ".join("--" + name.replace("_", "-") for name in missing)
        parser.error(f"{options} required, or --{switch.replace('_', '-')} if the project does not have this indicator")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--sonar-host", help="Sonar server URL, such as https://sonarqube.example.com")
    parser.add_argument("--sonar-project", help="Sonar project key")
    parser.add_argument("--no-sonar", action="store_true", help="project without Sonar analysis: columns and indicators hidden")
    parser.add_argument("--gitlab-host", required=True, help="GitLab server URL, such as https://gitlab.example.com")
    parser.add_argument("--gitlab-project", required=True, help="project path, not encoded")
    parser.add_argument("--gitlab-token-host", help="host name of the token in the glab configuration (default: the one of --gitlab-host)")
    parser.add_argument("--glab-config", default=DEFAULT_GLAB_CONFIG)
    parser.add_argument("--sonar-job", help="name of the CI job that runs the Sonar analysis")
    parser.add_argument("--pit-job", help="name of the CI job that posts the mutation note")
    parser.add_argument("--pit-marker", help="beginning of the mutation note posted on the MR")
    parser.add_argument("--no-pit", action="store_true", help="project without mutation testing: column and indicators hidden")
    parser.add_argument("--pipeline-branch", required=True, help="branch whose latest pipeline is shown below the MR table")
    parser.add_argument("--target-branch", help="target branch filtered when the page opens (default: all)")
    parser.add_argument(
        "--repo-dir",
        type=Path,
        required=True,
        help="local git clone of the tracked project, where the AI button's sessions open and where git actions run"
    )
    parser.add_argument(
        "--launch-in",
        action="append",
        help=f"where the AI button can open its sessions, once per target, offered in this order: {', '.join(LAUNCH_TARGETS)} (default: auto, every target found)"
    )
    parser.add_argument(
        "--git-fetch-interval",
        type=int,
        default=DEFAULT_GIT_FETCH_INTERVAL_S,
        help=f"seconds between two automatic git fetches of the local git clone, 0 for none (default: {DEFAULT_GIT_FETCH_INTERVAL_S})"
    )
    parser.add_argument("--quiet", action="store_true", help="do not log each request")
    args = parser.parse_args()
    require_unless_disabled(
        parser,
        args,
        "no_sonar",
        ("sonar_host", "sonar_project", "sonar_job")
    )
    require_unless_disabled(
        parser,
        args,
        "no_pit",
        ("pit_job", "pit_marker")
    )

    sonar_token = os.environ.get("SONAR_TOKEN")
    try:
        launch_targets = choose_launch_targets(args.launch_in, args.repo_dir)
    except LaunchTargetError as error:
        parser.error(f"--launch-in: {error}")
    stats = RequestStats(TTL_S)
    git = GitActions(
        args.repo_dir,
        args.git_fetch_interval,
        lambda failed: stats.record("git", "git" if failed else None)
    )
    if not sonar_token and not args.no_sonar:
        print("⚠️  SONAR_TOKEN missing: Sonar badges will stay grey.")
    settings = {
        "gitlab_host": args.gitlab_host,
        "gitlab_token": gitlab_token(args.glab_config, args.gitlab_token_host or urlsplit(args.gitlab_host).hostname),
        "sonar_host": args.sonar_host,
        "sonar_token": sonar_token,
        "quiet": args.quiet,
        "public": {
            "gitlabWeb": args.gitlab_host,
            "gitlabProject": args.gitlab_project,
            "sonarWeb": args.sonar_host,
            "sonarProject": args.sonar_project,
            "sonarTracked": not args.no_sonar,
            "sonarEnabled": not args.no_sonar and bool(sonar_token),
            "sonarJob": args.sonar_job,
            "pitTracked": not args.no_pit,
            "pitJob": args.pit_job,
            "pitMarker": args.pit_marker,
            "pipelineBranch": args.pipeline_branch,
            "targetBranch": args.target_branch,
            "launchTargets": [{"id": target.id, "name": target.name} for target in launch_targets],
            "gitFetchIntervalS": args.git_fetch_interval,
        },
    }
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(
            settings,
            launch_targets,
            git,
            AiActions(args.repo_dir),
            stats,
            AvatarColors(AVATAR_COLORS_PATH)
        )
    )
    git.start_periodic_fetch()
    print(f"MisteR Dashboard, the Merge Requests dashboard: http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
