#!/usr/bin/env python3
"""Tableau de bord local des MR ouvertes, avec les signaux CI (pipeline, PIT, Sonar) en pastilles.

La page (index.html) ne parle qu'à ce serveur, qui relaie deux préfixes :
    /gitlab/<chemin>  →  <gitlab>/api/v4/<chemin>   (token glab, en-tête PRIVATE-TOKEN)
    /sonar/<chemin>   →  <sonar>/api/<chemin>       (SONAR_TOKEN, en-tête Bearer)

Le relais est nécessaire pour Sonar, qui ne renvoie aucun en-tête CORS : un navigateur ne peut pas
l'interroger directement. Il sert aussi à garder les deux tokens hors du navigateur. Seul GET est
relayé, et le serveur n'écoute que sur 127.0.0.1.

Usage :
    python3 scripts/mr-dashboard/server.py            # puis http://localhost:8765
    python3 scripts/mr-dashboard/server.py --port 9100

Prérequis (les mêmes que scripts/mr-ci-signals.py) :
    SONAR_TOKEN dans l'environnement — sans lui, les pastilles Sonar restent grises.
    ~/.config/glab-cli/config.yml authentifié contre gitlab.example.com.
"""
import argparse
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PORT = 8765
DEFAULT_SONAR_HOST = "https://sonarqube.example.com"
DEFAULT_SONAR_PROJECT = "group-project"
DEFAULT_GITLAB_HOST = "https://gitlab.example.com"
DEFAULT_GITLAB_PROJECT = "group/project"
DEFAULT_GITLAB_TOKEN_HOST = "gitlab.example.com"
DEFAULT_GLAB_CONFIG = os.path.expanduser("~/.config/glab-cli/config.yml")
FORWARDED_RESPONSE_HEADERS = ("X-Total", "X-Total-Pages", "X-Next-Page", "X-Page", "X-Per-Page")
STATIC_DIR = Path(__file__).resolve().parent


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


def make_handler(settings):

    class Handler(BaseHTTPRequestHandler):

        def do_GET(self):
            # Refuse tout autre nom d'hôte : une page tierce qui ferait pointer son domaine sur
            # 127.0.0.1 (DNS rebinding) lirait sinon GitLab et Sonar avec les tokens du poste.
            if self.headers.get("Host", "").split(":")[0] not in ("localhost", "127.0.0.1"):
                self.send_json(403, {"message": "hôte refusé"})
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

        def relay(
                self,
                url,
                headers
        ):
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    self.send_body(response.status, response.read(), response.headers)
            except urllib.error.HTTPError as error:
                self.send_body(error.code, error.read(), error.headers)
            except urllib.error.URLError as error:
                self.send_json(502, {"message": f"relay failed: {error.reason}"})

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
        },
    }
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(settings))
    print(f"Tableau de bord des MR : http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
