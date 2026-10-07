"""Catalogue des actions du bouton AI d'une MR, propre au projet suivi.

Le projet le décrit dans CATALOG_PATH, fichier commité à la racine de son clone et relu à chaque
demande : un prompt modifié s'essaie sans redémarrer le serveur ni commiter. Chaque action :

    [[action]]
    id = "…"            identifiant, unique dans le fichier
    label = "…"         libellé du choix dans le dialogue
    tab = "… !{iid}"    titre de l'onglet Orca, {iid} remplacé par le numéro de la MR (défaut : label)
    prompt = "…"        prompt, dont la page remplace les variables (cf. README)
    when = "to-fix"     facultatif : action proposée seulement quand la MR a quelque chose à corriger

Sans fichier, le catalogue se réduit à la correction, avec le prompt calculé par la page.
"""
import subprocess
import tomllib
from pathlib import Path

CATALOG_PATH = Path(".mr-dashboard") / "ai-actions.toml"
DEFAULT_ACTIONS = [
    {"id": "fix", "label": None, "tab": "Fix MR !{iid}", "prompt": "{fix_context}", "when": "to-fix"},
]
WHEN_VALUES = {"to-fix"}
MAX_TAB_CHARS = 80


class AiActionsError(Exception):
    pass


class AiActions:

    def __init__(self, repo_root):
        self._path = repo_root / CATALOG_PATH

    @classmethod
    def detect(cls, repo_dir):
        """Le catalogue se lit dans le worktree principal du clone, comme Orca y ouvre ses sessions."""
        common_dir = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        return cls(Path(common_dir).parent)

    def catalog(self):
        """{"source", "actions"} : source vaut None pour le catalogue par défaut, faute de fichier."""
        try:
            content = self._path.read_bytes()
        except FileNotFoundError:
            return {"source": None, "actions": DEFAULT_ACTIONS}
        except OSError as error:
            raise AiActionsError(f"{CATALOG_PATH} illisible : {error}") from error
        try:
            document = tomllib.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise AiActionsError(f"{CATALOG_PATH} invalide : {error}") from error
        return {"source": str(CATALOG_PATH), "actions": self._actions(document)}

    def tab_title(
            self,
            action_id,
            iid
    ):
        action = next((a for a in self.catalog()["actions"] if a["id"] == action_id), None)
        if action is None:
            raise AiActionsError(f"action inconnue : {action_id}")
        return action["tab"].replace("{iid}", str(iid))

    def _actions(self, document):
        entries = document.get("action")
        if not isinstance(entries, list) or not entries:
            raise AiActionsError(f"{CATALOG_PATH} : aucune action [[action]]")
        actions = []
        for index, entry in enumerate(entries, start=1):
            actions.append(self._action(
                index,
                entry
            ))
        ids = [action["id"] for action in actions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise AiActionsError(f"{CATALOG_PATH} : id en double : {', '.join(duplicates)}")
        return actions

    def _action(
            self,
            index,
            entry
    ):
        where = f"{CATALOG_PATH}, action n°{index}"
        for key in ("id", "label", "prompt"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise AiActionsError(f"{where} : {key} manquant")
        unknown = set(entry) - {"id", "label", "tab", "prompt", "when"}
        if unknown:
            raise AiActionsError(f"{where} : clé inconnue : {', '.join(sorted(unknown))}")
        when = entry.get("when")
        if when is not None and when not in WHEN_VALUES:
            raise AiActionsError(f"{where} : when vaut {', '.join(sorted(WHEN_VALUES))} ou est absent")
        tab = entry.get("tab", entry["label"])
        if not isinstance(tab, str) or "\n" in tab or len(tab) > MAX_TAB_CHARS:
            raise AiActionsError(f"{where} : tab doit tenir sur une ligne de {MAX_TAB_CHARS} caractères au plus")
        return {"id": entry["id"], "label": entry["label"], "tab": tab, "prompt": entry["prompt"], "when": when}
