"""Catalog of the actions behind a MR's AI button, specific to the tracked project.

The project describes it in CATALOG_PATH, a file committed at the root of the tracked repository (--repo-dir) and
reread on every request: an edited prompt can be tried without restarting the server or committing. Each action:

    [[action]]
    id = "…"            identifier, unique within the file
    label = "…"         label of the choice in the dialog
    tab = "… !{iid}"    title of the Orca tab, {iid} replaced by the MR number (default: label)
    prompt = "…"        prompt, whose variables the page replaces (see README)
    when = "to-fix"     optional: action offered only when the MR has something to fix
    model = "sonnet"    optional: model preselected for the Orca session, an alias or a specific version
    effort = "low"      optional: effort level preselected for the Orca session, one of EFFORTS
    voice = "…"         optional: English line the dashboard voice appends to "Yes sir!" when the action
                        is launched in Orca

Without the file, the catalog comes down to the fix action, with the prompt computed by the page. Either way,
it ends with the free action, with an empty prompt to write in the dialog.
"""
import tomllib
from pathlib import Path

import agents
import claude_models
from claude_models import ALIASES, EFFORTS, SAFE_ID

CATALOG_PATH = Path(".mr-dashboard") / "ai-actions.toml"
DEFAULT_ACTIONS = [
    {"id": "fix", "label": None, "tab": "Fix MR !{iid}", "prompt": "{fix_context}", "when": "to-fix", "model": None, "effort": None, "voice": None},
]
# Prompt written in the dialog: any model, without typing the claude command in Orca.
FREE_ACTION = {"id": "free", "label": None, "tab": "Claude MR !{iid}", "prompt": "", "when": None, "model": None, "effort": None, "voice": None}
WHEN_VALUES = {"to-fix"}
MAX_TAB_CHARS = 80
MAX_VOICE_CHARS = 80


class AiActionsError(Exception):
    pass


class AiActions:

    def __init__(self, repo_root):
        self._path = repo_root / CATALOG_PATH

    def catalog(self):
        """{"source", "actions", "agents"}: source is None for the default catalog, when there is no file; agents
        are those installed, with their models and effort levels (see agents.py)."""
        try:
            content = self._path.read_bytes()
        except FileNotFoundError:
            return {
                "source": None,
                "actions": [*DEFAULT_ACTIONS, FREE_ACTION],
                "agents": [agent.describe() for agent in agents.installed()],
            }
        except OSError as error:
            raise AiActionsError(f"{CATALOG_PATH} unreadable: {error}") from error
        try:
            document = tomllib.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise AiActionsError(f"{CATALOG_PATH} invalid: {error}") from error
        return {
            "source": str(CATALOG_PATH),
            "actions": [*self._actions(document), FREE_ACTION],
            "agents": [agent.describe() for agent in agents.installed()],
        }

    def tab_title(
            self,
            action_id,
            iid
    ):
        action = next((a for a in self.catalog()["actions"] if a["id"] == action_id), None)
        if action is None:
            raise AiActionsError(f"unknown action: {action_id}")
        return action["tab"].replace("{iid}", str(iid))

    def _actions(self, document):
        entries = document.get("action")
        if not isinstance(entries, list) or not entries:
            raise AiActionsError(f"{CATALOG_PATH}: no [[action]] entry")
        actions = []
        for index, entry in enumerate(entries, start=1):
            actions.append(self._action(
                index,
                entry
            ))
        ids = [action["id"] for action in actions]
        if FREE_ACTION["id"] in ids:
            raise AiActionsError(f"{CATALOG_PATH}: id {FREE_ACTION['id']} is reserved for the free action")
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise AiActionsError(f"{CATALOG_PATH}: duplicate id: {', '.join(duplicates)}")
        return actions

    def _action(
            self,
            index,
            entry
    ):
        where = f"{CATALOG_PATH}, action #{index}"
        for key in ("id", "label", "prompt"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise AiActionsError(f"{where}: {key} missing")
        unknown = set(entry) - {"id", "label", "tab", "prompt", "when", "model", "effort", "voice"}
        if unknown:
            raise AiActionsError(f"{where}: unknown key: {', '.join(sorted(unknown))}")
        when = entry.get("when")
        if when is not None and when not in WHEN_VALUES:
            raise AiActionsError(f"{where}: when must be {', '.join(sorted(WHEN_VALUES))} or absent")
        model = entry.get("model")
        # A version Claude Code no longer offers leaves the dialog on the default model.
        if model is not None and model not in ALIASES and not (isinstance(model, str) and SAFE_ID.match(model)):
            raise AiActionsError(f"{where}: model must be {', '.join(ALIASES)}, a claude-… version, or absent")
        effort = entry.get("effort")
        if effort is not None and effort not in EFFORTS:
            raise AiActionsError(f"{where}: effort must be {', '.join(EFFORTS)} or absent")
        tab = entry.get("tab", entry["label"])
        if not isinstance(tab, str) or "\n" in tab or len(tab) > MAX_TAB_CHARS:
            raise AiActionsError(f"{where}: tab must fit on one line of at most {MAX_TAB_CHARS} characters")
        voice = entry.get("voice")
        if voice is not None and (not isinstance(voice, str) or "\n" in voice or len(voice) > MAX_VOICE_CHARS):
            raise AiActionsError(f"{where}: voice must fit on one line of at most {MAX_VOICE_CHARS} characters")
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
