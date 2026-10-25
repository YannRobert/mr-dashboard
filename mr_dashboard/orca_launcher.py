"""Opens in Orca a Claude Code session in charge of an AI button action on a MR.

Orca is driven through its CLI, in one of two set-ups:

- under WSL, with Orca on Windows: orca.exe, reachable from WSL through Windows interop. The terminal Orca
  opens on a \\\\wsl.localhost\\… worktree is a WSL bash placed in that worktree;
- on Linux, with Orca on the same machine: orca, on the PATH. The terminal is the user's login shell,
  placed in the worktree.

Either way, the terminal types the startup command as is: a POSIX shell command, which bash and zsh run.

The terminal always opens on the tracked repository (--repo-dir): it is Claude that, following the prompt,
works in the MR's worktree. All tabs thus stay in the same place in Orca.
"""
import base64
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROMPT_MAX_CHARS = 20_000
COMMAND_TIMEOUT_S = 60
# The prompt goes through a file: a long multiline text would not survive the quoting of the Windows
# command line. The terminal reads it, and the Claude Code session deletes it once started, through a
# SessionStart hook brought by its own settings (sibling file, passed with --settings); a file never
# deleted (shell or claude failing at startup) is purged on the next launch, once past this age. A marker
# file, which the terminal shell deletes first, tells a shell that never started (WSL unreachable, say) from
# a claude that did not start.
PROMPT_DIR = Path.home() / ".cache" / "mr-dashboard"
PROMPT_MAX_AGE_S = 24 * 3600
# Identifier of a launch: the name of its prompt file, without extension.
LAUNCH_ID = re.compile(r"MR\d+-[0-9a-f]{8}")
# Orca waits only a few seconds for the terminal, while the WSL shell sometimes takes more than ten to
# start: it then reports a failure although the terminal was indeed created.
UNCONFIRMED_ERROR = "Timed out waiting for terminal handle"
# Orca only opens terminals in the folders it holds as projects: the tracked repository must be one of them.
NOT_A_PROJECT = "selector_not_found"
# Orca only processes a tab creation once its window is in the foreground: bring it there first.
# Windows refuses this switch to a process that did not receive the last input, except right after a
# key press: hence the simulated Alt key (no visible effect). At worst, the user switches by hand.
RAISE_ORCA_SCRIPT = r"""
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class OrcaWindow {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
}
'@
$window = (Get-Process orca -ErrorAction SilentlyContinue | Where-Object MainWindowHandle -ne 0 | Select-Object -First 1).MainWindowHandle
if (-not $window) { exit 1 }
if ([OrcaWindow]::IsIconic($window)) { [void][OrcaWindow]::ShowWindow($window, 9) }
[OrcaWindow]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
[OrcaWindow]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
if (-not [OrcaWindow]::SetForegroundWindow($window)) { exit 1 }
"""


class OrcaError(Exception):

    def __init__(
            self,
            message,
            unconfirmed=False
    ):
        super().__init__(message)
        self.unconfirmed = unconfirmed


