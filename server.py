#!/usr/bin/env python3
"""MisteR Dashboard : le dashboard des Merge Requests.

Tableau de bord local des MR ouvertes, avec les signaux CI (pipeline, PIT, Sonar) en pastilles.

La page (index.html) ne parle qu'à ce serveur, qui relaie deux préfixes :
    /gitlab/<chemin>  →  <gitlab>/api/v4/<chemin>   (token glab, en-tête PRIVATE-TOKEN)
    /sonar/<chemin>   →  <sonar>/api/<chemin>       (SONAR_TOKEN, en-tête Bearer)
    /graphql?query=…  →  <gitlab>/api/graphql?…     (token glab ; en GET, GitLab refuse les mutations)

Le relais est nécessaire pour Sonar, qui ne renvoie aucun en-tête CORS : un navigateur ne peut pas
l'interroger directement. Il sert aussi à garder les deux tokens hors du navigateur. Seul GET est
relayé, et le serveur n'écoute que sur 127.0.0.1 : les seules écritures dans GitLab sont les actions
/gitlab/… ci-dessous, qui valident leur requête avant de la transmettre.

Actions locales, en POST :
    /orca/fix   ouvre dans Orca une session Claude Code avec le prompt de correction d'une MR
                (cf. orca_launcher.py), quand le serveur tourne dans WSL et qu'Orca est installé
    /git/fetch  git fetch du clone local, qui tourne aussi tout seul toutes les --git-fetch-interval
                secondes ; GET /git/status en donne le dernier résultat (cf. git_actions.py)
    /git/auto   active ou suspend le fetch automatique : {"enabled": true|false}
    /gitlab/discussion  ouvre une discussion sur une ou plusieurs lignes du diff d'une MR du projet
                suivi : {"iid", "body", "position"}, position au format de l'API GitLab
    /gitlab/reply       répond à un fil d'une MR du projet suivi : {"iid", "discussion", "body"}
    /gitlab/resolve     résout un fil, ou le rouvre : {"iid", "discussion", "resolved": true|false}
    /git/diff   GET ?branch=&target= : diff d'une MR depuis le point où elle part de sa cible, affiché
                par diff.html ; ?iid=&head=&merge=&target= pour une MR mergée, retrouvée par ses commits ;
                &first=&last= pour ce qu'ont apporté ensemble ses commits de first à last
    /git/commits GET, mêmes paramètres : commits de la MR, du plus ancien au plus récent

Usage — d'ordinaire via scripts/mr-dashboard/start.sh, qui lit ces options dans un profil
(scripts/mr-dashboard/profiles/<nom>.conf) :
    python3 scripts/mr-dashboard/server.py --gitlab-project <groupe/projet> --pipeline-branch <branche> \
        --sonar-project <clé> --sonar-job <job> --pit-job <job> --pit-marker <marqueur> \
        --repo-dir <clone local du projet> --git-fetch-interval 300 --port 8766
    python3 scripts/mr-dashboard/server.py --gitlab-project <groupe/projet> --pipeline-branch main \
        --no-sonar --no-pit   # projet sans analyse Sonar ni mutation testing

Aucun défaut ne désigne un projet : une option oubliée arrête le serveur au lieu de lui faire suivre
un autre dépôt que prévu.

Prérequis (les mêmes que scripts/mr-ci-signals.py) :
    SONAR_TOKEN dans l'environnement — sans lui, les pastilles Sonar restent grises.
    ~/.config/glab-cli/config.yml authentifié contre gitlab.example.com.
"""
import argparse
import base64
import http.client
import importlib.util
import json
import os
import shlex
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from git_actions import GitActions, GitError
from orca_launcher import OrcaError, OrcaLauncher

