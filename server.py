#!/usr/bin/env python3
"""MisteR Dashboard : le dashboard des Merge Requests.

Tableau de bord local des MR ouvertes, avec les signaux CI (pipeline, PIT, Sonar) en pastilles.

La page (index.html) ne parle qu'à ce serveur, qui relaie deux préfixes :
    /gitlab/<chemin>  →  <gitlab>/api/v4/<chemin>   (token glab, en-tête PRIVATE-TOKEN)
    /sonar/<chemin>   →  <sonar>/api/<chemin>       (SONAR_TOKEN, en-tête Bearer)

Le relais est nécessaire pour Sonar, qui ne renvoie aucun en-tête CORS : un navigateur ne peut pas
l'interroger directement. Il sert aussi à garder les deux tokens hors du navigateur. Seul GET est
relayé, et le serveur n'écoute que sur 127.0.0.1.

Seule écriture : POST /orca/fix ouvre dans Orca une session Claude Code avec le prompt de correction
d'une MR (cf. orca_launcher.py), quand le serveur tourne dans WSL et qu'Orca est installé.

Usage :
    python3 scripts/mr-dashboard/server.py            # puis http://localhost:8765
    python3 scripts/mr-dashboard/server.py --port 9100

Prérequis (les mêmes que scripts/mr-ci-signals.py) :
    SONAR_TOKEN dans l'environnement — sans lui, les pastilles Sonar restent grises.
    ~/.config/glab-cli/config.yml authentifié contre gitlab.example.com.
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
from pathlib import Path
from urllib.parse import unquote, urlsplit

from orca_launcher import OrcaError, OrcaLauncher

DEFAULT_PORT = 8765
DEFAULT_SONAR_HOST = "https://sonarqube.example.com"
DEFAULT_SONAR_PROJECT = "group-project"
DEFAULT_GITLAB_HOST = "https://gitlab.example.com"
DEFAULT_GITLAB_PROJECT = "group/project"
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
                path,
                headers
            )
        except (ConnectionError, http.client.HTTPException, ssl.SSLError):
            if not reused:
                raise
            return self._send(
                target,
                self._connect(target),
                path,
                headers
            )

    def _send(
            self,
            target,
            connection,
            path,
            headers
    ):
        try:
            connection.request(
                "GET",
                path,
                headers=headers
            )
            response = connection.getresponse()
            body = response.read()
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
        return response.status, body, response.headers

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
        orca
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
            elif self.path.startswith("/gitlab/"):
                self.relay(
                    settings["gitlab_host"] + "/api/v4/" + self.path[len("/gitlab/"):],
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
            if self.path != "/orca/fix":
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
                payload = json.loads(self.rfile.read(length))
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--sonar-host", default=DEFAULT_SONAR_HOST)
    parser.add_argument("--sonar-project", default=DEFAULT_SONAR_PROJECT)
    parser.add_argument("--gitlab-host", default=DEFAULT_GITLAB_HOST)
    parser.add_argument("--gitlab-project", default=DEFAULT_GITLAB_PROJECT, help="chemin du projet, non encodé")
    parser.add_argument("--gitlab-token-host", default=DEFAULT_GITLAB_TOKEN_HOST)
    parser.add_argument("--glab-config", default=DEFAULT_GLAB_CONFIG)
    parser.add_argument("--quiet", action="store_true", help="ne pas journaliser chaque requête")
    args = parser.parse_args()

    sonar_token = os.environ.get("SONAR_TOKEN")
    orca = OrcaLauncher.detect(STATIC_DIR)
    if not sonar_token:
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
            "sonarEnabled": bool(sonar_token),
            "orcaEnabled": orca is not None,
        },
    }
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(
            settings,
            orca
        )
    )
    print(f"MisteR Dashboard, le dashboard des Merge Requests : http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
