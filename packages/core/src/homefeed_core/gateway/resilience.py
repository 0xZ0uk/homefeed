"""Retries with exponential backoff and a minimum spacing between requests."""

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from homefeed_core.gateway.errors import GatewayError

Clock = Callable[[], float]
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class RetryPolicy:
    """Retry retryable `GatewayError`s up to `attempts` tries in total.

    The delay before retry `n` (1-based) is `initial_delay * multiplier ** (n - 1)`,
    capped at `max_delay`, with up to `jitter` (a fraction) added at random.
    """

    attempts: int = 3
    initial_delay: float = 2.0
    multiplier: float = 2.0
    max_delay: float = 30.0
    jitter: float = 0.25

    def delay(self, retry: int, rng: random.Random) -> float:
        base = min(self.initial_delay * self.multiplier ** (retry - 1), self.max_delay)
        return base * (1 + self.jitter * rng.random())


class RateLimiter:
    """Spaces calls at least `min_interval` seconds apart. Thread-safe."""

    def __init__(
        self,
        min_interval: float = 1.0,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed: float | None = None

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._next_allowed is not None and now < self._next_allowed:
                self._sleep(self._next_allowed - now)
                now = self._next_allowed
            self._next_allowed = now + self.min_interval


def call_with_retries[T](
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    sleep: Sleep = time.sleep,
    rng: random.Random | None = None,
    on_attempt: Callable[[int], None] | None = None,
) -> T:
    """Call `fn`, retrying retryable `GatewayError`s per `policy`.

    `on_attempt(n)` is called before each try (1-based). Non-retryable errors and the
    last retryable one propagate unchanged.
    """
    rng = rng or random.Random()
    attempt = 1
    while True:
        if on_attempt is not None:
            on_attempt(attempt)
        try:
            return fn()
        except GatewayError as error:
            if not error.retryable or attempt >= policy.attempts:
                raise
            sleep(policy.delay(attempt, rng))
            attempt += 1