class OrcaLauncher:

    def __init__(
            self,
            orca,
            repo_dir,
            distro=None
    ):
        self._orca_exe = orca
        self._repo_dir = repo_dir
        # The WSL distribution, under WSL with Orca on Windows; None with Orca on Linux.
        self._distro = distro

    @classmethod
    def detect(cls, repo_dir):
        """The launcher, or None without Orca: the button is then not offered. Under WSL, Orca on Windows;
        elsewhere on Linux, Orca on the same machine."""
        distro = os.environ.get("WSL_DISTRO_NAME")
        if distro:
            orca = shutil.which("orca.exe")
            return cls(orca, repo_dir, distro) if orca else None
        orca = shutil.which("orca") if sys.platform.startswith("linux") else None
        return cls(orca, repo_dir) if orca else None

    def launch(
            self,
            iid,
            title,
            prompt,
            model=None,
            effort=None
    ):
        """Opens the terminal and returns {worktree, confirmed, launch}. Without model or effort, claude uses those of its configuration."""
        if not prompt.strip() or len(prompt) > PROMPT_MAX_CHARS:
            raise OrcaError("prompt empty or too long")
        prompt_file = self._write_prompt(
            iid,
            prompt
        )
        settings_file = self._write_settings(prompt_file)
        shell_file = prompt_file.with_suffix(".shell")
        shell_file.touch(mode=0o600)
        model_option = f"--model {shlex.quote(model)} " if model else ""
        effort_option = f"--effort {shlex.quote(effort)} " if effort else ""
        self._raise_orca()
        # Files are never deleted here on error: the terminal may have been created anyway, and its
        # shell would then read them too late. Without the prompt, claude does not start at all rather
        # than start with no instructions.
        try:
            self._orca([
                "terminal", "create",
                "--worktree", "path:" + self._worktree_path(),
                "--title", title,
                "--command", f"rm -f '{shell_file}'; [ -f '{prompt_file}' ] && claude --settings '{settings_file}' {model_option}{effort_option}\"$(cat '{prompt_file}')\"",
                "--focus",
                "--json",
            ])
        except OrcaError as error:
            if NOT_A_PROJECT in str(error):
                raise OrcaError(f"Orca does not know {self._worktree_path()}: add it to Orca as a project, "
                                f"or run orca repo add --path {shlex.quote(self._worktree_path())}") from error
            if not error.unconfirmed:
                raise
            return {"worktree": str(self._repo_dir), "confirmed": False, "launch": prompt_file.stem}
        return {"worktree": str(self._repo_dir), "confirmed": True, "launch": prompt_file.stem}

    @staticmethod
    def progress(launch):
        """{shell, claude}: true once the terminal shell, then the launch's Claude Code session, have started,
        each deleting its file (the marker, then the prompt through the SessionStart hook). The tab
        creation, which Orca confirms, guarantees neither."""
        if not LAUNCH_ID.fullmatch(launch):
            raise OrcaError("unknown launch")
        claude = not (PROMPT_DIR / f"{launch}.md").exists()
        return {"shell": claude or not (PROMPT_DIR / f"{launch}.shell").exists(), "claude": claude}

    def _write_prompt(
            self,
            iid,
            prompt
    ):
        PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        for stale in PROMPT_DIR.glob("MR*"):
            if time.time() - stale.stat().st_mtime > PROMPT_MAX_AGE_S:
                stale.unlink(missing_ok=True)
        path = PROMPT_DIR / f"MR{iid}-{secrets.token_hex(4)}.md"
        path.write_text(prompt, encoding="utf-8")
        path.chmod(0o600)
        return path

    @staticmethod
    def _write_settings(prompt_file):
        path = prompt_file.with_suffix(".settings.json")
        cleanup = f"rm -f {shlex.quote(str(prompt_file))} {shlex.quote(str(path))}"
        settings = {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": cleanup}]}]}}
        path.write_text(json.dumps(settings), encoding="utf-8")
        path.chmod(0o600)
        return path

    def _worktree_path(self):
        """The tracked repository as Orca sees it: a Windows path to the WSL file system, or the Linux path."""
        if not self._distro:
            return str(self._repo_dir)
        return f"\\\\wsl.localhost\\{self._distro}" + str(self._repo_dir).replace("/", "\\")

    def _raise_orca(self):
        """Best effort, on Windows only: on failure, the creation happens as soon as the user switches to Orca.
        On Linux, --focus is enough."""
        if not self._distro:
            return
        powershell = shutil.which("powershell.exe")
        if not powershell:
            return
        try:
            subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", base64.b64encode(RAISE_ORCA_SCRIPT.encode("utf-16-le")).decode()],
                capture_output=True,
                timeout=COMMAND_TIMEOUT_S,
                check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _orca(self, args):
        try:
            result = subprocess.run(
                [self._orca_exe, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=COMMAND_TIMEOUT_S,
                check=False
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise OrcaError(f"Orca unreachable: {error}") from error
        output = result.stdout.replace("\r", "")
        try:
            reply = json.loads(output)
        except ValueError:
            reply = None
        if result.returncode != 0 or not (reply or {}).get("ok"):
            error = (reply or {}).get("error")
            message = (error.get("message") if isinstance(error, dict) else error) or result.stderr.strip() or output.strip()
            raise OrcaError(
                f"Orca: {message}",
                unconfirmed=UNCONFIRMED_ERROR in str(message)
            )
        return reply
