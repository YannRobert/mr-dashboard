"""Opens in Orca a Claude Code session in charge of an AI button action on a MR.

Orca is driven through its CLI, in one of two set-ups:

- under WSL, with Orca on Windows: orca.exe, reachable from WSL through Windows interop. The terminal Orca
  opens on a \\\\wsl.localhost\\… worktree is a WSL bash placed in that worktree;
- on Linux, with Orca on the same machine: orca, on the PATH. The terminal is the user's login shell,
  placed in the worktree.

Either way, the terminal types the startup command as is: a POSIX shell command, which bash and zsh run.

The terminal opens in the MR's worktree when one has its branch checked out and Orca knows it, else on the
tracked repository (--repo-dir).
"""
import base64
import json
import os
import shlex
import shutil
import subprocess
import sys

import launches
from launches import LaunchError

COMMAND_TIMEOUT_S = 60
STATUS_TIMEOUT_S = 4
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


class OrcaLauncher:

    name = "Orca"

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

    def unavailable(self):
        """Why Orca cannot open a tab now, or None: its app must be running."""
        try:
            result = subprocess.run([self._orca_exe, "status"], capture_output=True, text=True, encoding="utf-8",
                                    timeout=STATUS_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return "not answering"
        return None if "appRunning: true" in result.stdout else "not running"

    def launch(
            self,
            iid,
            title,
            prompt,
            model=None,
            effort=None,
            agent=None,
            worktree=None
    ):
        """Opens the tab, in the MR's worktree when given and Orca knows it, else at the root of the repository, and
        returns {worktree, confirmed, launch}."""
        launch = launches.prepare(
            iid,
            prompt,
            model,
            effort,
            agent
        )
        self._raise_orca()
        folders = [worktree, self._repo_dir] if worktree and worktree != self._repo_dir else [self._repo_dir]
        for folder in folders:
            try:
                self._orca([
                    "terminal", "create",
                    "--worktree", "path:" + self._orca_path(folder),
                    "--title", title,
                    "--command", launch.shell_command(),
                    "--focus",
                    "--json",
                ])
            except LaunchError as error:
                # Orca opens no tab in a folder it does not know: the root of the repository then, if not tried yet.
                if NOT_A_PROJECT in str(error) and folder != folders[-1]:
                    continue
                if NOT_A_PROJECT in str(error):
                    raise LaunchError(f"Orca does not know {self._orca_path(folder)}: add it to Orca as a project, "
                                      f"or run orca repo add --path {shlex.quote(self._orca_path(folder))}") from error
                if not error.unconfirmed:
                    raise
                return launch.result(folder, confirmed=False)
            return launch.result(folder, confirmed=True)

    def _orca_path(self, folder):
        """A folder as Orca sees it: a Windows path to the WSL file system, or the Linux path."""
        if not self._distro:
            return str(folder)
        return f"\\\\wsl.localhost\\{self._distro}" + str(folder).replace("/", "\\")

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
            raise LaunchError(f"Orca unreachable: {error}") from error
        output = result.stdout.replace("\r", "")
        try:
            reply = json.loads(output)
        except ValueError:
            reply = None
        if result.returncode != 0 or not (reply or {}).get("ok"):
            error = (reply or {}).get("error")
            message = (error.get("message") if isinstance(error, dict) else error) or result.stderr.strip() or output.strip()
            raise LaunchError(
                f"Orca: {message}",
                unconfirmed=UNCONFIRMED_ERROR in str(message)
            )
        return reply
