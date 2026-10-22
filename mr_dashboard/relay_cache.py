"""Responses of reads relayed to GitLab and Sonar, kept for a few seconds: tabs or browsers requesting
the same URL within that delay send only one request, and simultaneous requests wait for the same
response instead of each sending one. All go through the same token: the response for a URL does not
depend on who asks for it.
"""
import threading
import time

TTL_S = 30


class RelayCache:

    def __init__(self, ttl_s=TTL_S):
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        # url -> (monotonic expiry time, response)
        self._entries = {}
        # url -> event of the request in progress, which simultaneous requests wait for
        self._pending = {}
        # Write counter: a response requested before the latest write is not kept.
        self._generation = 0

    def get(
            self,
            url,
            load,
            keep,
            fresh
    ):
        """(response, served from cache); load() makes the request, keep(response) says whether it is kept.
        Requests arriving during the request get its response, kept or not, or its exception.
        fresh: the kept response is ignored (Refresh button), the new one replaces it."""
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
                # A write made during the request may have made its response stale: not kept.
                if pending.error is None and pending.generation == self._generation and keep(pending.response):
                    now = time.monotonic()
                    self._forget(now)
                    self._entries[url] = (now + self._ttl_s, pending.response)
            pending.done.set()
        return pending.response, False

    def clear(self):
        """After a write: the next read goes back to GitLab."""
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
