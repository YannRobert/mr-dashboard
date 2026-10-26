"""The coding agents the AI button can start: Claude Code, Codex and Pi, those installed on the PATH.

Each agent has its command line, the models it offers and the effort levels each model accepts, as the dialog's
menus show them ({"id", "label", "alias", "version", "efforts", "recommended"}, as claude_models.choices gives
them, plus "provider" for an agent that groups its models by provider). An agent whose models cannot be listed offers none: its session then runs on the model of its own
configuration.

The menus' default choice leaves the model and the effort level to the agent's configuration, which each agent
reads in its own files: the dialog names what they set, so that the default is no surprise. What only the agent's
code decides (Claude Code's model for the account, Codex's model when its configuration names none) stays unnamed.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import tomllib
from pathlib import Path

import claude_models

PI_THINKING = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
MODELS_TIMEOUT_S = 10
# Agents and their models are looked up in the background, at startup then every MODELS_REFRESH_S: models change
# seldom, and the dialog must open at once, on what the last lookup found.
MODELS_REFRESH_S = 3600
# Looking an agent up in the user's login shell, whose PATH may hold more than the server's (nvm, ~/.local/bin).
LOOKUP_TIMEOUT_S = 5
# A model of `codex debug models`, as `codex -m` takes it.
CODEX_MODEL = re.compile(r"^[A-Za-z0-9._-]+$")
# A model of `pi --list-models`: provider and model, as `pi --model provider/id` takes it.
PI_MODEL = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._:-]+$")


class Agent:

    def __init__(
            self,
            agent_id,
            name,
            program
    ):
        self.id = agent_id
        self.name = name
        self.program = program
        # The program's path, found by refresh(); None until then, or when it is not installed.
        self._path = None
        self._models = []

    def installed(self):
        """Whether the last refresh() found the program."""
        return self._path is not None

    def refresh(self):
        """Looks the program up, on the server's PATH or on that of the user's login shell, the one its tab runs (an
        agent installed through nvm or in ~/.local/bin is often only on the latter), then reads its models. Slow:
        run in the background only. A failed reading keeps the models of the previous one."""
        path = shutil.which(self.program) or self._in_login_shell()
        self._path = path
        models = self._read_models(path) if path else []
        if models or not path:
            self._models = models

    def _in_login_shell(self):
        """The program's path in the user's login shell, or None."""
        try:
            # Interactive too: nvm and the like set the PATH in ~/.zshrc or ~/.bashrc, which a login shell alone skips.
            result = subprocess.run([os.environ.get("SHELL") or "/bin/sh", "-l", "-i", "-c", f"command -v {shlex.quote(self.program)}"],
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=LOOKUP_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        lines = result.stdout.strip().splitlines()
        return lines[-1] if result.returncode == 0 and lines and lines[-1].startswith("/") else None

    @staticmethod
    def _read_models(path):
        """The models the program at path lists; [] when it lists none."""
        return []

    def models(self):
        return self._models

    def efforts(self, model):
        """Levels the model accepts; without a model, those the agent offers for the model of its configuration."""
        return []

    def defaults(self, folder):
        """{"model", "effort"}: what the agent's configuration sets for a session in the folder, None where it sets
        nothing."""
        return {"model": None, "effort": None}

    # Whether a model's recommended level is the one the agent takes when its configuration sets none.
    RECOMMENDED_IS_DEFAULT = False

    def find(self, model_id):
        return next((model for model in self.models() if model["id"] == model_id), None)

    # How the command line names the model and the effort level: arguments where {model} and {effort} are replaced.
    MODEL_OPTION = ()
    EFFORT_OPTION = ()

    def options(self, model, effort):
        """The command line options of the model and the effort level, both already checked against the menus."""
        return [*(part.format(model=model) for part in (self.MODEL_OPTION if model else ())),
                *(part.format(effort=effort) for part in (self.EFFORT_OPTION if effort else ()))]

    def describe(self, folder):
        """The agent as the dialog's menus and its command copy need it, with the defaults of a session in the
        folder."""
        return {"id": self.id, "name": self.name, "program": self.program, "models": self.models(),
                "efforts": list(self.efforts(None)), "modelOption": list(self.MODEL_OPTION),
                "effortOption": list(self.EFFORT_OPTION), "defaults": self.defaults(folder),
                "recommendedIsDefault": self.RECOMMENDED_IS_DEFAULT}


def _env(path):
    """The environment to run the program at path in: its folder first on the PATH, for the interpreter its shebang
    asks (node, next to pi under nvm) to be the one installed with it."""
    return {**os.environ, "PATH": os.pathsep.join([str(Path(path).parent), os.environ.get("PATH", "")])}


def _json(path):
    """The JSON object of a settings file, or {} when missing or unreadable."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _text(value):
    return value if isinstance(value, str) and value else None


