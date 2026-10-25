"""Where the AI button opens its sessions, as --launch-in names it:

    auto     Orca when it is found (the default), else nowhere: prompts are copied
    none     nowhere, even with Orca installed
    orca     Orca, which must be found
    herdr    herdr, the terminal multiplexer for coding agents, which must be found and running
    terminal:<preset>    a terminal, as one of terminal_launcher.PRESETS opens it (terminal:gnome-terminal)
    terminal:<template>  a terminal, as a command template of your own opens it (see terminal_launcher.py)

Each target has a name, shown on the button, and launch(iid, title, prompt, model, effort), which opens a tab
running the agent and returns what launches.Launch.result gives.
"""
from herdr_launcher import HerdrLauncher
from orca_launcher import OrcaLauncher
from terminal_launcher import PRESETS, TerminalLauncher

TARGETS = ("auto", "none", "orca", "herdr", *(f"terminal:{preset}" for preset in PRESETS), "terminal:<template>")


class LaunchTargetError(Exception):
    pass


def choose(launch_in, repo_dir):
    """The launch target of --launch-in, or None when prompts are only copied."""
    if launch_in == "auto":
        return OrcaLauncher.detect(repo_dir)
    if launch_in == "none":
        return None
    if launch_in == "orca":
        target = OrcaLauncher.detect(repo_dir)
        if target is None:
            raise LaunchTargetError("Orca not found: orca.exe from WSL, or orca on Linux")
        return target
    if launch_in == "herdr":
        target = HerdrLauncher.detect(repo_dir)
        if target is None:
            raise LaunchTargetError("herdr not found on the PATH")
        return target
    if launch_in.startswith("terminal:"):
        try:
            return TerminalLauncher.of(launch_in[len("terminal:"):], repo_dir)
        except ValueError as error:
            raise LaunchTargetError(str(error)) from error
    raise LaunchTargetError(f"unknown launch target: {launch_in} (one of {', '.join(TARGETS)})")
