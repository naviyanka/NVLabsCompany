"""The webhook model-run timeout must always fit inside the idempotency lease.

If a run could outlive its lease, a second worker could take the delivery over
while the first is still acting. Startup therefore refuses a timeout that is not
positive or that, with the safety margin, reaches the lease.
"""

from __future__ import annotations

import inspect

import pytest

from nexus.communication.webhook_idempotency import LEASE
from nexus.config import settings
from nexus.config_validator import (
    WEBHOOK_TIMEOUT_MARGIN_SECONDS,
    ConfigurationError,
    enforce_webhook_timeout_policy,
    webhook_timeout_refusal,
)

LEASE_S = LEASE.total_seconds()


def test_lease_and_default_are_the_documented_values():
    assert LEASE_S == 300
    assert settings.webhook_processing_timeout_seconds <= 120
    assert webhook_timeout_refusal(settings.webhook_processing_timeout_seconds, LEASE_S) is None


@pytest.mark.parametrize("timeout", [LEASE_S, LEASE_S + 1, LEASE_S * 4])
def test_timeout_equal_to_or_above_the_lease_is_refused(timeout):
    assert webhook_timeout_refusal(timeout, LEASE_S) == "WEBHOOK_TIMEOUT_NOT_BELOW_LEASE"


def test_the_safety_margin_is_part_of_the_bound():
    edge = LEASE_S - WEBHOOK_TIMEOUT_MARGIN_SECONDS
    assert webhook_timeout_refusal(edge, LEASE_S) == "WEBHOOK_TIMEOUT_NOT_BELOW_LEASE"
    assert webhook_timeout_refusal(edge - 0.5, LEASE_S) is None


@pytest.mark.parametrize("timeout", [1, 60, 120, 200])
def test_a_timeout_with_margin_below_the_lease_is_accepted(timeout):
    assert webhook_timeout_refusal(timeout, LEASE_S) is None


@pytest.mark.parametrize("timeout", [0, -5, float("nan")])
def test_a_non_positive_timeout_is_refused(timeout):
    assert webhook_timeout_refusal(timeout, LEASE_S) == "WEBHOOK_TIMEOUT_INVALID"


def test_startup_refuses_a_timeout_that_reaches_the_lease(monkeypatch):
    monkeypatch.setattr(settings, "webhook_processing_timeout_seconds", LEASE_S)
    with pytest.raises(ConfigurationError) as exc:
        enforce_webhook_timeout_policy()
    assert exc.value.code == "WEBHOOK_TIMEOUT_NOT_BELOW_LEASE"
    assert "WEBHOOK_PROCESSING_TIMEOUT_SECONDS" in str(exc.value)


def test_startup_accepts_a_valid_timeout(monkeypatch):
    monkeypatch.setattr(settings, "webhook_processing_timeout_seconds", 100)
    enforce_webhook_timeout_policy()


def test_the_lifespan_runs_the_check():
    import nexus.main

    assert "enforce_webhook_timeout_policy()" in inspect.getsource(nexus.main.lifespan)
