"""Actions git sur le clone local du projet suivi : fetch, et ouverture d'une branche dans une visionneuse.

Tant que le fetch automatique est activé, il tourne aussi tout seul à intervalle régulier : les branches
distantes restent à jour même sans page ouverte, et le restent pendant une coupure de GitLab — on peut
alors relire et committer sur origin/<branche>, puis pousser à son retour.

Le fetch se fait dans le worktree principal, retrouvé depuis n'importe quel worktree du clone ; la
visionneuse s'ouvre dans le worktree où la branche de la MR est extraite s'il y en a un, sinon dans le
principal.
"""
import os
import shlex
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

FETCH_TIMEOUT_S = 60
# Jamais d'invite d'identifiants : sans terminal pour y répondre, git attendrait jusqu'au délai.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


class GitError(Exception):
    pass


class GitActions:

    def __init__(
            self,
            repo_root,
            viewer,
            terminal,
            fetch_interval_s
    ):
        self._repo_root = repo_root
        self._viewer = viewer
        self._terminal = terminal
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
            viewer,
            terminal,
            fetch_interval_s
    ):
        """terminal, vide pour une visionneuse graphique, ouvre celle qui s'utilise dans un terminal."""
        common_dir = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        viewer_args = resolve(shlex.split(viewer))
        terminal_args = shlex.split(terminal)
        # Visionneuse ou terminal absent du poste : le bouton n'est pas proposé.
        if terminal_args and not resolve(terminal_args):
            viewer_args = None
        return cls(
            Path(common_dir).parent,
            viewer_args,
            terminal_args,
            fetch_interval_s
        )

    @property
    def viewer_name(self):
        return Path(self._viewer[0]).name if self._viewer else None

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

    def view(
            self,
            branch,
            target
    ):
        """Ouvre la visionneuse sur la branche de la MR, rapportée à sa branche cible, sans l'attendre."""
        if not self._viewer:
            raise GitError("visionneuse introuvable sur ce poste")
        for name in (branch, target):
            if self._git(["check-ref-format", "--branch", name]).returncode != 0:
                raise GitError(f"nom de branche invalide : {name}")
        # Le terminal Windows découpe sa ligne de commande sur « ; » : une branche qui en contient
        # pourrait y glisser une commande à lui.
        if self._terminal and any(";" in name for name in (branch, target)):
            raise GitError("nom de branche non pris en charge par le terminal : « ; »")
        # Branche poussée depuis le dernier fetch : on va la chercher, elle seule.
        missing = [name for name in (branch, target) if not self._has_remote_branch(name)]
        if missing:
            try:
                completed = self._git(["fetch", "origin", *missing], timeout=FETCH_TIMEOUT_S)
            except subprocess.TimeoutExpired as error:
                raise GitError(f"aucune réponse de git fetch en {FETCH_TIMEOUT_S} s") from error
            if completed.returncode != 0:
                raise GitError(last_line(completed.stderr) or "branche introuvable sur origin")
        repo = self._worktree_of(branch)
        values = {"branch": branch, "target": target, "repo": repo, "distro": os.environ.get("WSL_DISTRO_NAME", "")}
        command = [arg.format(**values) for arg in [*self._terminal, *self._viewer]]
        try:
            subprocess.Popen(
                command,
                cwd=repo,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except OSError as error:
            raise GitError(str(error)) from error
        return {"command": shlex.join(command)}

    def _worktree_of(self, branch):
        """Worktree où la branche est extraite : on peut y corriger et pousser sans rien déplacer."""
        listing = self._git(["worktree", "list", "--porcelain"]).stdout
        for block in listing.split("\n\n"):
            fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
            if fields.get("branch") == f"refs/heads/{branch}":
                return fields["worktree"]
        return str(self._repo_root)

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


# Dossiers d'installation par utilisateur (go install, pipx…), que le PATH d'un shell non interactif omet.
USER_BIN_DIRS = [Path.home() / "go" / "bin", Path.home() / ".local" / "bin"]


def resolve(args):
    """Programme en chemin absolu : le terminal qui l'ouvre n'a pas forcément le même PATH."""
    search_path = os.pathsep.join([os.environ.get("PATH", ""), *map(str, USER_BIN_DIRS)])
    program = shutil.which(os.path.expanduser(args[0]), path=search_path) if args else None
    return [program, *args[1:]] if program else None


def last_line(text):
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""
