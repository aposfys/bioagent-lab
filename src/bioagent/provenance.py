"""Execution records, and the check that keeps unattributed numbers off the wire.

The premise of this package is that the agent is unreliable. Rather than reviewing its
output afterwards, the response path refuses to carry any value that is not backed by a
recorded execution, so a fabricated result cannot reach the user even when the model
produces one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class UnattributedResult(RuntimeError):
    """Raised when a value is offered for reporting without a provenance record."""


def digest(payload: Any) -> str:
    """Stable SHA-256 of any JSON-serialisable payload.

    Keys are sorted so that two equal inputs always digest identically; without that, a
    rerun could not be checked against the original.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Execution:
    """One tool run, recorded whether it succeeded or failed."""

    tool: str
    tool_version: str
    input_digest: str
    output_digest: str
    exit_status: int
    complete: bool
    recorded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def succeeded(self) -> bool:
        """A run is usable only if it exited cleanly *and* ran to completion.

        These are separate conditions on purpose: a truncated result with exit status 0 is
        the most dangerous outcome in agentic analysis, because it looks correct.
        """
        return self.exit_status == 0 and self.complete


class ProvenanceLog:
    """Append-only record of executions, keyed by output digest."""

    def __init__(self) -> None:
        self._records: dict[str, Execution] = {}

    def record(self, execution: Execution) -> Execution:
        self._records[execution.output_digest] = execution
        return execution

    def lookup(self, output_digest: str) -> Execution | None:
        return self._records.get(output_digest)

    def __len__(self) -> int:
        return len(self._records)


def assert_reportable(value: Mapping[str, Any], log: ProvenanceLog) -> Execution:
    """Return the execution backing ``value``, or refuse it.

    Called on the response path rather than in a review step, because a guardrail that runs
    after the answer has been sent is not a guardrail.
    """
    output_digest = digest(value)
    execution = log.lookup(output_digest)
    if execution is None:
        raise UnattributedResult(
            f"no execution produced this value (digest {output_digest[:12]}); "
            "refusing to report it"
        )
    if not execution.succeeded:
        raise UnattributedResult(
            f"{execution.tool} did not complete successfully "
            f"(exit {execution.exit_status}, complete={execution.complete}); "
            "partial results are not reported as though they were complete"
        )
    return execution
