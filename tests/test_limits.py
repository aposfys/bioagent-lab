"""Resource ceilings, and the rule that nothing partial is returned as though it were whole."""

from __future__ import annotations

import sys

import pytest

from bioagent.limits import LimitExceeded, ResourceLimits, run_bounded


def test_defaults_are_sane():
    limits = ResourceLimits()
    assert limits.wall_clock_seconds > 0
    assert limits.memory_bytes > 0
    assert limits.max_output_bytes > 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"wall_clock_seconds": 0},
        {"wall_clock_seconds": -1},
        {"memory_bytes": 0},
        {"max_output_bytes": -5},
    ],
)
def test_nonsensical_ceilings_are_rejected_at_construction(kwargs):
    with pytest.raises(ValueError):
        ResourceLimits(**kwargs)


def test_a_command_that_succeeds_is_complete():
    result = run_bounded([sys.executable, "-c", "print('ok')"], ResourceLimits())
    assert result.exit_status == 0
    assert result.complete
    assert result.stdout.strip() == "ok"


def test_a_nonzero_exit_is_an_outcome_not_an_exception():
    """A failing tool is data. Raising here would turn every tool error into a server error."""
    result = run_bounded([sys.executable, "-c", "raise SystemExit(3)"], ResourceLimits())
    assert result.exit_status == 3
    assert not result.complete


def test_a_timeout_returns_incomplete_and_does_not_pass_off_partial_output():
    # The process prints before hanging, so there *is* partial output to be tempted by.
    script = "import time,sys; print('partial'); sys.stdout.flush(); time.sleep(30)"
    result = run_bounded(
        [sys.executable, "-c", script],
        ResourceLimits(wall_clock_seconds=1.0),
    )
    assert result.exit_status == 124
    assert not result.complete
    assert "timed out" in result.stderr


def test_oversized_output_is_refused_rather_than_truncated():
    script = "print('x' * 100000)"
    result = run_bounded(
        [sys.executable, "-c", script],
        ResourceLimits(max_output_bytes=1000),
    )
    assert not result.complete
    assert result.exit_status == 125
    # Nothing partial is handed back.
    assert result.stdout == ""
    assert "refusing rather than truncating" in result.stderr


def test_check_output_size_accepts_within_ceiling():
    ResourceLimits(max_output_bytes=100).check_output_size("short")


def test_check_output_size_measures_bytes_not_characters():
    """A multi-byte string must not slip past a byte ceiling by counting characters."""
    limits = ResourceLimits(max_output_bytes=10)
    limits.check_output_size("a" * 10)
    with pytest.raises(LimitExceeded):
        limits.check_output_size("é" * 6)  # 12 bytes, 6 characters


def test_a_missing_executable_is_a_configuration_error():
    with pytest.raises(LimitExceeded, match="cannot execute"):
        run_bounded(["definitely-not-a-real-binary-xyz"], ResourceLimits())


def test_the_memory_ceiling_reports_whether_it_was_actually_applied():
    """Claiming a ceiling that the platform ignores would be worse than not having one."""
    from bioagent.limits import MEMORY_LIMIT_ENFORCEABLE

    result = run_bounded([sys.executable, "-c", "print('ok')"], ResourceLimits())
    assert result.memory_limit_applied is MEMORY_LIMIT_ENFORCEABLE
    # And the preexec hook is absent exactly when the ceiling cannot be enforced.
    assert (ResourceLimits().preexec() is not None) is MEMORY_LIMIT_ENFORCEABLE
