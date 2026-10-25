"""Opens in a terminal of the user's choice a Claude Code session in charge of an AI button action on a MR.

The terminal is named, never guessed: a preset of PRESETS, or a command template of the user's own. Either opens
a new tab (or window, for terminals without tabs) on the tracked repository (--repo-dir), running the user's
login shell, which starts the agent with the prompt and, once it exits, stays open as an ordinary shell.

A template is a command line where {dir} is the tracked repository, {title} the tab's title and {command} the
command line to run, given as a single argument: for instance "mlterm --title {title} -e sh -c {command}".
"""
import os
import shlex
import shutil
import subprocess

import launches
from launches import LaunchError

# How long a terminal command may take to fail: past it, the tab is taken as opened. Terminals that open a
# window run as long as it stays open, and those that hand the tab to a running instance return at once.
FAILURE_WAIT_S = 3
# Presets: (name shown on the button, command template). {argv} is the command to run as separate arguments,
# {command} the same as a single shell command line.
PRESETS = {
    "tmux": ("tmux", "tmux new-window -c {dir} -n {title} {command}"),
    "gnome-terminal": ("GNOME Terminal", "gnome-terminal --tab --working-directory={dir} -- {argv}"),
    "konsole": ("Konsole", "konsole --new-tab --workdir {dir} -e {argv}"),
    "terminator": ("Terminator", "terminator --new-tab --working-directory={dir} -x {argv}"),
    "wezterm": ("WezTerm", "wezterm cli spawn --cwd {dir} -- {argv}"),
    "kitty": ("kitty", "kitty @ launch --type=tab --cwd={dir} --tab-title={title} {argv}"),
    "windows-terminal": ("Windows Terminal", "wt.exe -w 0 new-tab --title {title} wsl.exe -d {distro} --cd {dir} -- {argv}"),
    "xterm": ("xterm", "xterm -T {title} -e {argv}"),
}


class TerminalLauncher:

    def __init__(
            self,
            name,
            template,
            repo_dir
    ):
        self.name = name
        self._template = shlex.split(template)
        self._repo_dir = repo_dir

    @classmethod
    def of(cls, spec, repo_dir):
        """The launcher of a preset name or of a template; ValueError when the preset's program is missing."""
        if spec in PRESETS:
            name, template = PRESETS[spec]
            program = shlex.split(template)[0]
            if not shutil.which(program):
                raise ValueError(f"{program} not found on the PATH")
            return cls(name, template, repo_dir)
        if "{command}" not in spec and "{argv}" not in spec:
            raise ValueError(f"unknown terminal: {spec} (a preset among {', '.join(PRESETS)}, or a template with {{command}})")
        return cls(shlex.split(spec)[0], spec, repo_dir)

    def unavailable(self):
        """Why the terminal cannot open a tab now, or None: tmux needs a running session; a terminal that opens its
        own window always can."""
        if self._template[:2] != ["tmux", "new-window"]:
            return None
        try:
            result = subprocess.run(["tmux", "has-session"], capture_output=True, timeout=FAILURE_WAIT_S, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return "not answering"
        return None if result.returncode == 0 else "no session"

    def launch(
            self,
            iid,
            title,
            prompt,
            model=None,
            effort=None,
            agent=None
    ):
        """Opens the tab and returns {worktree, confirmed, launch}."""
        launch = launches.prepare(
            iid,
            prompt,
            model,
            effort,
            agent
        )
        argv = self._command(title, launch.shell_command())
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
        except OSError as error:
            raise LaunchError(f"{self.name} unreachable: {error}") from error
        try:
            status = process.wait(timeout=FAILURE_WAIT_S)
        except subprocess.TimeoutExpired:
            process.stderr.close()
            return launch.result(self._repo_dir, confirmed=True)
        message = process.stderr.read().decode("utf-8", "replace").strip()
        process.stderr.close()
        if status != 0:
            raise LaunchError(f"{self.name}: {message or f'exit status {status}'}")
        return launch.result(self._repo_dir, confirmed=True)

    def _command(self, title, agent_command):
        """The terminal's command line: the user's login shell sets the tab's title, starts the agent, then
        stays open as an ordinary shell."""
        shell = os.environ.get("SHELL") or "/bin/sh"
        script = f"printf '\\033]0;%s\\007' {shlex.quote(title)}; {agent_command}; exec {shlex.quote(shell)} -l"
        argv = [shell, "-l", "-c", script]
        values = {
            "dir": str(self._repo_dir),
            "title": title,
            "command": shlex.join(argv),
            "distro": os.environ.get("WSL_DISTRO_NAME", ""),
        }
        command = []
        for part in self._template:
            if part == "{argv}":
                command.extend(argv)
            else:
                command.append(part.format(**values))
        return command
