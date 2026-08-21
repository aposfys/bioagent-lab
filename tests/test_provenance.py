"""The guardrails, tested as guardrails: each one must refuse, not warn."""

from __future__ import annotations

import pytest

from bioagent.provenance import (
    Execution,
    ProvenanceLog,
    UnattributedResult,
    assert_reportable,
    digest,
)


def make_execution(value: dict[str, object], *, exit_status: int = 0, complete: bool = True):
    return Execution(
        tool="similarity_search",
        tool_version="0.1.0",
        input_digest=digest({"smiles": "CCO"}),
        output_digest=digest(value),
        exit_status=exit_status,
        complete=complete,
    )


def test_a_recorded_result_is_reportable() -> None:
    log = ProvenanceLog()
    value = {"neighbours": 3, "best_tanimoto": 0.81}
    log.record(make_execution(value))
    assert assert_reportable(value, log).tool == "similarity_search"


def test_a_fabricated_result_is_refused() -> None:
    """The central guarantee: a number no tool produced cannot reach the user."""
    log = ProvenanceLog()
    log.record(make_execution({"neighbours": 3, "best_tanimoto": 0.81}))
    with pytest.raises(UnattributedResult, match="refusing to report"):
        assert_reportable({"neighbours": 3, "best_tanimoto": 0.99}, log)


def test_an_empty_log_reports_nothing() -> None:
    with pytest.raises(UnattributedResult):
        assert_reportable({"anything": 1}, ProvenanceLog())


def test_a_truncated_result_with_a_clean_exit_is_refused() -> None:
    """Exit status 0 with incomplete output is the failure that looks like success."""
    log = ProvenanceLog()
    value = {"neighbours": 3}
    log.record(make_execution(value, exit_status=0, complete=False))
    with pytest.raises(UnattributedResult, match="partial results"):
        assert_reportable(value, log)


def test_a_failed_tool_cannot_be_reported() -> None:
    log = ProvenanceLog()
    value = {"neighbours": 0}
    log.record(make_execution(value, exit_status=1))
    with pytest.raises(UnattributedResult, match="did not complete"):
        assert_reportable(value, log)


def test_digest_is_order_independent_so_reruns_can_be_checked() -> None:
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


def test_digest_distinguishes_different_values() -> None:
    assert digest({"score": 0.81}) != digest({"score": 0.82})