DEFAULT_PORT = 8765
DEFAULT_GIT_FETCH_INTERVAL_S = 300
DEFAULT_SONAR_HOST = "https://sonarqube.example.com"
DEFAULT_GITLAB_HOST = "https://gitlab.example.com"
DEFAULT_GITLAB_TOKEN_HOST = "gitlab.example.com"
DEFAULT_GLAB_CONFIG = os.path.expanduser("~/.config/glab-cli/config.yml")
# Content-Encoding : les réponses gzip sont relayées telles quelles, le navigateur les décompresse.
FORWARDED_RESPONSE_HEADERS = ("Content-Encoding", "X-Total", "X-Total-Pages", "X-Next-Page", "X-Page", "X-Per-Page")
UPSTREAM_TIMEOUT_S = 30
# Une connexion inactive plus longtemps est fermée plutôt que réutilisée : le proxy ou le serveur l'a
# probablement déjà coupée, et l'essayer coûterait un aller-retour pour rien.
UPSTREAM_IDLE_S = 30
# La page charge 4 MR en parallèle, jusqu'à 3 requêtes chacune.
UPSTREAM_MAX_IDLE_PER_HOST = 12
STATIC_DIR = Path(__file__).resolve().parent
# Bibliothèques servies depuis le dépôt plutôt qu'un CDN : la page de diff marche aussi sans réseau.
STATIC_FILES = {
    "/vendor/diff2html/diff2html-ui-slim.min.js": "text/javascript; charset=utf-8",
    "/vendor/diff2html/diff2html.min.css": "text/css; charset=utf-8",
    "/notes.js": "text/javascript; charset=utf-8",
    "/notes.css": "text/css; charset=utf-8",
    "/tabs.js": "text/javascript; charset=utf-8",
    "/avatars.js": "text/javascript; charset=utf-8",
    "/dates.js": "text/javascript; charset=utf-8",
    "/avatars.css": "text/css; charset=utf-8",
}
SIGNALS_SCRIPT = STATIC_DIR.parent / "mr-ci-signals.py"
REPO_ROOT = STATIC_DIR.parent.parent
# Exigé sur le POST : un en-tête non standard impose au navigateur un preflight CORS, que ce serveur
# ne satisfait jamais — une page tierce ne peut donc pas déclencher l'action.
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
    raise RuntimeError(f"aucun token trouvé pour {target_host} dans {config_path}")


