"""The MCP server.

Every response leaves through :func:`_reportable_payload`, which asks the provenance layer
to vouch for the value first. That is the whole point of the package: the refusal is on the
transport, so a value the pipeline did not produce cannot reach the caller even if some
future handler tries to return one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Mapping
from typing import Any

from bioagent import __version__
from bioagent.provenance import ProvenanceLog, UnattributedResult, assert_reportable
from bioagent.registry import (
    InvalidArguments,
    PermissionClass,
    PermissionDenied,
    Registry,
    ToolNotFound,
)
from bioagent.tools import build_registry

logger = logging.getLogger("bioagent")


def _reportable_payload(payload: Mapping[str, Any], log: ProvenanceLog) -> str:
    """Render a payload only if an execution backs it.

    ``assert_reportable`` raises for a value with no record and for one whose execution did
    not complete, so a failed or partial tool run is rendered as an explicit refusal rather
    than as a result.
    """
    try:
        execution = assert_reportable(payload, log)
    except UnattributedResult as exc:
        return json.dumps(
            {
                "reportable": False,
                "reason": str(exc),
                "payload_withheld": True,
            },
            indent=2,
        )
    return json.dumps(
        {
            "reportable": True,
            "provenance": {
                "tool": execution.tool,
                "tool_version": execution.tool_version,
                "input_digest": execution.input_digest,
                "output_digest": execution.output_digest,
                "exit_status": execution.exit_status,
                "recorded_at": execution.recorded_at,
            },
            "result": dict(payload),
        },
        indent=2,
    )


def build_server(registry: Registry):
    """Wire a registry up to an MCP server over stdio."""
    import mcp.types as types
    from mcp.server import Server

    server = Server("bioagent")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=tool.name,
                description=(
                    f"{tool.description} "
                    f"[{tool.permission.value}; "
                    f"{tool.limits.wall_clock_seconds:g}s wall clock]"
                ),
                inputSchema=dict(tool.input_schema),
            )
            for tool in registry.tools()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        try:
            payload, _ = registry.call(name, arguments or {})
        except ToolNotFound:
            return [types.TextContent(type="text", text=f"no tool named {name!r}")]
        except (InvalidArguments, PermissionDenied) as exc:
            # Refused before anything ran, so there is nothing to attribute.
            return [types.TextContent(type="text", text=str(exc))]
        return [
            types.TextContent(type="text", text=_reportable_payload(payload, registry.log))
        ]

    return server


async def _serve(registry: Registry) -> None:
    from mcp.server.stdio import stdio_server

    server = build_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bioagent",
        description="MCP server exposing analysis tools with enforced provenance",
    )
    parser.add_argument("--version", action="version", version=f"bioagent {__version__}")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        choices=[p.value for p in PermissionClass],
        help="enable a permission class beyond read_only; repeatable",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="print the registered tools and exit, without starting the server",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s: %(message)s")

    enabled = {PermissionClass.READ_ONLY} | {PermissionClass(value) for value in args.allow}
    registry, skipped = build_registry(enabled_permissions=enabled)

    for note in skipped:
        logger.warning("not registered — %s", note)
    if enabled != {PermissionClass.READ_ONLY}:
        logger.warning(
            "privileged permissions enabled: %s",
            sorted(p.value for p in enabled - {PermissionClass.READ_ONLY}),
        )

    if args.list_tools:
        for tool in registry.tools():
            print(f"{tool.name}\t{tool.permission.value}\t{tool.description}")
        if not registry.names():
            print("(no tools registered; see the warnings above)", file=sys.stderr)
        return 0

    if not registry.names():
        logger.error("no tools registered; refusing to start a server that can do nothing")
        return 1

    logger.info("serving %d tool(s): %s", len(registry.names()), ", ".join(registry.names()))
    asyncio.run(_serve(registry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
