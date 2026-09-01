"""Per-call resource ceilings.

An agent loop that has gone wrong does not look like a crash. It looks like the same tool
being called a few thousand times, or one call that never returns, and the machine it is
running on has no other defence. Every ceiling here is enforced on the call, not advised in
documentation.

The result-size ceiling matters for a second reason. When output is too large, the tempting
thing to do is truncate it and carry on -- which produces a complete-looking answer built
from a partial result. Here, exceeding the ceiling is a failure. Nothing is truncated and
returned as though it were whole.
"""

from __future__ import annotations

import resource
import subprocess
import sys
from dataclasses import dataclass

#: Whether an address-space ceiling can actually be enforced on this platform.
#:
#: Linux enforces ``RLIMIT_AS`` as you would expect. macOS does not: the kernel does not
#: bound address space the same way, and a limit low enough to be useful stops a CPython
#: child starting at all. Rather than set a limit that does nothing -- or worse, one that
#: breaks every call -- the ceiling is applied only where it works, and
#: :class:`CommandResult` reports whether it was applied so a caller is never told a
#: process was bounded when it was not.
MEMORY_LIMIT_ENFORCEABLE = sys.platform.startswith("linux")


class LimitExceeded(RuntimeError):
    """A call exceeded one of its ceilings.

    Raised rather than handled by truncation, because a truncated result that is reported as
    complete is the failure this package exists to prevent.
    """


@dataclass(frozen=True)
class ResourceLimits:
    """Ceilings applied to a single tool call.

    Defaults are deliberately modest: a tool that genuinely needs more should say so in its
    own registration rather than everything being raised to accommodate it.
    """

    wall_clock_seconds: float = 30.0
    memory_bytes: int = 2 * 1024**3
    max_output_bytes: int = 8 * 1024**2

    def __post_init__(self) -> None:
        if self.wall_clock_seconds <= 0:
            raise ValueError("wall_clock_seconds must be positive")
        if self.memory_bytes <= 0:
            raise ValueError("memory_bytes must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")

    def preexec(self):
        """A ``preexec_fn`` applying the memory ceiling inside the child, or ``None``.

        Applied in the child so a runaway subprocess is stopped by the kernel rather than
        merely reported on afterwards. Returns ``None`` where the platform cannot enforce
        it -- see :data:`MEMORY_LIMIT_ENFORCEABLE` -- so the caller records that the ceiling
        was absent instead of assuming it held.
        """
        if not MEMORY_LIMIT_ENFORCEABLE:
            return None
        limit = self.memory_bytes

        def apply() -> None:  # pragma: no cover - runs in the forked child
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

        return apply

    def check_output_size(self, payload: bytes | str, stream: str = "output") -> None:
        """Refuse an oversized payload rather than trimming it."""
        size = len(payload if isinstance(payload, bytes) else payload.encode("utf-8"))
        if size > self.max_output_bytes:
            raise LimitExceeded(
                f"{stream} is {size} bytes, ceiling is {self.max_output_bytes}; "
                "refusing rather than truncating, because a trimmed result reported as "
                "complete is worse than no result"
            )


@dataclass(frozen=True)
class CommandResult:
    """What a bounded subprocess produced.

    ``memory_limit_applied`` is part of the result rather than an implementation detail:
    a caller that needs the ceiling should be able to see that it was not enforced.
    """

    stdout: str
    stderr: str
    exit_status: int
    complete: bool
    memory_limit_applied: bool = MEMORY_LIMIT_ENFORCEABLE


def run_bounded(
    argv: list[str],
    limits: ResourceLimits,
    stdin: str | None = None,
    cwd: str | None = None,
) -> CommandResult:
    """Run a command under `limits`, reporting truncation and timeouts as incompleteness.

    Never raises on a non-zero exit: a tool that fails is a recorded failure, and the
    provenance layer is what refuses to report it. It does raise if the command cannot be
    started at all, since that is a registration error rather than a tool outcome.
    """
    try:
        completed = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=limits.wall_clock_seconds,
            cwd=cwd,
            preexec_fn=limits.preexec(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        # Whatever the process managed to emit before the ceiling is *not* returned as a
        # result. complete=False is what stops it being reported.
        return CommandResult(
            stdout=stdout,
            stderr=(stderr + f"\ntimed out after {limits.wall_clock_seconds}s").strip(),
            exit_status=124,
            complete=False,
        )
    except FileNotFoundError as exc:
        raise LimitExceeded(f"cannot execute {argv[0]!r}: {exc}") from exc

    try:
        limits.check_output_size(completed.stdout, "stdout")
    except LimitExceeded as exc:
        return CommandResult(
            stdout="",
            stderr=str(exc),
            exit_status=125,
            complete=False,
        )

    return CommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_status=completed.returncode,
        complete=completed.returncode == 0,
    )