class UpstreamPool:
    """Connexions gardées ouvertes par hôte amont.

    Via un proxy HTTPS, ouvrir une connexion (CONNECT + poignée de main TLS) coûte ~500 ms :
    davantage que la requête elle-même. Une actualisation en enchaîne des dizaines ; les réutiliser
    divise leur durée par ~4. Proxy lu dans l'environnement (https_proxy / no_proxy), comme urllib.
    """

    def __init__(self):
        self._idle = {}
        self._lock = threading.Lock()

    def get(
            self,
            url,
            headers
    ):
        """GET, et renvoie (statut, corps, en-têtes) ; une connexion réutilisée que l'amont a fermée
        entre-temps est remplacée une fois, la requête étant idempotente."""
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
        """Requête qui écrit (POST, PUT), et renvoie (statut, corps, en-têtes) ; toujours sur une
        connexion neuve, sans nouvel essai : une requête qui écrit ne se rejoue pas à l'aveugle."""
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
        orca,
        git
):
    upstream = UpstreamPool()

    class Handler(BaseHTTPRequestHandler):

        # Connexion gardée entre deux requêtes du navigateur ; chaque réponse porte son Content-Length.
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if not self.host_allowed():
                return
            if self.path in ("/", "/index.html") or self.path.startswith("/?"):
                self.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            elif self.path == "/config":
                self.send_json(200, settings["public"])
            elif self.path.startswith("/diff.html"):
                self.send_file(STATIC_DIR / "diff.html", "text/html; charset=utf-8")
            elif self.path.startswith("/comments.html"):
                self.send_file(STATIC_DIR / "comments.html", "text/html; charset=utf-8")
            elif self.path in STATIC_FILES:
                self.send_file(STATIC_DIR / self.path.lstrip("/"), STATIC_FILES[self.path])
            elif self.path == "/git/status":
                self.send_json(200, git.status())
            elif self.path.startswith("/git/diff?"):
                self.git_diff(parse_qs(urlsplit(self.path).query))
            elif self.path.startswith("/git/commits?"):
                self.git_commits(parse_qs(urlsplit(self.path).query))
            elif self.path.startswith("/gitlab/"):
                self.relay(
                    settings["gitlab_host"] + "/api/v4/" + self.path[len("/gitlab/"):],
                    {"PRIVATE-TOKEN": settings["gitlab_token"]}
                )
            elif self.path.startswith("/graphql?"):
                self.relay(
                    settings["gitlab_host"] + "/api" + self.path,
                    {"PRIVATE-TOKEN": settings["gitlab_token"]}
                )
            elif self.path.startswith("/sonar/"):
                if not settings["sonar_token"]:
                    self.send_json(503, {"message": "SONAR_TOKEN absent de l'environnement du serveur"})
                    return
                self.relay(
                    settings["sonar_host"] + "/api/" + self.path[len("/sonar/"):],
                    {"Authorization": "Bearer " + settings["sonar_token"]}
                )
            else:
                self.send_json(404, {"message": "introuvable"})

        def do_POST(self):
            if not self.host_allowed():
                return
            actions = {
                "/orca/fix": self.orca_fix,
                "/git/fetch": self.git_fetch,
                "/git/auto": self.git_auto,
                "/gitlab/discussion": self.gitlab_discussion,
                "/gitlab/reply": self.gitlab_reply,
                "/gitlab/resolve": self.gitlab_resolve
            }
            action = actions.get(self.path)
            if not action:
                self.close_connection = True
                self.send_json(404, {"message": "introuvable"})
                return
            origins = {f"http://{host}:{self.server.server_port}" for host in ("localhost", "127.0.0.1")}
            if self.headers.get(ACTION_HEADER) != "1" or self.headers.get("Origin") not in origins:
                self.close_connection = True
                self.send_json(403, {"message": "origine refusée"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_POST_BYTES:
                self.close_connection = True
                self.send_json(413, {"message": "requête trop volumineuse"})
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self.send_json(400, {"message": "requête invalide"})
                return
            action(payload)

        def orca_fix(self, payload):
            try:
                iid = int(payload["iid"])
                prompt = str(payload["prompt"])
            except (ValueError, KeyError, TypeError):
                self.send_json(400, {"message": "requête invalide"})
                return
            if not orca:
                self.send_json(503, {"message": "Orca introuvable, ou serveur lancé hors WSL"})
                return
            try:
                result = orca.launch(
                    iid,
                    prompt
                )
            except OrcaError as error:
                self.send_json(502, {"message": str(error)})
                return
            self.send_json(200, result)

        def git_fetch(self, payload):
            signature = payload.get("signature") if isinstance(payload, dict) else None
            if signature is None:
                git.fetch()
            elif isinstance(signature, str):
                git.fetch_if_changed(signature)
            else:
                self.send_json(400, {"message": "requête invalide"})
                return
            self.send_json(200, git.status())

        def git_auto(self, payload):
            enabled = payload.get("enabled") if isinstance(payload, dict) else None
            if not isinstance(enabled, bool):
                self.send_json(400, {"message": "requête invalide"})
                return
            git.set_auto(enabled)
            self.send_json(200, git.status())

        def gitlab_discussion(self, payload):
            request = discussion_request(payload)
            if not request:
                self.send_json(400, {"message": "requête invalide"})
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
                self.send_json(400, {"message": "requête invalide"})
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
                self.send_json(400, {"message": "requête invalide"})
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
            """Transmet à GitLab, pour le projet suivi, une écriture déjà validée ; path relatif au projet."""
            project = quote(settings["public"]["gitlabProject"], safe="")
            try:
                status, content, upstream_headers = upstream.write(
                    method,
                    f"{settings['gitlab_host']}/api/v4/projects/{project}/{path}",
                    {"PRIVATE-TOKEN": settings["gitlab_token"], "Content-Type": "application/json"},
                    body
                )
            except (OSError, http.client.HTTPException) as error:
                self.send_json(
                    502,
                    {"message": f"relay failed: {error}"}
                )
                return
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
                    last
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

        # MR ouverte par ses branches, mergée par ses commits.
        def mr_revisions(self, query):
            branch, target, iid, head, merge = (
                query.get(name, [""])[0] for name in ("branch", "target", "iid", "head", "merge")
            )
            if not target or not (branch or (iid and head and merge)):
                raise ValueError("requête invalide")
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
            # Refuse tout autre nom d'hôte : une page tierce qui ferait pointer son domaine sur
            # 127.0.0.1 (DNS rebinding) lirait sinon GitLab et Sonar avec les tokens du poste.
            if self.headers.get("Host", "").split(":")[0] in ("localhost", "127.0.0.1"):
                return True
            self.close_connection = True
            self.send_json(403, {"message": "hôte refusé"})
            return False

        def relay(
                self,
                url,
                headers
        ):
            try:
                status, body, upstream_headers = upstream.get(
                    url,
                    {**headers, "Accept-Encoding": "gzip"}
                )
            except (OSError, http.client.HTTPException) as error:
                self.send_json(
                    502,
                    {"message": f"relay failed: {error}"}
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
            # Heure du serveur amont, sous un autre nom : send_response vient d'écrire le Date de ce
            # serveur-ci, c'est-à-dire l'heure du PC, dont la page cherche justement l'écart.
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

        def send_file(
                self,
                path,
                content_type
        ):
            self.send_body(200, path.read_bytes(), {"Content-Type": content_type})

        def log_message(
                self,
                fmt,
                *args
        ):
            if not settings["quiet"]:
                super().log_message(fmt, *args)

    return Handler


def discussion_request(payload):
    """(iid, corps JSON pour GitLab) d'une demande de discussion sur le diff, None si elle est invalide.

    Seuls les champs attendus passent, au type attendu : la page ne peut rien faire écrire d'autre à
    GitLab qu'un commentaire de ligne sur une MR du projet suivi.
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
    """(iid, discussion, corps JSON pour GitLab) d'une réponse à un fil, None si elle est invalide."""
    target = discussion_target(payload)
    body = payload.get("body") if target else None
    if not isinstance(body, str) or not body.strip():
        return None
    return *target, json.dumps({"body": body}).encode()


def resolve_request(payload):
    """(iid, discussion, corps JSON pour GitLab) d'une demande de résoudre ou rouvrir un fil, None si
    elle est invalide."""
    target = discussion_target(payload)
    resolved = payload.get("resolved") if target else None
    if not isinstance(resolved, bool):
        return None
    return *target, json.dumps({"resolved": resolved}).encode()


def discussion_target(payload):
    """(iid, discussion) d'un fil d'une MR, None si la demande ne le désigne pas sans ambiguïté :
    l'identifiant d'un fil GitLab est un SHA, rien d'autre ne peut entrer dans le chemin de l'API."""
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
    """Une extrémité de line_range réduite à ses champs, None si elle est invalide."""
    if not isinstance(end, dict) or end.get("type") not in ("old", "new"):
        return None
    line_code = end.get("line_code")
    if not isinstance(line_code, str) or len(line_code) > 200:
        return None
    lines = {name: end.get(name) for name in ("old_line", "new_line")}
    if not all(line is None or is_positive(line) for line in lines.values()):
        return None
    return {"line_code": line_code, "type": end["type"], **{n: v for n, v in lines.items() if v is not None}}


def signals_command(args):
    """Commande de vérification citée par le prompt de correction, exécutée depuis --repo-dir.

    Depuis ce dépôt : chemin relatif, et seulement les options qui s'écartent des défauts du script,
    pour un prompt lisible. Depuis un autre clone, qui n'a pas ce script : son chemin absolu.
    """
    defaults = signals_script_defaults()
    options = [
        ("--gitlab-host", args.gitlab_host, defaults.DEFAULT_GITLAB_HOST),
        ("--gitlab-project", quote(args.gitlab_project, safe=""), defaults.DEFAULT_GITLAB_PROJECT),
    ]
    if args.no_sonar:
        options.append(("--no-sonar", None, None))
    else:
        options += [
            ("--sonar-host", args.sonar_host, defaults.DEFAULT_SONAR_HOST),
            ("--sonar-project", args.sonar_project, defaults.DEFAULT_SONAR_PROJECT),
        ]
    if args.no_pit:
        options.append(("--no-pit", None, None))
    else:
        options.append(("--pit-marker", args.pit_marker, defaults.MUTATION_MARKER))
    in_this_repo = args.repo_dir.resolve().is_relative_to(REPO_ROOT)
    command = ["python3", "scripts/mr-ci-signals.py" if in_this_repo else shlex.quote(str(SIGNALS_SCRIPT))]
    for name, value, default in options:
        if value is None:
            command.append(name)
        elif not in_this_repo or value != default:
            command += [name, shlex.quote(value)]
    return " ".join(command)


def signals_script_defaults():
    spec = importlib.util.spec_from_file_location("mr_ci_signals", SIGNALS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require_unless_disabled(
        parser,
        args,
        switch,
        names
):
    """Un indicateur suivi exige toutes ses options ; --no-<indicateur> déclare qu'il n'existe pas."""
    if getattr(args, switch):
        return
    missing = [name for name in names if not getattr(args, name)]
    if missing:
        options = ", ".join("--" + name.replace("_", "-") for name in missing)
        parser.error(f"{options} requis, ou --{switch.replace('_', '-')} si le projet n'a pas cet indicateur")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--sonar-host", default=DEFAULT_SONAR_HOST)
    parser.add_argument("--sonar-project", help="clé du projet Sonar")
    parser.add_argument("--no-sonar", action="store_true", help="projet sans analyse Sonar : colonnes et indicateurs masqués")
    parser.add_argument("--gitlab-host", default=DEFAULT_GITLAB_HOST)
    parser.add_argument("--gitlab-project", required=True, help="chemin du projet, non encodé")
    parser.add_argument("--gitlab-token-host", default=DEFAULT_GITLAB_TOKEN_HOST)
    parser.add_argument("--glab-config", default=DEFAULT_GLAB_CONFIG)
    parser.add_argument("--sonar-job", help="nom du job CI qui lance l'analyse Sonar")
    parser.add_argument("--pit-job", help="nom du job CI qui publie la note de mutation")
    parser.add_argument("--pit-marker", help="début de la note de mutation publiée sur la MR")
    parser.add_argument("--no-pit", action="store_true", help="projet sans mutation testing : colonne et indicateurs masqués")
    parser.add_argument("--pipeline-branch", required=True, help="branche dont le dernier pipeline s'affiche sous le tableau des MR")
    parser.add_argument("--target-branch", help="branche cible filtrée à l'ouverture de la page (défaut : --pipeline-branch)")
    parser.add_argument(
        "--repo-dir",
        type=Path,
        default=STATIC_DIR,
        help="clone local du projet suivi, où Orca ouvre la session de correction et où tournent les actions git (défaut : ce dépôt)"
    )
    parser.add_argument(
        "--git-fetch-interval",
        type=int,
        default=DEFAULT_GIT_FETCH_INTERVAL_S,
        help=f"secondes entre deux git fetch automatiques du clone local, 0 pour aucun (défaut : {DEFAULT_GIT_FETCH_INTERVAL_S})"
    )
    parser.add_argument("--quiet", action="store_true", help="ne pas journaliser chaque requête")
    args = parser.parse_args()
    require_unless_disabled(
        parser,
        args,
        "no_sonar",
        ("sonar_project", "sonar_job")
    )
    require_unless_disabled(
        parser,
        args,
        "no_pit",
        ("pit_job", "pit_marker")
    )

    sonar_token = os.environ.get("SONAR_TOKEN")
    orca = OrcaLauncher.detect(args.repo_dir)
    git = GitActions.detect(
        args.repo_dir,
        args.git_fetch_interval
    )
    if not sonar_token and not args.no_sonar:
        print("⚠️  SONAR_TOKEN absent : les pastilles Sonar resteront grises.")
    settings = {
        "gitlab_host": args.gitlab_host,
        "gitlab_token": gitlab_token(args.glab_config, args.gitlab_token_host),
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
            "targetBranch": args.target_branch or args.pipeline_branch,
            "signalsCommand": signals_command(args),
            "orcaEnabled": orca is not None,
            "gitFetchIntervalS": args.git_fetch_interval,
        },
    }
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(
            settings,
            orca,
            git
        )
    )
    git.start_periodic_fetch()
    print(f"MisteR Dashboard, le dashboard des Merge Requests : http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
