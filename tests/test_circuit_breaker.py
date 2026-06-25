"""
Fault-injection tests for the circuit breaker.

These deliberately "break" a fake dependency to prove the breaker opens after
repeated failures, fails fast while open, and recovers via a half-open trial.
A fake clock (monkeypatched time.monotonic) drives the recovery timing so the
tests are deterministic and instant — no real sleeping, no network.
"""

import pytest

from app.circuit_breaker import CircuitBreaker, CircuitOpenError


class Boom(Exception):
    """Stand-in for a dependency failure that should trip the breaker."""


def _boom():
    raise Boom("dependency down")


def _ok():
    return "ok"


@pytest.fixture
def clock(monkeypatch):
    """A controllable monotonic clock. Advance with clock.advance(seconds)."""
    state = {"t": 1000.0}

    class Clock:
        def advance(self, seconds):
            state["t"] += seconds

    monkeypatch.setattr("app.circuit_breaker.time.monotonic", lambda: state["t"])
    return Clock()


class TestClosedState:
    def test_starts_closed(self):
        assert CircuitBreaker("t").state == CircuitBreaker.CLOSED

    def test_success_passes_through_and_returns_value(self):
        cb = CircuitBreaker("t")
        assert cb.call(lambda x: x + 1, 41) == 42

    def test_expected_failure_propagates(self):
        cb = CircuitBreaker("t", expected_exception=Boom)
        with pytest.raises(Boom):
            cb.call(_boom)

    def test_failures_below_threshold_stay_closed(self):
        cb = CircuitBreaker("t", failure_threshold=3, expected_exception=Boom)
        for _ in range(2):
            with pytest.raises(Boom):
                cb.call(_boom)
        assert cb.state == CircuitBreaker.CLOSED


class TestOpening:
    def test_opens_exactly_at_threshold(self):
        cb = CircuitBreaker("t", failure_threshold=3, expected_exception=Boom)
        for _ in range(2):
            with pytest.raises(Boom):
                cb.call(_boom)
        assert cb.state == CircuitBreaker.CLOSED
        with pytest.raises(Boom):
            cb.call(_boom)  # third failure
        assert cb.state == CircuitBreaker.OPEN

    def test_open_fails_fast_without_invoking_fn(self):
        cb = CircuitBreaker("t", failure_threshold=1, expected_exception=Boom)
        with pytest.raises(Boom):
            cb.call(_boom)
        assert cb.state == CircuitBreaker.OPEN

        invoked = []
        with pytest.raises(CircuitOpenError):
            cb.call(lambda: invoked.append(1))
        assert invoked == []  # the protected call was never made


class TestRecovery:
    def test_stays_open_until_timeout_then_half_open_success_closes(self, clock):
        cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout=30.0, expected_exception=Boom)
        with pytest.raises(Boom):
            cb.call(_boom)
        assert cb.state == CircuitBreaker.OPEN

        # Just before the cooldown elapses: still open, fails fast.
        clock.advance(29)
        with pytest.raises(CircuitOpenError):
            cb.call(_ok)

        # Past the cooldown: a trial call is allowed; success closes the breaker.
        clock.advance(2)
        assert cb.call(_ok) == "ok"
        assert cb.state == CircuitBreaker.CLOSED

    def test_half_open_trial_failure_reopens(self, clock):
        cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout=10.0, expected_exception=Boom)
        with pytest.raises(Boom):
            cb.call(_boom)

        clock.advance(11)  # cooldown elapsed -> next call is the half-open trial
        with pytest.raises(Boom):
            cb.call(_boom)  # trial fails
        assert cb.state == CircuitBreaker.OPEN

        # And it fails fast again immediately afterwards.
        with pytest.raises(CircuitOpenError):
            cb.call(_ok)


class TestExpectedExceptionFiltering:
    def test_unexpected_exception_does_not_trip(self):
        # Only Boom counts as a dependency failure; a ValueError must propagate
        # WITHOUT opening the breaker (mirrors 429/auth errors not tripping it).
        cb = CircuitBreaker("t", failure_threshold=1, expected_exception=Boom)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("not a dependency failure")))
        assert cb.state == CircuitBreaker.CLOSED

    def test_tuple_of_exceptions(self):
        cb = CircuitBreaker("t", failure_threshold=1, expected_exception=(Boom, KeyError))
        with pytest.raises(KeyError):
            cb.call(lambda: (_ for _ in ()).throw(KeyError("k")))
        assert cb.state == CircuitBreaker.OPEN


class TestSuccessResets:
    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("t", failure_threshold=3, expected_exception=Boom)
        for _ in range(2):
            with pytest.raises(Boom):
                cb.call(_boom)
        cb.call(_ok)  # resets the counter
        # Two more failures should NOT open it (count restarted from zero).
        for _ in range(2):
            with pytest.raises(Boom):
                cb.call(_boom)
        assert cb.state == CircuitBreaker.CLOSED
