"""The call path: validation, permissions, and the guarantee that every result is recorded."""

from __future__ import annotations

import pytest

from bioagent.limits import LimitExceeded, ResourceLimits
from bioagent.provenance import UnattributedResult, assert_reportable, digest
from bioagent.registry import (
    InvalidArguments,
    PermissionClass,
    PermissionDenied,
    Registry,
    Tool,
    ToolNotFound,
    ToolResult,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "count": {"type": "integer", "minimum": 1, "maximum": 10},
        "mode": {"type": "string", "enum": ["fast", "slow"]},
    },
    "required": ["text"],
}


def echo(arguments):
    return ToolResult(payload={"echoed": arguments["text"]})


def make_tool(**overrides) -> Tool:
    defaults = {
        "name": "echo",
        "version": "1.0.0",
        "description": "Echo the input.",
        "input_schema": SCHEMA,
        "handler": echo,
    }
    return Tool(**{**defaults, **overrides})


def test_a_successful_call_is_recorded_and_reportable():
    registry = Registry()
    registry.register(make_tool())

    payload, execution = registry.call("echo", {"text": "hello"})

    assert payload == {"echoed": "hello"}
    assert execution.tool == "echo"
    assert execution.succeeded
    # The whole contract: the payload the caller holds can be vouched for.
    assert assert_reportable(payload, registry.log) is execution


def test_a_value_the_registry_never_produced_is_refused():
    registry = Registry()
    registry.register(make_tool())
    registry.call("echo", {"text": "hello"})

    # Exactly the failure mode this package exists for: a plausible value the pipeline
    # never generated.
    with pytest.raises(UnattributedResult):
        assert_reportable({"echoed": "something the model made up"}, registry.log)


def test_a_failing_tool_is_recorded_but_not_reportable():
    def explode(arguments):
        raise RuntimeError("backend unreachable")

    registry = Registry()
    registry.register(make_tool(name="explode", handler=explode))

    payload, execution = registry.call("explode", {"text": "x"})

    assert not execution.succeeded
    assert "backend unreachable" in payload["error"]
    # Recorded, so the failure is auditable — but refused on the response path.
    assert len(registry.log) == 1
    with pytest.raises(UnattributedResult, match="did not complete"):
        assert_reportable(payload, registry.log)


def test_a_partial_result_is_refused_even_with_a_clean_exit():
    """The dangerous case: exit status 0, truncated data, looks correct."""

    def truncated(arguments):
        return ToolResult(payload={"rows": [1, 2, 3]}, exit_status=0, complete=False)

    registry = Registry()
    registry.register(make_tool(name="truncated", handler=truncated))

    payload, execution = registry.call("truncated", {"text": "x"})

    assert execution.exit_status == 0
    assert not execution.succeeded
    with pytest.raises(UnattributedResult, match="partial results"):
        assert_reportable(payload, registry.log)


def test_privileged_tools_are_denied_by_default():
    registry = Registry()
    registry.register(make_tool(name="writer", permission=PermissionClass.WRITES))

    with pytest.raises(PermissionDenied, match="writes"):
        registry.call("writer", {"text": "x"})
    # Denied before the handler ran, so there is nothing recorded to report.
    assert len(registry.log) == 0


def test_privileged_tools_run_when_enabled_and_are_logged_separately():
    registry = Registry(
        enabled_permissions={PermissionClass.READ_ONLY, PermissionClass.WRITES}
    )
    registry.register(make_tool(name="writer", permission=PermissionClass.WRITES))

    registry.call("writer", {"text": "x"})
    registry.register(make_tool(name="reader"))
    registry.call("reader", {"text": "y"})

    # Read-only traffic does not dilute the privileged record.
    assert registry.privileged_calls == [("writer", "writes")]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "missing required"),
        ({"text": "x", "nope": 1}, "unexpected argument"),
        ({"text": 5}, "must be string"),
        ({"text": "x", "count": "3"}, "must be integer"),
        ({"text": "x", "count": 0}, "must be >= 1"),
        ({"text": "x", "count": 99}, "must be <= 10"),
        ({"text": "x", "mode": "medium"}, "must be one of"),
    ],
)
def test_schema_violations_are_rejected(arguments, message):
    registry = Registry()
    registry.register(make_tool())
    with pytest.raises(InvalidArguments, match=message):
        registry.call("echo", arguments)


def test_a_boolean_is_not_accepted_as_an_integer():
    """bool subclasses int in Python; an integer field must not silently take True."""
    registry = Registry()
    registry.register(make_tool())
    with pytest.raises(InvalidArguments, match="got boolean"):
        registry.call("echo", {"text": "x", "count": True})


def test_an_unknown_tool_raises():
    registry = Registry()
    with pytest.raises(ToolNotFound):
        registry.call("absent", {})


def test_registering_the_same_name_twice_is_refused():
    registry = Registry()
    registry.register(make_tool())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(make_tool())


def test_the_input_digest_distinguishes_different_arguments():
    registry = Registry()
    registry.register(make_tool())
    _, first = registry.call("echo", {"text": "a"})
    _, second = registry.call("echo", {"text": "b"})
    assert first.input_digest != second.input_digest


def test_an_oversized_payload_fails_rather_than_being_trimmed():
    def huge(arguments):
        return ToolResult(payload={"blob": "x" * 5000})

    registry = Registry()
    registry.register(
        make_tool(name="huge", handler=huge, limits=ResourceLimits(max_output_bytes=1000))
    )

    payload, execution = registry.call("huge", {"text": "x"})

    assert not execution.succeeded
    assert "refusing rather than truncating" in payload["error"]
    with pytest.raises(UnattributedResult):
        assert_reportable(payload, registry.log)


def test_a_limit_exceeded_inside_a_handler_becomes_a_recorded_failure():
    def over(arguments):
        raise LimitExceeded("wall clock")

    registry = Registry()
    registry.register(make_tool(name="over", handler=over))
    payload, execution = registry.call("over", {"text": "x"})
    assert execution.exit_status == 125
    assert not execution.succeeded
    assert "wall clock" in payload["error"]


def test_digest_is_order_independent():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
