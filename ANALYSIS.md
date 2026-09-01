# Analysis

What was built, why it was built that way, and the bug that only CI caught.

## The premise

Benchmarks for agentic bioinformatics already exist and agree: frontier models reach roughly
17% accuracy on open-answer analysis tasks, and the failures are mostly silent rather than
loud. A fifth benchmark adds little. The gap worth filling is infrastructure that **assumes
the agent is unreliable** and makes its output verifiable anyway.

## The design rule, and where it is enforced

Every value an agent can report must trace to a recorded execution: tool, version, input
digest, output digest, exit status. A claim without a matching record is refused **at the
API boundary** — not flagged in a log, not appended as a caveat.

The placement is the whole design. `assert_reportable` sits on the response path, so a
hallucinated result cannot reach the user even when the model produces one. A guardrail that
runs after the answer has been sent is not a guardrail.

`Registry.call` is the only route to a handler. It digests the input, authorises, meters,
runs, and records — whether the tool succeeded or failed. Nothing else in the package writes
to the log, so there is no path by which a value exists without a record.

## Decisions worth stating

**`complete` is separate from `exit_status`.** A truncated result that exits 0 is the
dangerous case: it looks correct. A handler that ran to completion but knows its answer is
partial must say so, and the provenance layer then refuses it.

**Oversized output is a failure, never a trim.** The tempting behaviour is to truncate and
carry on, which produces a complete-looking answer built from a partial result.

**A tool whose backend is absent is not registered at all**, and startup says why. An agent
cannot distinguish "this tool is broken" from "this analysis found nothing", so the
distinction is made at startup where a human can see it.

**Read-only by default**, with privileged classes opt-in per session and logged separately —
because the failure mode of an autonomous agent is not one catastrophic action, it is a
hundred small ones nobody was watching.

**The memory ceiling reports whether it was actually applied.** `RLIMIT_AS` behaves as
expected on Linux; macOS does not bound address space the same way, and a limit low enough
to be useful stops a CPython child starting at all. Rather than set a limit that silently
does nothing, `MEMORY_LIMIT_ENFORCEABLE` gates it and `CommandResult.memory_limit_applied`
reports the truth. A guardrail you believe in but that is not running is worse than no
guardrail, and this package is not entitled to that mistake given what it is for.

## Verified end to end

Against a 2.85M-molecule ChEMBL index built with `fpsearch-rs`: aspirin returns **CHEMBL25
at Tanimoto 1.0000** — CHEMBL25 *is* aspirin, so that is the search finding the query
itself. Hand the same payload back with one hit altered and the server returns
`"reportable": false` and withholds it.

## The bug CI caught

`build_server` used `Server.list_tools` / `Server.call_tool` decorators that do not exist in
the MCP 2.x SDK. **The server never built.** Nothing exercised the path: `--list-tools` does
not construct a server, and the unit test mocked it.

It is rewritten on `MCPServer.add_tool` with explicit typed wrappers — the SDK derives a
tool's schema from its signature and will not accept one directly — and a test now builds
the server and asserts every registered tool appears with a non-empty schema.

The lesson is narrow and worth keeping: a test that mocks the integration point tests
everything except the integration point.

## What is not built

`curate_chembl`, `screen_ligands` and `compare_variants` are planned but unregistered — they
wrap pipelines whose own headline experiments have not been run. Registering a tool that
fails on first call is exactly what the backend-detection rule exists to prevent.
