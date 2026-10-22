"""Catalogue des actions du bouton AI d'une MR, propre au projet suivi.

Le projet le décrit dans CATALOG_PATH, fichier commité à la racine de son clone et relu à chaque
demande : un prompt modifié s'essaie sans redémarrer le serveur ni commiter. Chaque action :

    [[action]]
    id = "…"            identifiant, unique dans le fichier
    label = "…"         libellé du choix dans le dialogue
    tab = "… !{iid}"    titre de l'onglet Orca, {iid} remplacé par le numéro de la MR (défaut : label)
    prompt = "…"        prompt, dont la page remplace les variables (cf. README)
    when = "to-fix"     facultatif : action proposée seulement quand la MR a quelque chose à corriger
    model = "sonnet"    facultatif : modèle présélectionné pour la session Orca, alias ou version précise
    effort = "low"      facultatif : niveau d'effort présélectionné pour la session Orca, parmi EFFORTS
    voice = "…"         facultatif : réplique anglaise que la voix du dashboard ajoute à « Yes sir! » quand
                        l'action est lancée dans Orca

Sans fichier, le catalogue se réduit à la correction, avec le prompt calculé par la page. Avec ou sans,
il finit par l'action libre, au prompt vide, à rédiger dans le dialogue.
"""
import subprocess
import tomllib
from pathlib import Path

import claude_models
from claude_models import ALIASES, EFFORTS, SAFE_ID

CATALOG_PATH = Path(".mr-dashboard") / "ai-actions.toml"
DEFAULT_ACTIONS = [
    {"id": "fix", "label": None, "tab": "Fix MR !{iid}", "prompt": "{fix_context}", "when": "to-fix", "model": None, "effort": None, "voice": None},
]
# Prompt rédigé dans le dialogue : un modèle au choix, sans taper la commande claude dans Orca.
FREE_ACTION = {"id": "free", "label": None, "tab": "Claude MR !{iid}", "prompt": "", "when": None, "model": None, "effort": None, "voice": None}
WHEN_VALUES = {"to-fix"}
MAX_TAB_CHARS = 80
MAX_VOICE_CHARS = 80


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
        """{"source", "actions", "models", "efforts"} : source vaut None pour le catalogue par défaut, faute de
        fichier ; models, ceux que propose Claude Code (cf. claude_models.py)."""
        try:
            content = self._path.read_bytes()
        except FileNotFoundError:
            return {
                "source": None,
                "actions": [*DEFAULT_ACTIONS, FREE_ACTION],
                "models": claude_models.choices(),
                "efforts": EFFORTS,
            }
        except OSError as error:
            raise AiActionsError(f"{CATALOG_PATH} illisible : {error}") from error
        try:
            document = tomllib.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise AiActionsError(f"{CATALOG_PATH} invalide : {error}") from error
        return {
            "source": str(CATALOG_PATH),
            "actions": [*self._actions(document), FREE_ACTION],
            "models": claude_models.choices(),
            "efforts": EFFORTS,
        }

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
        if FREE_ACTION["id"] in ids:
            raise AiActionsError(f"{CATALOG_PATH} : id {FREE_ACTION['id']} réservé à l'action libre")
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
        unknown = set(entry) - {"id", "label", "tab", "prompt", "when", "model", "effort", "voice"}
        if unknown:
            raise AiActionsError(f"{where} : clé inconnue : {', '.join(sorted(unknown))}")
        when = entry.get("when")
        if when is not None and when not in WHEN_VALUES:
            raise AiActionsError(f"{where} : when vaut {', '.join(sorted(WHEN_VALUES))} ou est absent")
        model = entry.get("model")
        # Une version que Claude Code ne propose plus laisse le dialogue sur le modèle par défaut.
        if model is not None and model not in ALIASES and not (isinstance(model, str) and SAFE_ID.match(model)):
            raise AiActionsError(f"{where} : model vaut {', '.join(ALIASES)}, une version claude-…, ou est absent")
        effort = entry.get("effort")
        if effort is not None and effort not in EFFORTS:
            raise AiActionsError(f"{where} : effort vaut {', '.join(EFFORTS)} ou est absent")
        tab = entry.get("tab", entry["label"])
        if not isinstance(tab, str) or "\n" in tab or len(tab) > MAX_TAB_CHARS:
            raise AiActionsError(f"{where} : tab doit tenir sur une ligne de {MAX_TAB_CHARS} caractères au plus")
        voice = entry.get("voice")
        if voice is not None and (not isinstance(voice, str) or "\n" in voice or len(voice) > MAX_VOICE_CHARS):
            raise AiActionsError(f"{where} : voice doit tenir sur une ligne de {MAX_VOICE_CHARS} caractères au plus")
        return {
            "id": entry["id"],
            "label": entry["label"],
            "tab": tab,
            "prompt": entry["prompt"],
            "when": when,
            "model": model,
            "effort": effort,
            "voice": voice,
        }
