"""Couleur de la pastille de chaque personne, gardée par le serveur : le stockage d'un navigateur ne vaut
que pour lui, et deux navigateurs, rencontrant les personnes dans un ordre différent, leur donnaient des
couleurs différentes. Un seul fichier pour tous les profils : une personne garde sa couleur d'un projet
à l'autre.
"""
import json
import os
import threading
from pathlib import Path

DEFAULT_PATH = Path.home() / ".local" / "state" / "mr-dashboard-avatar-colors.json"


class AvatarColors:

    def __init__(self, path):
        self._path = path
        self._lock = threading.Lock()
        self._slots = self._read()

    def _read(self):
        try:
            saved = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}
        if not isinstance(saved, dict):
            return {}
        return {name: slot for name, slot in saved.items()
                if isinstance(name, str) and isinstance(slot, int) and not isinstance(slot, bool) and slot >= 0}

    def snapshot(self):
        with self._lock:
            return dict(self._slots)

    def assign(
            self,
            names,
            count
    ):
        """Donne à chaque nom encore sans couleur la moins utilisée des count couleurs, et la retient."""
        with self._lock:
            new = [name for name in dict.fromkeys(names) if name not in self._slots]
            if new:
                uses = [0] * count
                for slot in self._slots.values():
                    if slot < count:
                        uses[slot] += 1
                for name in new:
                    slot = uses.index(min(uses))
                    self._slots[name] = slot
                    uses[slot] += 1
                self._write()
            return dict(self._slots)

    def _write(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._slots, ensure_ascii=False, indent=1, sort_keys=True))
        os.replace(temporary, self._path)
