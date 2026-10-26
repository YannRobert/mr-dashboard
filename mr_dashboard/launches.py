"""What every launch of a coding agent shares, whatever opens its tab (see orca_launcher.py): the prompt and the
agent's settings written to files, the command that starts the agent, and how far the start has got.

The prompt goes through a file: a long multiline text would not survive the quoting of a command line (the
Windows one, through WSL, least of all). The tab reads it, and the Claude Code session deletes it once
started, through a SessionStart hook brought by its own settings (sibling file, passed with --settings); a
file never deleted (shell or claude failing at startup) is purged on the next launch, once past this age. A
marker file, which the tab's shell deletes first, tells a shell that never started (WSL unreachable, say)
from a claude that did not start.
"""
import json
import re
import secrets
import shlex
import time
from pathlib import Path

import agents

PROMPT_MAX_CHARS = 20_000
PROMPT_DIR = Path.home() / ".cache" / "mr-dashboard"
PROMPT_MAX_AGE_S = 24 * 3600
# Identifier of a launch: the name of its prompt file, without extension.
LAUNCH_ID = re.compile(r"MR\d+-[0-9a-f]{8}")


class LaunchError(Exception):

    def __init__(
            self,
            message,
            unconfirmed=False
    ):
        super().__init__(message)
        # The tab may have opened all the same: the page then waits for the agent to start.
        self.unconfirmed = unconfirmed


class Launch:
    """The files of one launch, written by prepare(). Files are never deleted here on error: the tab may have
    been created anyway, and its shell would then read them too late. Without the prompt, the agent does not start
    at all rather than start with no instructions."""

    def __init__(
            self,
            prompt_file,
            settings_file,
            shell_file,
            model,
            effort,
            agent=None
    ):
        self.prompt_file = prompt_file
        self.settings_file = settings_file
        self.shell_file = shell_file
        self._model = model
        self._effort = effort
        self._agent = agent

    @property
    def id(self):
        return self.prompt_file.stem

    def shell_command(self):
        """The POSIX command line the tab's shell runs: it marks the shell as started, then starts the agent with
        the prompt, provided the prompt is still there. Claude Code deletes the prompt once started; another
        agent has it read and deleted by the shell just before it starts, into a variable whose name no shell
        reserves (zsh's prompt is its PS1)."""
        if self._agent is not None and self._agent.id != "claude":
            agent = agents.command(self._agent, self._agent.options(self._model, self._effort))
            # The prompt is only taken once the agent is found: otherwise it stays, and the page says the agent did
            # not start.
            return (f"rm -f '{self.shell_file}'; [ -f '{self.prompt_file}' ] && command -v {shlex.quote(self._agent.program)} >/dev/null "
                    f"&& {{ mr_dashboard_prompt=\"$(cat '{self.prompt_file}')\"; "
                    f"rm -f '{self.prompt_file}' '{self.settings_file}'; {agent} \"$mr_dashboard_prompt\"; }}")
        model_option = f"--model {shlex.quote(self._model)} " if self._model else ""
        effort_option = f"--effort {shlex.quote(self._effort)} " if self._effort else ""
        return (f"rm -f '{self.shell_file}'; [ -f '{self.prompt_file}' ] && claude --settings '{self.settings_file}' "
                f"{model_option}{effort_option}\"$(cat '{self.prompt_file}')\"")

    def result(self, worktree, confirmed):
        """What the page receives: the tab's folder, whether its opening was confirmed, and the launch to follow."""
        return {"worktree": str(worktree), "confirmed": confirmed, "launch": self.id}


def prepare(
        iid,
        prompt,
        model=None,
        effort=None,
        agent=None
):
    """Writes the files of a launch. Without model or effort, the agent uses those of its configuration; without
    agent, Claude Code."""
    if not prompt.strip() or len(prompt) > PROMPT_MAX_CHARS:
        raise LaunchError("prompt empty or too long")
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in PROMPT_DIR.glob("MR*"):
        if time.time() - stale.stat().st_mtime > PROMPT_MAX_AGE_S:
            stale.unlink(missing_ok=True)
    prompt_file = PROMPT_DIR / f"MR{iid}-{secrets.token_hex(4)}.md"
    # A prompt starting with - or @ would be read as an option, or a file for Pi: a line break before it avoids that.
    if prompt[:1] in ("-", "@"):
        prompt = "\n" + prompt
    prompt_file.write_text(prompt, encoding="utf-8")
    prompt_file.chmod(0o600)
    settings_file = prompt_file.with_suffix(".settings.json")
    cleanup = f"rm -f {shlex.quote(str(prompt_file))} {shlex.quote(str(settings_file))}"
    settings = {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": cleanup}]}]}}
    settings_file.write_text(json.dumps(settings), encoding="utf-8")
    settings_file.chmod(0o600)
    shell_file = prompt_file.with_suffix(".shell")
    shell_file.touch(mode=0o600)
    return Launch(
        prompt_file,
        settings_file,
        shell_file,
        model,
        effort,
        agent
    )


def progress(launch):
    """{shell, agent}: true once the tab's shell, then the launch's agent, have started, each deleting its file (the
    marker, then the prompt, through Claude Code's SessionStart hook or the shell just before another agent
    starts). The tab's creation, even confirmed, guarantees neither."""
    if not LAUNCH_ID.fullmatch(launch):
        raise LaunchError("unknown launch")
    agent = not (PROMPT_DIR / f"{launch}.md").exists()
    return {"shell": agent or not (PROMPT_DIR / f"{launch}.shell").exists(), "agent": agent}
