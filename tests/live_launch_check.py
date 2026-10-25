"""Checks by hand that each launch target installed here really runs the command it is given, quoting intact.

Not a unit test: it opens real tabs, in the terminals, herdr and Orca found on this machine (see launch_targets.py),
each running, instead of an agent, a probe that writes its arguments and folder to a file, then exits, which closes
the tab. Run it from the repository, with Orca and herdr running for them to be checked:

    python3 tests/live_launch_check.py [target ...]

Without arguments, every target found; a target is a --launch-in value (terminal:xterm, herdr, orca).
"""
import os
import shlex
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mr_dashboard"))

import launch_targets  # noqa: E402
import launches  # noqa: E402

# Words a prompt may hold that a lost quoting would break: spaces, quotes, a variable and a command substitution.
WORDS = ["a b", "it's", '"quoted"', "$HOME", "`date`", "-dash"]
WAIT_S = 20


class Probe:
    """Stands for launches.Launch: its command writes the probe's arguments and folder, then exits."""

    def __init__(
            self,
            output
    ):
        self.output = output

    def shell_command(self):
        words = " ".join(shlex.quote(word) for word in WORDS)
        return f"printf '%s\\n' {words} \"$PWD\" > {shlex.quote(str(self.output))}; exit"

    def result(self, worktree, confirmed):
        return {"worktree": str(worktree), "confirmed": confirmed, "launch": "probe"}


def check(target, folder, output):
    launches.prepare = lambda *args, **kwargs: Probe(output)
    try:
        target.launch(0, f"Probe {target.id}", "probe")
    except launches.LaunchError as error:
        return f"launch failed: {error}"
    deadline = time.time() + WAIT_S
    while time.time() < deadline and not output.exists():
        time.sleep(0.5)
    time.sleep(0.5)
    if not output.exists():
        return f"nothing written in {WAIT_S} s: the command did not run"
    got = output.read_text(encoding="utf-8").splitlines()
    expected = [*WORDS, str(folder)]
    return None if got == expected else f"got {got}, expected {expected}"


def main(values):
    repo_dir = Path(__file__).resolve().parent.parent
    targets = launch_targets.choose_all(values or ["auto"], repo_dir)
    failures = 0
    with tempfile.TemporaryDirectory(prefix="mr-dashboard-probe-") as directory:
        for target in targets:
            reason = target.unavailable()
            if reason:
                print(f"skip  {target.id}: {reason}")
                continue
            problem = check(target, repo_dir, Path(directory) / f"{target.id.replace(':', '-')}.txt")
            failures += bool(problem)
            print(f"{'FAIL' if problem else 'ok  '}  {target.id}{f': {problem}' if problem else ''}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
