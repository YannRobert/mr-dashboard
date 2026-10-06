"""Actions git sur le clone local du projet suivi : fetch et diff d'une MR.

Tant que le fetch automatique est activé, il tourne aussi tout seul à intervalle régulier : les branches
distantes restent à jour même sans page ouverte, et le restent pendant une coupure de GitLab — on peut
alors relire et committer sur origin/<branche>, puis pousser à son retour.

Fetch et diff se font dans le worktree principal, retrouvé depuis n'importe quel worktree du clone,
sans jamais rien y extraire : il porte le travail en cours.
"""
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

FETCH_TIMEOUT_S = 60
DIFF_TIMEOUT_S = 30
MAX_DIFF_BYTES = 5_000_000
# Jamais d'invite d'identifiants : sans terminal pour y répondre, git attendrait jusqu'au délai.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


class GitError(Exception):
    pass


class GitActions:

    def __init__(
            self,
            repo_root,
            fetch_interval_s
    ):
        self._repo_root = repo_root
        self._fetch_interval_s = fetch_interval_s
        self._fetch_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._fetches = 0
        self._running = False
        self._last = None
        self._last_success_at = None
        self._auto = True
        self._wake = threading.Event()
        # Échéance du prochain fetch automatique, en temps monotone : chaque fetch, d'où qu'il vienne,
        # la repousse d'un intervalle.
        self._next_due = 0.0
        self._next_at = None

    @classmethod
    def detect(
            cls,
            repo_dir,
            fetch_interval_s
    ):
        common_dir = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        return cls(
            Path(common_dir).parent,
            fetch_interval_s
        )

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
        """Réactivé, le fetch automatique part aussitôt, sans attendre la fin de l'intervalle."""
        with self._state_lock:
            self._auto = enabled
            if enabled:
                self._next_due = 0.0
        self._wake.set()

    def fetch(self):
        """Lance un fetch, ou attend celui en cours et en renvoie le résultat : deux demandes rapprochées
        n'en font qu'un."""
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

    def _run_fetch(self):
        at = datetime.now(timezone.utc).isoformat()
        try:
            completed = self._git(["fetch", "--prune", "origin"], timeout=FETCH_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {"at": at, "ok": False, "message": f"aucune réponse de git fetch en {FETCH_TIMEOUT_S} s"}
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

    def diff(
            self,
            branch,
            target
    ):
        """Diff de la MR depuis le point où elle part de sa cible, celui de l'onglet Changes de GitLab."""
        self._check_branch_names(
            branch,
            target
        )
        self._fetch_missing(
            branch,
            target
        )
        try:
            completed = subprocess.run(
                [
                    "git", "-C", str(self._repo_root), "diff", "--no-color", "--no-ext-diff", "--find-renames",
                    f"refs/remotes/origin/{target}...refs/remotes/origin/{branch}",
                ],
                capture_output=True,
                env=GIT_ENV,
                timeout=DIFF_TIMEOUT_S
            )
        except subprocess.TimeoutExpired as error:
            raise GitError(f"aucune réponse de git diff en {DIFF_TIMEOUT_S} s") from error
        if completed.returncode != 0:
            raise GitError(last_line(completed.stderr.decode(errors="replace")) or "git diff en échec")
        # Au-delà, le navigateur peinerait à l'afficher.
        if len(completed.stdout) > MAX_DIFF_BYTES:
            raise GitError(
                f"diff de {len(completed.stdout) // 1_000_000} Mo, au-delà des {MAX_DIFF_BYTES // 1_000_000} Mo "
                "affichables : le lire dans GitLab"
            )
        return completed.stdout.decode(errors="replace")

    def _check_branch_names(
            self,
            branch,
            target
    ):
        for name in (branch, target):
            if self._git(["check-ref-format", "--branch", name]).returncode != 0:
                raise GitError(f"nom de branche invalide : {name}")

    def _fetch_missing(
            self,
            branch,
            target
    ):
        """Branche poussée depuis le dernier fetch : on va la chercher, elle seule."""
        missing = [name for name in (branch, target) if not self._has_remote_branch(name)]
        if not missing:
            return
        try:
            completed = self._git(["fetch", "origin", *missing], timeout=FETCH_TIMEOUT_S)
        except subprocess.TimeoutExpired as error:
            raise GitError(f"aucune réponse de git fetch en {FETCH_TIMEOUT_S} s") from error
        if completed.returncode != 0:
            raise GitError(last_line(completed.stderr) or "branche introuvable sur origin")

    def _has_remote_branch(self, name):
        return self._git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}"]).returncode == 0

    def _git(
            self,
            args,
            timeout=10
    ):
        return subprocess.run(
            ["git", "-C", str(self._repo_root), *args],
            capture_output=True,
            text=True,
            env=GIT_ENV,
            timeout=timeout
        )


def last_line(text):
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""
