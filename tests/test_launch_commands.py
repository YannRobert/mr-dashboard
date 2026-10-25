"""The command lines the AI button's launches run, held still and run for real.

- Recorded: what each launch target calls (terminal presets, herdr, Orca on Linux and under WSL) and the command
  each agent starts with, compared with tests/golden/launch_commands.json. A deliberate change regenerates it:

      MR_DASHBOARD_UPDATE_GOLDEN=1 python3 -m unittest discover tests

- Run: each terminal's command line, read back the way that terminal reads it (Terminator through DBus included,
  which joins -x's arguments with spaces), must run its shell with the arguments intact; each agent's start
  command, run by sh with stand-in agents, must hand them the prompt intact.

Run with python3 -m unittest discover tests, from the repository. tests/live_launch_check.py checks the same on the
real terminals, herdr and Orca installed.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mr_dashboard"))

import agents  # noqa: E402
import launches  # noqa: E402
from herdr_launcher import HerdrLauncher  # noqa: E402
from orca_launcher import OrcaLauncher  # noqa: E402
from terminal_launcher import PRESETS, TerminalLauncher  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden" / "launch_commands.json"
UPDATE = os.environ.get("MR_DASHBOARD_UPDATE_GOLDEN") == "1"
REPO = Path("/home/user/work/shop")
WORKTREE = Path("/home/user/work/shop-wt/fix-cart")
TITLE = "Fix MR !42"
# A prompt that a lost quoting would break, starting with a dash, which the launch moves to a line of its own.
PROMPT = "- fix it's \"cart\" in $HOME and `date`\nsecond line"


class Recorder:
    """Stands for subprocess.run and subprocess.Popen: records each call and answers as the tool would."""

    def __init__(self):
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[1:3] == ["workspace", "list"]:
            reply = {"result": {"workspaces": []}}
        elif argv[1:3] == ["workspace", "create"]:
            reply = {"result": {"root_pane": {"pane_id": "p1"}, "tab": {"tab_id": "t1"}}}
        else:
            reply = {"ok": True, "result": {}}
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(reply), stderr="")

    def popen(self, argv, **kwargs):
        self.calls.append(list(argv))
        process = mock.Mock()
        process.wait.return_value = 0
        process.stderr.read.return_value = b""
        return process


class LaunchCommandsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() and not UPDATE else {}
        cls.recorded = {}

    @classmethod
    def tearDownClass(cls):
        if UPDATE:
            GOLDEN.parent.mkdir(exist_ok=True)
            GOLDEN.write_text(json.dumps(cls.recorded, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.prompts = Path(directory.name)
        for patch in (mock.patch.object(launches, "PROMPT_DIR", self.prompts),
                      mock.patch.object(launches.secrets, "token_hex", return_value="0123abcd"),
                      mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"})):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop("WSL_DISTRO_NAME", None)

    def check(self, name, value):
        """Compares with the recorded value, the folder of the prompt files written as <prompts>."""
        value = json.loads(json.dumps(value).replace(str(self.prompts), "<prompts>"))
        self.recorded[name] = value
        if not UPDATE:
            self.assertIn(name, self.golden, f"{name} not recorded: regenerate {GOLDEN.name}")
            self.assertEqual(self.golden[name], value, f"{name} changed")

    def launched(self, launcher, agent=None):
        recorder = Recorder()
        with mock.patch("subprocess.run", recorder.run), mock.patch("subprocess.Popen", recorder.popen):
            launcher.launch(42, TITLE, PROMPT, "opus", "high", agent, WORKTREE)
        return recorder.calls

    def test_terminal_presets(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                if preset == "windows-terminal":
                    os.environ["WSL_DISTRO_NAME"] = "Ubuntu"
                launcher = TerminalLauncher(*PRESETS[preset], REPO)
                self.check(f"terminal:{preset}", self.launched(launcher))
                os.environ.pop("WSL_DISTRO_NAME", None)

    def test_herdr(self):
        self.check("herdr", self.launched(HerdrLauncher("herdr", REPO)))

    def test_orca_linux(self):
        self.check("orca", self.launched(OrcaLauncher("orca", REPO)))

    def test_orca_wsl(self):
        with mock.patch("shutil.which", return_value=None):
            self.check("orca:wsl", self.launched(OrcaLauncher("orca.exe", REPO, "Ubuntu")))

    def test_agent_start_commands(self):
        for agent in agents.AGENTS:
            with self.subTest(agent=agent.id):
                launch = launches.prepare(42, PROMPT, *self.settings(agent), agent)
                self.check(f"agent:{agent.id}", launch.shell_command())

    @staticmethod
    def settings(agent):
        return {"claude": ("opus", "high"), "codex": ("gpt-5.5", "high"), "pi": ("openai/gpt-5.5", "high")}[agent.id]


# How each preset's terminal reads its command line back into the command it runs: (marker, how). "rest": the
# arguments after the marker; "string": the last argument, a command line run by a shell; "terminator": Terminator
# already open, which gets the command through DBus, -x's arguments joined with spaces, and runs it with its shell.
TERMINAL_READING = {
    "tmux": (None, "string"),
    "gnome-terminal": ("--", "rest"),
    "konsole": ("-e", "rest"),
    "terminator": (None, "terminator"),
    "wezterm": ("--", "rest"),
    "kitty": (None, "kitty"),
    "windows-terminal": ("--", "rest"),
    "xterm": ("-e", "rest"),
}


def as_run(argv, preset, shell):
    """The command the terminal runs for this command line."""
    marker, how = TERMINAL_READING[preset]
    if how == "rest":
        return argv[argv.index(marker) + 1:]
    if how == "string":
        return [shell, "-c", argv[-1]]
    if how == "kitty":
        rest = argv[argv.index("launch") + 1:]
        return rest[next(i for i, word in enumerate(rest) if not word.startswith("--")):]
    for option in ("-x", "--execute"):
        if option in argv:
            return [shell, "-c", " ".join(argv[argv.index(option) + 1:])]
    return [shell, "-c", argv[argv.index("-e") + 1]]


class LaunchCommandsRunTest(unittest.TestCase):
    """The commands run for real by sh, with probes standing for the agents."""

    WORDS = ["a b", "it's", '"quoted"', "$HOME", "`date`", "-dash"]

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.output = self.directory / "output"

    def probe(self):
        words = " ".join(shlex.quote(word) for word in self.WORDS)
        return f"printf '%s\\n' {words} > {shlex.quote(str(self.output))}; exit"

    def test_terminals_run_the_command_intact(self):
        shell = "/bin/sh"
        for preset in PRESETS:
            with self.subTest(preset=preset), mock.patch.dict(os.environ, {"SHELL": shell}):
                self.output.unlink(missing_ok=True)
                argv = TerminalLauncher(*PRESETS[preset], self.directory)._command(TITLE, self.probe(), self.directory)
                run = as_run(argv, preset, shell)
                # Word for word the shell the launch means, with its whole script: a split script would run its
                # first command in that shell and the others, the agent's among them, in the terminal's.
                ran = shlex.split(run[2]) if run[:2] == [shell, "-c"] else run
                self.assertEqual([shell, "-l", "-i", "-c"], ran[:4], f"{preset}: not the launch's shell")
                self.assertEqual(5, len(ran), f"{preset}: the script is split into {len(ran) - 4} words")
                subprocess.run(run, stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=False)
                self.assertTrue(self.output.exists(), f"{preset}: the command did not run")
                self.assertEqual(self.WORDS, self.output.read_text(encoding="utf-8").splitlines())

    def test_agents_receive_the_prompt_intact(self):
        """Each agent's start command, as Orca and herdr type it and the terminals run it, run by sh: the stand-in
        agent writes the arguments it gets."""
        bin_dir = self.directory / "bin"
        bin_dir.mkdir()
        for program in ("claude", "codex", "pi"):
            stand_in = bin_dir / program
            stand_in.write_text(f"#!/bin/sh\nfor word in \"$@\"; do printf '%s\\0' \"$word\"; done > {shlex.quote(str(self.output))}\n")
            stand_in.chmod(0o755)
        with mock.patch.object(launches, "PROMPT_DIR", self.directory / "prompts"):
            for agent in agents.AGENTS:
                with self.subTest(agent=agent.id):
                    self.output.unlink(missing_ok=True)
                    launch = launches.prepare(42, PROMPT, None, None, agent)
                    subprocess.run(["/bin/sh", "-c", launch.shell_command()], env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
                                   stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=False)
                    self.assertTrue(self.output.exists(), f"{agent.id} did not start")
                    words = self.output.read_text(encoding="utf-8").split("\0")[:-1]
                    # The prompt starts with a dash: a line break before it keeps it from being read as an option.
                    self.assertEqual("\n" + PROMPT, words[-1])
                    self.assertFalse(launch.shell_file.exists(), "the shell's marker is left")


if __name__ == "__main__":
    unittest.main()
