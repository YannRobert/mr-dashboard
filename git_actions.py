"""Actions git sur le clone local du projet suivi : fetch, et ouverture d'une MR dans une visionneuse.

Tant que le fetch automatique est activé, il tourne aussi tout seul à intervalle régulier : les branches
distantes restent à jour même sans page ouverte, et le restent pendant une coupure de GitLab — on peut
alors relire et committer sur origin/<branche>, puis pousser à son retour.

Le fetch se fait dans le worktree principal, retrouvé depuis n'importe quel worktree du clone. Les
visionneuses qui comparent origin/<cible> et origin/<branche> y tournent aussi ; celles qui montrent la
branche extraite s'ouvrent dans le worktree où elle l'est s'il y en a un, sinon dans son worktree de
revue, <clone>-MR<iid> à côté du principal, détaché sur origin/<branche> — jamais par un checkout dans
le principal, qui porte le travail en cours.
"""
import os
import shlex
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

FETCH_TIMEOUT_S = 60
# Jamais d'invite d'identifiants : sans terminal pour y répondre, git attendrait jusqu'au délai.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


class GitError(Exception):
    pass


class Viewer(NamedTuple):
    command: str
    # S'utilise dans un terminal, ouvert par la commande terminal de GitActions.
    terminal: bool
    # Montre la branche extraite plutôt que de comparer des références : ouverte dans son worktree.
    worktree: bool


# {branch} et {target} : branches source et cible de la MR. Le programme de la commande doit être
# présent sur le poste pour que son bouton soit proposé.
VIEWERS = {
    # Les fichiers modifiés par la MR depuis le point où elle part de sa cible, un par un.
    "meld": Viewer("git difftool --dir-diff --no-prompt --tool=meld origin/{target}...origin/{branch}", False, False),
    "tig": Viewer("tig origin/{target}..origin/{branch}", True, False),
    # Le diff cumulé de la MR, lu par tig : la liste des fichiers en tête mène au diff de chacun. La
    # plage arrive en argument du shell, jamais dans son script.
    "tig diff": Viewer("sh -c 'git diff --stat -p \"$1\" | tig' tig-diff origin/{target}...origin/{branch}", True, False),
    "lazygit": Viewer("lazygit log", True, True),
    "gitk": Viewer("gitk --boundary origin/{target}..origin/{branch}", False, False),
}
REQUIRED_PROGRAMS = {"meld": "meld", "tig diff": "tig"}


class GitActions:

    def __init__(
            self,
            repo_root,
            viewers,
            terminal,
            fetch_interval_s
    ):
        self._repo_root = repo_root
        self._viewers = viewers
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
            viewer_names,
            terminal,
            fetch_interval_s
    ):
        """viewer_names : visionneuses de VIEWERS proposées, dans l'ordre des boutons ; terminal : celui
        qui ouvre les visionneuses en mode texte, None si aucun n'est présent."""
        common_dir = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        unknown = [name for name in viewer_names if name not in VIEWERS]
        if unknown:
            raise ValueError(f"visionneuse inconnue : {', '.join(unknown)} (connues : {', '.join(VIEWERS)})")
        terminal_args = resolve(shlex.split(terminal or ""))
        viewers = {}
        # Visionneuse, ou terminal qu'il lui faut, absent du poste : son bouton n'est pas proposé.
        for name in viewer_names:
            viewer = VIEWERS[name]
            args = resolve(shlex.split(viewer.command))
            required = REQUIRED_PROGRAMS.get(name)
            if not args or (required and not resolve([required])) or (viewer.terminal and not terminal_args):
                continue
            viewers[name] = (viewer, args)
        return cls(
            Path(common_dir).parent,
            viewers,
            terminal_args or [],
            fetch_interval_s
        )

    @property
    def viewer_names(self):
        return list(self._viewers)

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
            viewer_name,
            iid,
            branch,
            target
    ):
        """Ouvre la visionneuse sur la branche de la MR, rapportée à sa branche cible, sans l'attendre."""
        if viewer_name not in self._viewers:
            raise GitError(f"visionneuse {viewer_name} introuvable sur ce poste")
        viewer, viewer_args = self._viewers[viewer_name]
        terminal = self._terminal if viewer.terminal else []
        for name in (branch, target):
            if self._git(["check-ref-format", "--branch", name]).returncode != 0:
                raise GitError(f"nom de branche invalide : {name}")
        # Le terminal Windows découpe sa ligne de commande sur « ; » : une branche qui en contient
        # pourrait y glisser une commande à lui.
        if terminal and Path(terminal[0]).name == "wt.exe" and any(";" in name for name in (branch, target)):
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
        repo = self._worktree_of(branch) or self._review_worktree(
            iid,
            branch
        ) if viewer.worktree else str(self._repo_root)
        values = {"branch": branch, "target": target, "repo": repo, "distro": os.environ.get("WSL_DISTRO_NAME", "")}
        command = [arg.format(**values) for arg in [*terminal, *viewer_args]]
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
        return None

    def _review_worktree(
            self,
            iid,
            branch
    ):
        """Worktree de revue de la MR, créé au besoin, et amené sur le dernier commit poussé tant qu'il
        est détaché et sans modification : on n'y déplace ni une branche, ni un travail en cours."""
        path = self._repo_root.parent / f"{self._repo_root.name}-MR{iid}"
        remote = f"refs/remotes/origin/{branch}"
        listing = self._git(["worktree", "list", "--porcelain"]).stdout
        if f"worktree {path}\n" not in listing + "\n":
            if path.exists():
                raise GitError(f"{path} existe déjà sans être un worktree de ce dépôt")
            completed = self._git(["worktree", "add", "--detach", str(path), remote], timeout=FETCH_TIMEOUT_S)
            if completed.returncode != 0:
                raise GitError(last_line(completed.stderr) or "création du worktree de revue impossible")
            return str(path)
        detached = self._git(["-C", str(path), "symbolic-ref", "--quiet", "HEAD"]).returncode != 0
        clean = not self._git(["-C", str(path), "status", "--porcelain"]).stdout.strip()
        if detached and clean:
            self._git(["-C", str(path), "checkout", "--quiet", "--detach", remote])
        return str(path)

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
