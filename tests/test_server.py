"""The response path: what actually leaves the server."""

from __future__ import annotations

import json

import pytest

from bioagent.provenance import ProvenanceLog
from bioagent.registry import Registry, Tool, ToolResult
from bioagent.server import _reportable_payload, main
from bioagent.tools import build_registry


def make_registry() -> Registry:
    registry = Registry()
    registry.register(
        Tool(
            name="echo",
            version="1.0.0",
            description="Echo.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda arguments: ToolResult(payload={"echoed": arguments["text"]}),
        )
    )
    return registry


def test_a_recorded_result_is_rendered_with_its_provenance():
    registry = make_registry()
    payload, execution = registry.call("echo", {"text": "hi"})

    rendered = json.loads(_reportable_payload(payload, registry.log))

    assert rendered["reportable"] is True
    assert rendered["result"] == {"echoed": "hi"}
    assert rendered["provenance"]["tool"] == "echo"
    assert rendered["provenance"]["output_digest"] == execution.output_digest
    # An input digest means a rerun can be checked rather than believed.
    assert rendered["provenance"]["input_digest"] == execution.input_digest


def test_an_unattributed_value_is_withheld_not_rendered():
    log = ProvenanceLog()
    rendered = json.loads(_reportable_payload({"invented": 42}, log))

    assert rendered["reportable"] is False
    assert rendered["payload_withheld"] is True
    # The refusal must not leak the value it refused.
    assert "42" not in json.dumps(rendered["reason"])
    assert "invented" not in json.dumps(rendered)


def test_a_failed_execution_is_withheld():
    registry = Registry()
    registry.register(
        Tool(
            name="broken",
            version="1.0.0",
            description="Always fails.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda arguments: ToolResult(
                payload={"rows": []}, exit_status=1, complete=False
            ),
        )
    )
    payload, _ = registry.call("broken", {})
    rendered = json.loads(_reportable_payload(payload, registry.log))
    assert rendered["reportable"] is False


def test_build_registry_reports_what_it_skipped(monkeypatch):
    monkeypatch.delenv("FPSEARCH_BIN", raising=False)
    monkeypatch.delenv("FPSEARCH_INDEX", raising=False)
    monkeypatch.setattr("bioagent.tools._fpsearch_binary", lambda: None)

    registry, skipped = build_registry()

    assert any("similarity_search" in note for note in skipped)
    # A tool with no backend is absent, not registered-and-broken.
    assert "similarity_search" not in registry.names()


def test_list_tools_exits_cleanly(capsys):
    assert main(["--list-tools"]) == 0


def test_server_refuses_to_start_with_no_tools(monkeypatch):
    monkeypatch.setattr(
        "bioagent.server.build_registry", lambda **kwargs: (Registry(), ["all skipped"])
    )
    # Starting a server that can do nothing looks healthy and answers nothing; refuse instead.
    assert main([]) == 1


@pytest.mark.skipif(
    not build_registry()[0].names(), reason="no backends available in this environment"
)
def test_registered_tools_have_well_formed_schemas():
    registry, _ = build_registry()
    for tool in registry.tools():
        assert tool.input_schema["type"] == "object"
        assert "properties" in tool.input_schema
        for name in tool.input_schema.get("required", []):
            assert name in tool.input_schema["properties"]


def test_the_mcp_server_actually_builds_with_real_schemas():
    """Regression: the SDK's server API changed and `build_server` raised on import-time
    decorators that no longer exist. Nothing else exercised this path."""
    import asyncio

    registry, _ = build_registry()
    if not registry.names():
        pytest.skip("no backends available in this environment")
    server = build_server(registry)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == set(registry.names())
    for tool in tools:
        # A schema derived from the wrapper signature, not an empty placeholder.
        assert tool.input_schema.get("properties")
