"""
circuit_breaker.py — a small, dependency-free circuit breaker.

Wraps calls to a flaky dependency (e.g. the Anthropic API). After
`failure_threshold` consecutive failures the breaker "opens" and fails fast
for `recovery_timeout` seconds — giving the dependency room to recover
instead of piling more load onto it while it is struggling. After the
cooldown it allows a single trial call ("half-open"): success closes the
breaker, another failure re-opens it.

Three states:
  CLOSED     — normal; calls pass through, failures are counted
  OPEN       — too many recent failures; calls short-circuit immediately
  HALF_OPEN  — cooldown elapsed; a trial call is allowed to test recovery

Thread-safe: state is guarded by a lock because Flask serves requests on
multiple threads and /lookup fans out across a ThreadPoolExecutor.

Deliberately tiny and hand-rolled (no third-party dep) so the logic is
transparent — same philosophy as text_utils computing its metrics by hand.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the breaker is open."""


class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[BaseException] | tuple[type[BaseException], ...] = Exception,
    ) -> None:
        """
        name               — label used in logs and the `state` reporting
        failure_threshold  — consecutive failures before the breaker opens
        recovery_timeout   — seconds to stay open before allowing a trial call
        expected_exception — exception type(s) that count as a failure; anything
                             else propagates without tripping the breaker
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self._lock = threading.Lock()
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        """Current state, advancing OPEN → HALF_OPEN if the cooldown has elapsed."""
        with self._lock:
            self._maybe_half_open()
            return self._state

    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        """
        Run `fn(*args, **kwargs)` through the breaker.

        Raises CircuitOpenError immediately if the breaker is open and the
        cooldown has not elapsed. Otherwise the call runs; a failure of an
        `expected_exception` type is recorded (and may open the breaker) and
        re-raised, a success resets the failure count.
        """
        with self._lock:
            self._maybe_half_open()
            if self._state == self.OPEN:
                raise CircuitOpenError(
                    f"circuit '{self.name}' is open — failing fast"
                )

        try:
            result = fn(*args, **kwargs)
        except self.expected_exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    # ── internal ──────────────────────────────────────────────────────────────

    def _maybe_half_open(self) -> None:
        """Promote OPEN → HALF_OPEN once the recovery window has passed. Caller holds the lock."""
        if self._state == self.OPEN and (time.monotonic() - self._opened_at) >= self.recovery_timeout:
            self._state = self.HALF_OPEN
            log.info("circuit '%s': half-open — allowing a trial call", self.name)

    def _on_success(self) -> None:
        with self._lock:
            if self._state != self.CLOSED:
                log.info("circuit '%s': closed — dependency recovered", self.name)
            self._failures = 0
            self._state = self.CLOSED

    def _on_failure(self) -> None:
        with self._lock:
            self._failures += 1
            # A failure during a half-open trial, or crossing the threshold while
            # closed, opens (or re-opens) the breaker.
            if self._state == self.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = self.OPEN
                self._opened_at = time.monotonic()
                log.warning(
                    "circuit '%s': open — %d consecutive failure(s), failing fast for %.0fs",
                    self.name, self._failures, self.recovery_timeout,
                )
