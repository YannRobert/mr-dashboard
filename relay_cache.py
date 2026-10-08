"""Réponses des lectures relayées vers GitLab et Sonar, gardées quelques secondes : des onglets ou des
navigateurs qui demandent la même adresse dans ce délai n'envoient qu'une requête, et des demandes
simultanées attendent la même réponse au lieu d'en envoyer chacune une. Toutes passent par le même
jeton : la réponse à une adresse ne dépend pas de qui la demande.
"""
import threading
import time

TTL_S = 30


class RelayCache:

    def __init__(self, ttl_s=TTL_S):
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        # adresse -> (instant monotone d'expiration, réponse)
        self._entries = {}
        # adresse -> événement de la requête en cours, que les demandes simultanées attendent
        self._pending = {}
        # Compte des écritures : une réponse demandée avant la dernière n'est pas gardée.
        self._generation = 0

    def get(
            self,
            url,
            load,
            keep,
            fresh
    ):
        """(réponse, servie par le cache) ; load() fait la requête, keep(réponse) dit si elle se garde.
        Les demandes arrivées pendant la requête en reçoivent la réponse, gardée ou non, ou l'exception.
        fresh : la réponse gardée est ignorée (bouton « Rafraîchir »), la nouvelle la remplace."""
        with self._lock:
            entry = self._entries.get(url)
            if not fresh and entry and entry[0] > time.monotonic():
                return entry[1], True
            pending = self._pending.get(url)
            loader = pending is None
            if loader:
                pending = self._pending[url] = _Pending(self._generation)
        if not loader:
            pending.done.wait()
            if pending.error:
                raise pending.error
            return pending.response, True
        try:
            pending.response = load()
        except BaseException as error:
            pending.error = error
            raise
        finally:
            with self._lock:
                del self._pending[url]
                # Une écriture faite pendant la requête a pu rendre sa réponse périmée : pas gardée.
                if pending.error is None and pending.generation == self._generation and keep(pending.response):
                    now = time.monotonic()
                    self._forget(now)
                    self._entries[url] = (now + self._ttl_s, pending.response)
            pending.done.set()
        return pending.response, False

    def clear(self):
        """Après une écriture : la prochaine lecture repart de GitLab."""
        with self._lock:
            self._entries.clear()
            self._generation += 1

    def _forget(self, now):
        for url in [url for url, (expires, _) in self._entries.items() if expires <= now]:
            del self._entries[url]


class _Pending:

    def __init__(self, generation):
        self.generation = generation
        self.done = threading.Event()
        self.response = None
        self.error = None
