"""Where the AI button can open its sessions, as --launch-in names them, once or several times: the dialog then offers
them in a menu, the first one chosen until the user picks another.

    auto     every target found, in this order: Orca, herdr, the terminals of PRESETS installed (the default)
    none     nowhere, even with Orca installed: prompts are copied
    orca     Orca, which must be found
    herdr    herdr, the terminal multiplexer for coding agents, which must be found and running
    terminal:<preset>    a terminal, as one of terminal_launcher.PRESETS opens it (terminal:gnome-terminal)
    terminal:<template>  a terminal, as a command template of your own opens it (see terminal_launcher.py)

Each target has an id (its --launch-in value), a name, shown on the button, unavailable(), why it cannot open a tab
now (None when it can), and launch(iid, title, prompt, model, effort, agent, worktree), which opens a tab running
the agent, in the MR's worktree when given, and returns what launches.Launch.result gives.
"""
import os
from concurrent.futures import ThreadPoolExecutor

from herdr_launcher import HerdrLauncher
from orca_launcher import OrcaLauncher
from terminal_launcher import PRESETS, TerminalLauncher

TARGETS = ("auto", "none", "orca", "herdr", *(f"terminal:{preset}" for preset in PRESETS), "terminal:<template>")


class LaunchTargetError(Exception):
    pass


def choose_all(launch_in, repo_dir):
    """The launch targets of the --launch-in values, in their order, without duplicates: empty when prompts are only
    copied."""
    targets = []
    for value in launch_in or ["auto"]:
        for target in _targets(value, repo_dir):
            if target.id not in (other.id for other in targets):
                targets.append(target)
    return targets


def _targets(value, repo_dir):
    if value == "auto":
        return _found(repo_dir)
    if value == "none":
        return []
    return [_named(value, repo_dir)]


def _named(value, repo_dir):
    """The target of one --launch-in value, which must be usable."""
    if value == "orca":
        target = OrcaLauncher.detect(repo_dir)
        if target is None:
            raise LaunchTargetError("Orca not found: orca.exe from WSL, or orca on Linux")
    elif value == "herdr":
        target = HerdrLauncher.detect(repo_dir)
        if target is None:
            raise LaunchTargetError("herdr not found on the PATH")
    elif value.startswith("terminal:"):
        try:
            target = TerminalLauncher.of(value[len("terminal:"):], repo_dir)
        except ValueError as error:
            raise LaunchTargetError(str(error)) from error
    else:
        raise LaunchTargetError(f"unknown launch target: {value} (one of {', '.join(TARGETS)})")
    target.id = value
    return target


def _found(repo_dir):
    """Every target installed: Orca and herdr when found, then the terminals of PRESETS whose program is on the PATH,
    Windows Terminal under WSL only."""
    found = []
    for value in ("orca", "herdr", *(f"terminal:{preset}" for preset in PRESETS)):
        if value == "terminal:windows-terminal" and not os.environ.get("WSL_DISTRO_NAME"):
            continue
        try:
            found.append(_named(value, repo_dir))
        except LaunchTargetError:
            continue
    return found


def availability(targets):
    """[{"id", "name", "unavailable"}]: why each target cannot open a tab now, or None, all asked at once."""
    if not targets:
        return []
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        reasons = list(pool.map(lambda target: target.unavailable(), targets))
    return [{"id": target.id, "name": target.name, "unavailable": reason} for target, reason in zip(targets, reasons)]
