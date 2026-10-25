"""Opens in herdr, the terminal multiplexer for coding agents, a coding agent's session in charge of an AI button action
on a MR.

herdr is driven through its CLI, which talks to the running herdr session: a new tab on the tracked repository
(--repo-dir), in the workspace named after it, then the agent's start command run in that tab's pane. herdr
recognises the agent in the pane on its own, and shows its state in its sidebar.
"""
import json
import shutil
import subprocess

import launches
from launches import LaunchError

COMMAND_TIMEOUT_S = 30
STATUS_TIMEOUT_S = 3


class HerdrLauncher:

    name = "herdr"

    def __init__(
            self,
            herdr,
            repo_dir
    ):
        self._herdr_exe = herdr
        self._repo_dir = repo_dir

    @classmethod
    def detect(cls, repo_dir):
        """The launcher, or None without herdr on the PATH."""
        herdr = shutil.which("herdr")
        return cls(herdr, repo_dir) if herdr else None

    def unavailable(self):
        """Why herdr cannot open a tab now, or None: only when its status says its server is not running. A status
        that does not come in time leaves herdr offered, without holding the dialog."""
        try:
            result = subprocess.run([self._herdr_exe, "status", "server"], capture_output=True, text=True,
                                    encoding="utf-8", timeout=STATUS_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return "not running" if "status: not running" in result.stdout else None

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
        """Opens the tab, in the MR's worktree when given, else at the root of the repository, and returns
        {worktree, confirmed, launch}."""
        launch = launches.prepare(
            iid,
            prompt,
            model,
            effort,
            agent
        )
        folder = worktree or self._repo_dir
        workspace = self._workspace()
        if workspace:
            reply = self._herdr(["tab", "create", "--workspace", workspace, "--cwd", str(folder), "--label", title, "--focus"])
        else:
            reply = self._herdr(["workspace", "create", "--cwd", str(folder), "--label", self._repo_dir.name, "--focus"])
            # A new workspace's first tab takes the session's title, as later tabs do.
            tab = (reply or {}).get("result", {}).get("tab", {}).get("tab_id")
            if tab:
                self._herdr(["tab", "rename", tab, title])
        try:
            pane = reply["result"]["root_pane"]["pane_id"]
        except (KeyError, TypeError) as error:
            raise LaunchError(f"herdr: no pane in its answer: {json.dumps(reply)[:200]}") from error
        self._herdr(["pane", "run", pane, launch.shell_command()])
        return launch.result(folder, confirmed=True)

    def _workspace(self):
        """The workspace of the tracked repository: the one labelled with its folder's name, which the first launch
        creates. Its tabs then gather the project's sessions, away from the workspace in focus."""
        reply = self._herdr(["workspace", "list"])
        for workspace in (reply or {}).get("result", {}).get("workspaces", []):
            if workspace.get("label") == self._repo_dir.name:
                return workspace.get("workspace_id")
        return None

    def _herdr(self, args):
        try:
            result = subprocess.run(
                [self._herdr_exe, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=COMMAND_TIMEOUT_S,
                check=False
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LaunchError(f"herdr unreachable: {error}") from error
        # Its answer is JSON, on the standard output, or on the error output when it fails.
        reply = None
        for output in (result.stdout, result.stderr):
            try:
                reply = json.loads(output)
                break
            except ValueError:
                continue
        if result.returncode != 0:
            error = (reply or {}).get("error")
            message = (error.get("message") if isinstance(error, dict) else error) or result.stderr.strip() or result.stdout.strip()
            raise LaunchError(f"herdr: {message or f'exit status {result.returncode}'}")
        return reply
