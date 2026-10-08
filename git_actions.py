"""Actions git sur le clone local du projet suivi : fetch et diff d'une MR, ouverte ou mergée, et ce
que le clone sait d'une MR ouverte quand GitLab ne répond pas.

Tant que le fetch automatique est activé, il tourne aussi tout seul à intervalle régulier : les branches
distantes restent à jour même sans page ouverte, et restent en place pendant une coupure de GitLab, même
quand il sert une page de maintenance à la place du dépôt — on peut alors relire et committer sur
origin/<branche>, puis pousser à son retour.

Fetch et diff se font dans le worktree principal, retrouvé depuis n'importe quel worktree du clone,
sans jamais rien y extraire : il porte le travail en cours.
"""
import os
import re
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
SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


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
        # État des MR qui a déclenché le dernier fetch sur changement, partagé par tous les onglets.
        self._repo_signature = None
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

    def fetch_if_changed(self, signature):
        """Fetch si l'état des MR vu par la page diffère du dernier signalé : une page rechargée, ou un
        autre onglet qui voit le même état, ne relance pas de fetch."""
        with self._state_lock:
            if signature == self._repo_signature:
                return self._last
            self._repo_signature = signature
        return self.fetch()

    def _run_fetch(self):
        at = datetime.now(timezone.utc).isoformat()
        try:
            # Une page de maintenance servie en 200 à la place du dépôt passe pour un dépôt sans branche :
            # git ne signale rien, et --prune effacerait alors toutes les branches origin/*. Sans branche
            # annoncée, pas de fetch.
            advertised = self._git(["ls-remote", "--heads", "origin"], timeout=FETCH_TIMEOUT_S)
            if advertised.returncode != 0:
                return {"at": at, "ok": False, "message": last_line(advertised.stderr) or f"code {advertised.returncode}"}
            if not advertised.stdout.strip():
                return {"at": at, "ok": False, "message": "origin n'annonce aucune branche (maintenance ?) : "
                                                          "fetch annulé pour garder les branches origin/*"}
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

    def open_revisions(
            self,
            branch,
            target
    ):
        """Bornes d'une MR ouverte : sa cible et sa branche, telles que sur origin."""
        self._check_branch_names(
            branch,
            target
        )
        self._fetch_missing(
            branch,
            target
        )
        return f"refs/remotes/origin/{target}", f"refs/remotes/origin/{branch}"

    def merged_revisions(
            self,
            iid,
            head,
            merge_commit,
            target
    ):
        """Bornes d'une MR mergée, branche source supprimée ou non : la cible juste avant le merge et
        le dernier commit de la MR. Tout se lit dans l'historique, aucun worktree ni branche locale."""
        if not iid.isdigit() or not SHA.fullmatch(head) or not SHA.fullmatch(merge_commit):
            raise GitError("MR ou commit invalide")
        self._check_branch_names(target)
        # Branche source supprimée et MR squashée : GitLab garde sa tête sous refs/merge-requests.
        if not self._has_commit(head):
            self._fetch(f"refs/merge-requests/{iid}/head")
        if not self._has_commit(merge_commit):
            self._fetch(target)
        return f"{merge_commit}^1", head

    def diff(
            self,
            revisions,
            first=None,
            last=None
    ):
        """Sans plage, le diff de la MR depuis le point où elle part de sa cible, celui de l'onglet
        Changes de GitLab ; avec, ce qu'ont apporté ensemble ses commits de first à last."""
        base, head = revisions
        if first is None and last is None:
            return self._diff_range(f"{base}...{head}")
        shas = [commit["sha"] for commit in self.commits(revisions)]
        if first not in shas or last not in shas or shas.index(first) > shas.index(last):
            raise GitError("plage de commits hors de la MR")
        return self._diff_range(f"{first}^1", last)

    def commits(self, revisions):
        """Commits de la MR, du plus ancien au plus récent, sans ceux de la cible qu'elle a mergée."""
        base, head = revisions
        completed = self._git(
            [
                "log", "--first-parent", "--reverse", "--format=%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%s",
                f"{base}..{head}",
            ],
            timeout=DIFF_TIMEOUT_S
        )
        if completed.returncode != 0:
            raise GitError(last_line(completed.stderr) or "git log en échec")
        commits = []
        for line in completed.stdout.splitlines():
            sha, parents, author, email, date, title = line.split("\x1f", 5)
            commits.append({
                "sha": sha,
                "merge": len(parents.split()) > 1,
                "author": author,
                "email": email,
                "date": date,
                "title": title,
            })
        return commits

    def branch_signals(
            self,
            branch,
            target
    ):
        """Nombre de commits, date du dernier et retard sur la cible d'une MR ouverte, d'après les branches
        origin/* du dernier fetch, sans réseau : de quoi les donner pendant une coupure de GitLab. Le retard
        court, comme dans la page, depuis le commit de la cible qui suit le dernier commit commun."""
        self._check_branch_names(
            branch,
            target
        )
        head, base = f"refs/remotes/origin/{branch}", f"refs/remotes/origin/{target}"
        for ref, name in ((head, branch), (base, target)):
            if self._git(["rev-parse", "--verify", "--quiet", ref]).returncode != 0:
                raise GitError(f"branche absente du clone local : {name}")
        common = self._git_output(["merge-base", head, base])
        count = int(self._git_output(["rev-list", "--count", f"{base}..{head}"]))
        commit_date = self._git_output(["log", "-1", "--format=%cI", head])
        behind = int(self._git_output(["rev-list", "--count", f"{head}..{base}"]))
        since = next_short = None
        if behind:
            successors = [
                line.split("\x1f")
                for line in self._git_output(
                    ["log", "--first-parent", "--reverse", "--format=%P%x1f%h%x1f%cI", f"{common}..{base}"]
                ).splitlines()
            ]
            successor = next((s for s in successors if s[0].split()[0] == common), successors[0] if successors else None)
            if successor:
                next_short, since = successor[1], successor[2]
        return {
            "count": count,
            "commitDate": commit_date,
            "behind": {"count": behind, "since": since, "base": self._git_output(["rev-parse", "--short", common]), "next": next_short},
            "fetchedAt": self._last_fetch_at(),
        }

    def _last_fetch_at(self):
        """Date du dernier fetch qui a abouti, même lancé hors du serveur : celle de FETCH_HEAD."""
        try:
            mtime = (self._repo_root / ".git" / "FETCH_HEAD").stat().st_mtime
        except OSError:
            return None
        return datetime.fromtimestamp(mtime, timezone.utc).isoformat()

    def _git_output(self, args):
        completed = self._git(args)
        if completed.returncode != 0:
            raise GitError(last_line(completed.stderr) or f"git {args[0]} en échec")
        return completed.stdout.strip()

    def _diff_range(self, *revisions):
        try:
            completed = subprocess.run(
                [
                    "git", "-C", str(self._repo_root), "diff", "--no-color", "--no-ext-diff", "--find-renames",
                    *revisions,
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
            *names
    ):
        for name in names:
            if self._git(["check-ref-format", "--branch", name]).returncode != 0:
                raise GitError(f"nom de branche invalide : {name}")

    def _fetch_missing(
            self,
            branch,
            target
    ):
        """Branche poussée depuis le dernier fetch : on va la chercher, elle seule."""
        missing = [name for name in (branch, target) if not self._has_remote_branch(name)]
        if missing:
            self._fetch(*missing)

    def _fetch(self, *refspecs):
        try:
            completed = self._git(["fetch", "origin", *refspecs], timeout=FETCH_TIMEOUT_S)
        except subprocess.TimeoutExpired as error:
            raise GitError(f"aucune réponse de git fetch en {FETCH_TIMEOUT_S} s") from error
        if completed.returncode != 0:
            raise GitError(last_line(completed.stderr) or "introuvable sur origin")

    def _has_remote_branch(self, name):
        return self._git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}"]).returncode == 0

    def _has_commit(self, sha):
        return self._git(["cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0

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
