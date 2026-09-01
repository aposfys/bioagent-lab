"""Tool registration, input schemas, permission classes, and the call path.

Every call goes through :meth:`Registry.call`, which digests the input, runs the handler
under its ceilings, records an execution whether it succeeded or failed, and returns a
result the provenance layer can later be asked to vouch for. There is no second path: a
handler is not reachable except through this one, so a tool cannot accidentally return a
value that was never recorded.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from bioagent.limits import LimitExceeded, ResourceLimits
from bioagent.provenance import Execution, ProvenanceLog, digest


class PermissionClass(StrEnum):
    """What a tool is allowed to do.

    Read-only is the default everywhere. Anything that writes, deletes or spends money has
    to be enabled for the session explicitly, and its calls are logged separately, because
    the failure mode of an autonomous agent is not one catastrophic action -- it is a
    hundred small ones nobody was watching.
    """

    READ_ONLY = "read_only"
    WRITES = "writes"
    SPENDS = "spends"


class PermissionDenied(RuntimeError):
    """A tool was called whose permission class is not enabled for this session."""


class ToolNotFound(KeyError):
    """No tool is registered under that name."""


class InvalidArguments(ValueError):
    """Arguments did not satisfy the tool's schema."""


@dataclass(frozen=True)
class ToolResult:
    """What a handler returns.

    ``complete`` is separate from ``exit_status`` on purpose. A handler that ran to
    completion but knows its answer is partial -- a capped result set, a skipped shard --
    must say so here, and the provenance layer will then refuse to report it.
    """

    payload: Mapping[str, Any]
    exit_status: int = 0
    complete: bool = True


@dataclass(frozen=True)
class Tool:
    """One registered tool."""

    name: str
    version: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[[Mapping[str, Any]], ToolResult]
    permission: PermissionClass = PermissionClass.READ_ONLY
    limits: ResourceLimits = field(default_factory=ResourceLimits)

    def validate(self, arguments: Mapping[str, Any]) -> None:
        """Check `arguments` against the declared JSON schema.

        Deliberately a small subset of JSON Schema -- required keys, types, enums, numeric
        bounds -- rather than a dependency. The point is to reject the shapes an LLM
        actually gets wrong, not to be a conformant validator.
        """
        properties: Mapping[str, Any] = self.input_schema.get("properties", {})
        required: list[str] = list(self.input_schema.get("required", []))

        missing = [key for key in required if key not in arguments]
        if missing:
            raise InvalidArguments(f"{self.name}: missing required argument(s) {missing}")

        if not self.input_schema.get("additionalProperties", False):
            unexpected = [key for key in arguments if key not in properties]
            if unexpected:
                raise InvalidArguments(f"{self.name}: unexpected argument(s) {unexpected}")

        type_map: dict[str, type | tuple[type, ...]] = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for key, value in arguments.items():
            spec = properties.get(key)
            if not spec:
                continue
            expected = spec.get("type")
            if expected in type_map:
                # bool is a subclass of int; an integer field must not silently accept True.
                if expected in {"integer", "number"} and isinstance(value, bool):
                    raise InvalidArguments(
                        f"{self.name}: {key} must be {expected}, got boolean"
                    )
                if not isinstance(value, type_map[expected]):
                    raise InvalidArguments(
                        f"{self.name}: {key} must be {expected}, got {type(value).__name__}"
                    )
            if "enum" in spec and value not in spec["enum"]:
                raise InvalidArguments(
                    f"{self.name}: {key} must be one of {spec['enum']}, got {value!r}"
                )
            if (
                "minimum" in spec
                and isinstance(value, int | float)
                and value < spec["minimum"]
            ):
                raise InvalidArguments(f"{self.name}: {key} must be >= {spec['minimum']}")
            if (
                "maximum" in spec
                and isinstance(value, int | float)
                and value > spec["maximum"]
            ):
                raise InvalidArguments(f"{self.name}: {key} must be <= {spec['maximum']}")


class Registry:
    """The tools a server exposes, and the only way to call them."""

    def __init__(
        self,
        log: ProvenanceLog | None = None,
        enabled_permissions: set[PermissionClass] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self.log = log if log is not None else ProvenanceLog()
        # Read-only unless the session says otherwise.
        self.enabled_permissions = enabled_permissions or {PermissionClass.READ_ONLY}
        self.privileged_calls: list[tuple[str, str]] = []

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"a tool named {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFound(name) from exc

    def names(self) -> list[str]:
        return sorted(self._tools)

    def tools(self) -> list[Tool]:
        return [self._tools[name] for name in self.names()]

    def call(
        self, name: str, arguments: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], Execution]:
        """Validate, authorise, run under ceilings, and record.

        Returns the payload together with the execution backing it. The payload is safe to
        pass to ``assert_reportable`` precisely because this method recorded it; nothing
        else in the package writes to the log.
        """
        tool = self.get(name)
        tool.validate(arguments)

        if tool.permission not in self.enabled_permissions:
            raise PermissionDenied(
                f"{tool.name} is {tool.permission.value}; this session enables "
                f"{sorted(p.value for p in self.enabled_permissions)}. "
                "Enable it explicitly if that is intended."
            )
        if tool.permission is not PermissionClass.READ_ONLY:
            # Logged separately, so a session's privileged actions can be reviewed without
            # reading through every read-only call.
            self.privileged_calls.append((tool.name, tool.permission.value))

        # Inputs are hashed before use, so a rerun claiming to reproduce a result can be
        # checked rather than believed.
        input_digest = digest(
            {"tool": tool.name, "version": tool.version, "arguments": dict(arguments)}
        )

        try:
            result = tool.handler(arguments)
        except LimitExceeded as exc:
            result = ToolResult(
                payload={"error": str(exc), "tool": tool.name},
                exit_status=125,
                complete=False,
            )
        except Exception as exc:
            result = ToolResult(
                payload={"error": f"{type(exc).__name__}: {exc}", "tool": tool.name},
                exit_status=1,
                complete=False,
            )

        try:
            tool.limits.check_output_size(str(result.payload), "payload")
        except LimitExceeded as exc:
            result = ToolResult(
                payload={"error": str(exc), "tool": tool.name},
                exit_status=125,
                complete=False,
            )

        execution = self.log.record(
            Execution(
                tool=tool.name,
                tool_version=tool.version,
                input_digest=input_digest,
                output_digest=digest(result.payload),
                exit_status=result.exit_status,
                complete=result.complete,
            )
        )
        return result.payload, execution
