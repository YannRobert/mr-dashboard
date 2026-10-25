"""Where the AI button opens its sessions, as --launch-in names it:

    auto     Orca when it is found (the default), else nowhere: prompts are copied
    none     nowhere, even with Orca installed
    orca     Orca, which must be found

Each target has a name, shown on the button, and launch(iid, title, prompt, model, effort), which opens a tab
running the agent and returns what launches.Launch.result gives.
"""
from orca_launcher import OrcaLauncher

TARGETS = ("auto", "none", "orca")


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
    raise LaunchTargetError(f"unknown launch target: {launch_in} (one of {', '.join(TARGETS)})")
