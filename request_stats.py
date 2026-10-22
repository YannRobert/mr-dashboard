"""Requests sent by the server to GitLab (API and git repository) and to Sonar, counted over sliding
windows of 1, 5 and 15 min: enough to check that the dashboard does not overload GitLab. The browser
never talks to them directly, everything goes through the server: the count covers all tabs.
"""
import threading
import time
from collections import deque

WINDOWS_S = (60, 300, 900)


def http_error(status):
    """Error class of an HTTP response, None if it succeeded."""
    if status >= 500:
        return "5xx"
    return "4xx" if status >= 400 else None


class RequestStats:

    def __init__(self, cache_seconds):
        # Lifetime of the responses kept by the relay cache, quoted by the page.
        self._cache_seconds = cache_seconds
        self._started_at = time.time()
        # Since server start, by category.
        self._totals = {}
        self._lock = threading.Lock()
        # (monotonic time, category, error or None), oldest first. Errors: "connection" (no
        # response), "4xx", "5xx", "git" (failed git command). Categories "gitlab-cache" and
        # "sonar-cache": reads served from the cache, without a request.
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
        """For each window, the number of requests and of errors, by class, of each category; and the
        total by category since server start."""
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
