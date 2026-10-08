"""Requêtes envoyées par le serveur à GitLab (API et dépôt git) et à Sonar, comptées sur des fenêtres
glissantes de 1, 5 et 15 min : de quoi vérifier que le dashboard ne surcharge pas GitLab. Le navigateur
ne leur parle jamais en direct, tout passe par le serveur : le compte vaut pour tous les onglets.
"""
import threading
import time
from collections import deque

WINDOWS_S = (60, 300, 900)


class RequestStats:

    def __init__(self):
        self._lock = threading.Lock()
        # (instant monotone, catégorie, en échec), du plus ancien au plus récent.
        self._events = deque()

    def record(
            self,
            kind,
            failed
    ):
        now = time.monotonic()
        with self._lock:
            self._events.append((now, kind, failed))
            self._forget(now)

    def windows(self):
        """Pour chaque fenêtre, le nombre de requêtes et d'échecs par catégorie."""
        now = time.monotonic()
        with self._lock:
            self._forget(now)
            events = list(self._events)
        result = []
        for seconds in WINDOWS_S:
            counts, failures = {}, {}
            for at, kind, failed in events:
                if now - at <= seconds:
                    counts[kind] = counts.get(kind, 0) + 1
                    failures[kind] = failures.get(kind, 0) + int(failed)
            result.append({"seconds": seconds, "counts": counts, "failures": failures})
        return result

    def _forget(self, now):
        while self._events and now - self._events[0][0] > WINDOWS_S[-1]:
            self._events.popleft()
