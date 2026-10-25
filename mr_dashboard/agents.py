"""The coding agents the AI button can start: Claude Code, Codex and Pi, those installed on the PATH.

Each agent has its command line, the models it offers and the effort levels each model accepts, as the dialog's
menus show them ({"id", "label", "alias", "version", "efforts", "recommended"}, as claude_models.choices gives
them, plus "provider" for an agent that groups its models by provider). An agent whose models cannot be listed offers none: its session then runs on the model of its own
configuration.
"""
import json
import re
import shlex
import shutil
import subprocess
import threading
import time

import claude_models

PI_THINKING = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
MODELS_TIMEOUT_S = 10
# How long a model list read from an agent's command is reused: models change seldom, and the agent refreshes its
# own catalogue. A failed reading is not kept, and a restart of the server reads again.
MODELS_CACHE_S = 24 * 3600
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
        self._lock = threading.Lock()
        self._models = None
        self._models_at = 0

    def installed(self):
        return shutil.which(self.program) is not None

    def _cached(self, read):
        """The model list read(), kept MODELS_CACHE_S; an empty reading is retried next time."""
        with self._lock:
            if self._models is None or time.time() - self._models_at > MODELS_CACHE_S:
                models = read()
                if not models:
                    return []
                self._models, self._models_at = models, time.time()
            return self._models

    def models(self):
        return []

    def efforts(self, model):
        """Levels the model accepts; without a model, those the agent offers for the model of its configuration."""
        return []

    def find(self, model_id):
        return next((model for model in self.models() if model["id"] == model_id), None)

    def options(self, model, effort):
        """The command line options of the model and the effort level, both already checked against the menus."""
        return []

    def describe(self):
        return {"id": self.id, "name": self.name, "models": self.models(), "efforts": list(self.efforts(None))}


class ClaudeCode(Agent):
    """Claude Code deletes the prompt file itself once started, through a SessionStart hook (see launches.py): the
    surest sign that it runs."""

    def __init__(self):
        super().__init__("claude", "Claude Code", "claude")

    def models(self):
        return claude_models.choices()

    def efforts(self, model):
        choice = self.find(model) if model else None
        return choice["efforts"] if choice else claude_models.EFFORTS

    def options(self, model, effort):
        return [*(["--model", model] if model else []), *(["--effort", effort] if effort else [])]


class Codex(Agent):
    """Codex exports its model catalogue with `codex debug models`: the models it lists (not those it hides), their
    reasoning levels and the default one, set with -c model_reasoning_effort."""

    def __init__(self):
        super().__init__("codex", "Codex", "codex")

    def models(self):
        return self._cached(self._read_models)

    @staticmethod
    def _read_models():
        try:
            result = subprocess.run(["codex", "debug", "models"], capture_output=True, text=True, encoding="utf-8",
                                    timeout=MODELS_TIMEOUT_S, check=False)
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

    def options(self, model, effort):
        return [*(["-m", model] if model else []), *(["-c", f"model_reasoning_effort={effort}"] if effort else [])]


class Pi(Agent):
    """Pi lists the models of the providers it is logged in to, with whether each thinks."""

    def __init__(self):
        super().__init__("pi", "Pi", "pi")

    def models(self):
        return self._cached(self._read_models)

    @staticmethod
    def _read_models():
        try:
            result = subprocess.run(
                ["pi", "--list-models"],
                capture_output=True,
                text=True,
                encoding="utf-8",
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

    def options(self, model, effort):
        return [*(["--model", model] if model else []), *(["--thinking", effort] if effort else [])]


AGENTS = (ClaudeCode(), Codex(), Pi())


def installed():
    return [agent for agent in AGENTS if agent.installed()]


def find(agent_id):
    """The installed agent with this id, or None."""
    return next((agent for agent in installed() if agent.id == agent_id), None)


def command(agent, options):
    """The agent's program and options, quoted for the shell."""
    return shlex.join([agent.program, *options])
