"""The coding agents the AI button can start: Claude Code, Codex and Pi, those installed on the PATH.

Each agent has its command line, the models it offers and the effort levels each model accepts, as the dialog's
menus show them ({"id", "label", "alias", "version", "efforts", "recommended"}, as claude_models.choices gives
them). An agent whose models cannot be listed offers none: its session then runs on the model of its own
configuration.
"""
import re
import shlex
import shutil
import subprocess

import claude_models

PI_THINKING = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
PI_MODELS_TIMEOUT_S = 10
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

    def installed(self):
        return shutil.which(self.program) is not None

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
    """Codex lists no models offline: its sessions run on the model of its configuration."""

    def __init__(self):
        super().__init__("codex", "Codex", "codex")


class Pi(Agent):
    """Pi lists the models of the providers it is logged in to, with whether each thinks."""

    def __init__(self):
        super().__init__("pi", "Pi", "pi")

    def models(self):
        try:
            result = subprocess.run(
                ["pi", "--list-models"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=PI_MODELS_TIMEOUT_S,
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
                models.append({"id": model_id, "label": f"{model} ({provider})", "alias": False, "version": None,
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
