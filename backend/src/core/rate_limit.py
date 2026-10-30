"""In-process token buckets for the unauthenticated endpoints.

Shared by the public share pages and the sign-in / signup routes. Each bucket
lives in this process's memory, so the limits are PER REPLICA: two pods means two
buckets and twice the allowance. That is the honest scope of it -- it raises the
cost of hammering an endpoint from one address without pretending to be a real
distributed limit. If the shared instance ever runs more than one replica and the
login limits start to matter, back these with Postgres instead.
"""

from __future__ import annotations

import threading
import time
import weakref

from fastapi import Request

from src.core.analytics import client_ip_from_request


_all_buckets: "weakref.WeakSet[TokenBucket]" = weakref.WeakSet()

# Indirection so tests can stop the clock: a bcrypt round per login is slow
# enough that a real clock refills the bucket in the middle of a test.
_clock = time.monotonic


class TokenBucket:
    """`capacity` requests at once, refilled at `refill_per_second`, per key.

    Past `max_keys` tracked keys the whole table is dropped rather than evicted
    entry by entry: a flood of distinct keys is itself the attack, and forgetting
    everyone at once costs less than tracking them.
    """

    def __init__(self, capacity: float, refill_per_second: float, max_keys: int = 20_000):
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self.max_keys = max_keys
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        _all_buckets.add(self)

    def hit(self, key: str) -> bool:
        """Spend one token for `key`. True means the caller is over the limit."""
        now = _clock()
        with self._lock:
            if len(self._buckets) > self.max_keys:
                self._buckets.clear()
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_second)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return True
            self._buckets[key] = (tokens - 1.0, now)
            return False

    def blocked(self, key: str) -> bool:
        """Whether `key` is out of tokens, without spending one.

        For limits charged only on failure (a wrong password): check before the
        attempt, `hit` after it fails, and a correct attempt costs nothing.
        """
        now = _clock()
        with self._lock:
            entry = self._buckets.get(key)
            if entry is None:
                return False
            tokens, last = entry
            return min(self.capacity, tokens + (now - last) * self.refill_per_second) < 1.0

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def reset_all_rate_limits() -> None:
    """Test hook -- the buckets are module state and must not leak between tests."""
    for bucket in list(_all_buckets):
        bucket.reset()


def client_ip(request: Request) -> str:
    # Shared with the analytics path so a bucket and a location are always keyed
    # to the same address. In the k8s deployments Traefik sits in front and, with
    # its default (untrusted) forwardedHeaders setting, replaces any
    # X-Forwarded-For the client sent with the address it saw, so the left-most
    # entry is the real peer there. Anywhere the API is reachable without such a
    # proxy the header is client-controlled -- which is why every login and
    # signup limit is also keyed by email, not by IP alone.
    return client_ip_from_request(request) or "unknown"