class ClaudeCode(Agent):
    """Claude Code deletes the prompt file itself once started, through a SessionStart hook (see launches.py): the
    surest sign that it runs. Always offered, as before other agents came: if the tab's shell does not find it,
    the dialog says the agent did not start."""

    def __init__(self):
        super().__init__("claude", "Claude Code", "claude")

    def installed(self):
        return True

    def refresh(self):
        pass

    def models(self):
        return claude_models.choices()

    def efforts(self, model):
        choice = self.find(model) if model else None
        return choice["efforts"] if choice else claude_models.EFFORTS

    def defaults(self, folder):
        """The user's settings, then the project's, then the project's local ones, each overriding the previous,
        and the environment above all; each settings file may set the environment too."""
        model = effort = None
        for path in (Path.home() / ".claude" / "settings.json", Path(folder) / ".claude" / "settings.json",
                     Path(folder) / ".claude" / "settings.local.json"):
            settings = _json(path)
            env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
            model = _text(env.get("ANTHROPIC_MODEL")) or _text(settings.get("model")) or model
            effort = _text(env.get("CLAUDE_CODE_EFFORT_LEVEL")) or _text(settings.get("effortLevel")) or effort
        return {"model": _text(os.environ.get("ANTHROPIC_MODEL")) or model,
                "effort": _text(os.environ.get("CLAUDE_CODE_EFFORT_LEVEL")) or effort}

    MODEL_OPTION = ("--model", "{model}")
    EFFORT_OPTION = ("--effort", "{effort}")


class Codex(Agent):
    """Codex exports its model catalogue with `codex debug models`: the models it lists (not those it hides), their
    reasoning levels and the default one, set with -c model_reasoning_effort."""

    def __init__(self):
        super().__init__("codex", "Codex", "codex")

    @staticmethod
    def _read_models(path):
        try:
            result = subprocess.run([path, "debug", "models"], capture_output=True, text=True, encoding="utf-8",
                                    env=_env(path), timeout=MODELS_TIMEOUT_S, check=False)
            catalog = json.loads(result.stdout).get("models", [])
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
            return []
        models = []
        for model in catalog:
            slug = model.get("slug") if isinstance(model, dict) else None
            if not slug or not CODEX_MODEL.match(slug) or model.get("visibility") != "list":
                continue
            levels = [level.get("effort") if isinstance(level, dict) else level for level in model.get("supported_reasoning_levels") or []]
            models.append({"id": slug, "label": model.get("display_name") or slug, "alias": False, "version": None,
                           "efforts": [level for level in levels if isinstance(level, str) and CODEX_MODEL.match(level)],
                           "recommended": model.get("default_reasoning_level")})
        return models

    def efforts(self, model):
        """The model's levels; for the model of Codex's configuration, those every listed model accepts."""
        choice = self.find(model) if model else None
        if choice:
            return choice["efforts"]
        lists = [set(choice["efforts"]) for choice in self.models()]
        common = set.intersection(*lists) if lists else set()
        return [level for level in (self.models()[0]["efforts"] if lists else []) if level in common]

    def defaults(self, folder):
        """Its configuration file, and the profile it names, which overrides it."""
        try:
            config = tomllib.loads((Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return super().defaults(folder)
        profile = (config.get("profiles") or {}).get(config.get("profile")) if isinstance(config.get("profiles"), dict) else None
        layers = [config, profile if isinstance(profile, dict) else {}]
        pick = lambda key: next((_text(layer.get(key)) for layer in reversed(layers) if _text(layer.get(key))), None)
        return {"model": pick("model"), "effort": pick("model_reasoning_effort")}

    # A model's default_reasoning_level, from Codex's catalogue.
    RECOMMENDED_IS_DEFAULT = True

    MODEL_OPTION = ("-m", "{model}")
    EFFORT_OPTION = ("-c", "model_reasoning_effort={effort}")


class Pi(Agent):
    """Pi lists the models of the providers it is logged in to, with whether each thinks."""

    def __init__(self):
        super().__init__("pi", "Pi", "pi")

    @staticmethod
    def _read_models(path):
        try:
            result = subprocess.run(
                [path, "--list-models"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=_env(path),
                timeout=MODELS_TIMEOUT_S,
                check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        models = []
        for line in result.stdout.splitlines()[1:]:
            columns = line.split()
            if len(columns) < 5:
                continue
            provider, model, thinking = columns[0], columns[1], columns[4]
            model_id = f"{provider}/{model}"
            if PI_MODEL.match(model_id):
                models.append({"id": model_id, "label": model, "provider": provider, "alias": False, "version": None,
                               "efforts": list(PI_THINKING) if thinking == "yes" else [], "recommended": None})
        return models

    def efforts(self, model):
        choice = self.find(model) if model else None
        return choice["efforts"] if choice else PI_THINKING

    def defaults(self, folder):
        """Its global settings, then the project's, which override them."""
        model = effort = None
        for path in (Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent") / "settings.json",
                     Path(folder) / ".pi" / "settings.json"):
            settings = _json(path)
            provider, name = _text(settings.get("defaultProvider")), _text(settings.get("defaultModel"))
            if name:
                model = name if "/" in name or not provider else f"{provider}/{name}"
            effort = _text(settings.get("defaultThinkingLevel")) or effort
        return {"model": model, "effort": effort}

    MODEL_OPTION = ("--model", "{model}")
    EFFORT_OPTION = ("--thinking", "{effort}")


AGENTS = (ClaudeCode(), Codex(), Pi())


def refresh():
    for agent in AGENTS:
        agent.refresh()


def start_periodic_refresh():
    """Looks the agents and their models up now then every MODELS_REFRESH_S, in a background thread: until the first
    lookup ends, the dialog offers Claude Code only."""
    def loop():
        while True:
            refresh()
            time.sleep(MODELS_REFRESH_S)
    threading.Thread(target=loop, name="agents-refresh", daemon=True).start()


def installed():
    return [agent for agent in AGENTS if agent.installed()]


def find(agent_id):
    """The installed agent with this id, or None."""
    return next((agent for agent in installed() if agent.id == agent_id), None)


def command(agent, options):
    """The agent's program and options, quoted for the shell."""
    return shlex.join([agent.program, *options])
