"""Requêtes envoyées par le serveur à GitLab (API et dépôt git) et à Sonar, comptées sur des fenêtres
glissantes de 1, 5 et 15 min : de quoi vérifier que le dashboard ne surcharge pas GitLab. Le navigateur
ne leur parle jamais en direct, tout passe par le serveur : le compte vaut pour tous les onglets.
"""
import threading
import time
from collections import deque

WINDOWS_S = (60, 300, 900)


def http_error(status):
    """Classe d'erreur d'une réponse HTTP, None si elle a abouti."""
    if status >= 500:
        return "5xx"
    return "4xx" if status >= 400 else None


class RequestStats:

    def __init__(self, cache_seconds):
        # Durée de vie des réponses gardées par le cache du relais, citée par la page.
        self._cache_seconds = cache_seconds
        self._started_at = time.time()
        # Depuis le démarrage du serveur, par catégorie.
        self._totals = {}
        self._lock = threading.Lock()
        # (instant monotone, catégorie, erreur ou None), du plus ancien au plus récent. Erreurs :
        # "connection" (aucune réponse), "4xx", "5xx", "git" (commande git en échec). Catégories
        # "gitlab-cache" et "sonar-cache" : lectures servies par le cache, sans requête.
        self._events = deque()

    def record(
            self,
            kind,
            error
    ):
        now = time.monotonic()
        with self._lock:
            self._events.append((now, kind, error))
            self._totals[kind] = self._totals.get(kind, 0) + 1
            self._forget(now)

    def snapshot(self):
        """Pour chaque fenêtre, le nombre de requêtes et d'erreurs, par classe, de chaque catégorie ; et
        le total par catégorie depuis le démarrage du serveur."""
        now = time.monotonic()
        with self._lock:
            self._forget(now)
            events = list(self._events)
            totals = dict(self._totals)
        result = []
        for seconds in WINDOWS_S:
            counts, errors = {}, {}
            for at, kind, error in events:
                if now - at <= seconds:
                    counts[kind] = counts.get(kind, 0) + 1
                    if error:
                        by_error = errors.setdefault(kind, {})
                        by_error[error] = by_error.get(error, 0) + 1
            result.append({"seconds": seconds, "counts": counts, "errors": errors})
        return {"windows": result, "sinceStart": totals, "startedAt": int(self._started_at * 1000),
                "cacheSeconds": self._cache_seconds}

    def _forget(self, now):
        while self._events and now - self._events[0][0] > WINDOWS_S[-1]:
            self._events.popleft()
