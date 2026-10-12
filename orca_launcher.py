"""Ouvre dans Orca une session Claude Code chargée d'une action du bouton AI sur une MR.

Orca tourne sous Windows, ce serveur dans WSL : on pilote Orca par sa CLI (orca.exe, joignable depuis
WSL par l'interop Windows). Le terminal qu'Orca ouvre sur un worktree \\\\wsl.localhost\\… est un bash
WSL placé dans ce worktree, qui y tape la commande de démarrage telle quelle.

Le terminal s'ouvre toujours sur le worktree principal, comme les autres sessions : c'est Claude qui,
d'après le prompt, travaille dans le worktree de la MR. Tous les onglets restent ainsi au même endroit
dans Orca.
"""
import base64
import json
import os
import secrets
import shlex
import shutil
import subprocess
import time
from pathlib import Path

PROMPT_MAX_CHARS = 20_000
COMMAND_TIMEOUT_S = 60
# Le prompt passe par un fichier : un long texte multiligne ne survivrait pas aux guillemets de la
# ligne de commande Windows. Le terminal le lit puis le supprime ; un fichier jamais lu (terminal fermé
# avant que son shell ait démarré) est purgé au lancement suivant, passé ce délai.
PROMPT_DIR = Path.home() / ".cache" / "mr-dashboard"
PROMPT_MAX_AGE_S = 24 * 3600
# Orca n'attend le terminal que quelques secondes, quand le shell WSL en met parfois plus de dix à
# démarrer : il répond alors en échec alors que le terminal est bel et bien créé.
UNCONFIRMED_ERROR = "Timed out waiting for terminal handle"
# Orca ne traite la création d'un onglet qu'une fois sa fenêtre au premier plan : on l'y ramène avant.
# Windows refuse ce changement à un processus qui n'a pas reçu la dernière saisie, sauf juste après un
# appui clavier : d'où la touche Alt simulée (sans effet visible). Au pire, l'utilisateur bascule à la main.
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
            repo_root,
            distro
    ):
        self._orca_exe = orca
        self._repo_root = repo_root
        self._distro = distro

    @classmethod
    def detect(cls, repo_dir):
        """Le lanceur, ou None hors WSL ou sans Orca installé : le bouton n'est alors pas proposé."""
        orca = shutil.which("orca.exe")
        distro = os.environ.get("WSL_DISTRO_NAME")
        if not orca or not distro:
            return None
        common_dir = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        return cls(
            orca,
            Path(common_dir).parent,
            distro
        )

    def launch(
            self,
            iid,
            title,
            prompt,
            model=None
    ):
        """Ouvre le terminal et renvoie {worktree, confirmed}. Sans model, claude prend celui de sa configuration."""
        if not prompt.strip() or len(prompt) > PROMPT_MAX_CHARS:
            raise OrcaError("prompt vide ou trop long")
        prompt_file = self._write_prompt(
            iid,
            prompt
        )
        model_option = f"--model {shlex.quote(model)} " if model else ""
        self._raise_orca()
        # Le fichier n'est jamais supprimé ici sur erreur : le terminal a pu être créé quand même, et
        # son shell le lirait alors trop tard. Sans le fichier, claude ne démarre pas du tout plutôt
        # que de démarrer sans consigne.
        try:
            self._orca([
                "terminal", "create",
                "--worktree", "path:" + self._windows_path(self._repo_root),
                "--title", title,
                "--command", f"[ -f '{prompt_file}' ] && claude {model_option}\"$(cat '{prompt_file}'; rm -f '{prompt_file}')\"",
                "--focus",
                "--json",
            ])
        except OrcaError as error:
            if not error.unconfirmed:
                raise
            return {"worktree": str(self._repo_root), "confirmed": False}
        return {"worktree": str(self._repo_root), "confirmed": True}

    def _write_prompt(
            self,
            iid,
            prompt
    ):
        PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        for stale in PROMPT_DIR.glob("*MR*.md"):
            if time.time() - stale.stat().st_mtime > PROMPT_MAX_AGE_S:
                stale.unlink(missing_ok=True)
        path = PROMPT_DIR / f"MR{iid}-{secrets.token_hex(4)}.md"
        path.write_text(prompt, encoding="utf-8")
        path.chmod(0o600)
        return path

    def _windows_path(self, path):
        return f"\\\\wsl.localhost\\{self._distro}" + str(path).replace("/", "\\")

    def _raise_orca(self):
        """Au mieux : un échec laisse la création se faire dès que l'utilisateur bascule sur Orca."""
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
            raise OrcaError(f"Orca injoignable : {error}") from error
        output = result.stdout.replace("\r", "")
        try:
            reply = json.loads(output)
        except ValueError:
            reply = None
        if result.returncode != 0 or not (reply or {}).get("ok"):
            error = (reply or {}).get("error")
            message = (error.get("message") if isinstance(error, dict) else error) or result.stderr.strip() or output.strip()
            raise OrcaError(
                f"Orca : {message}",
                unconfirmed=UNCONFIRMED_ERROR in str(message)
            )
        return reply
