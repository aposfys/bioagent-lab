# bioagent-lab — design notes

An MCP server that exposes the analysis pipelines in this portfolio as tools an LLM agent
can call — with a provenance layer that makes it structurally impossible to report a number
the pipeline did not produce.

## Why infrastructure, not another benchmark

This is deliberately **not** another agent benchmark. Benchmarks for agentic bioinformatics
already exist and agree on the headline: frontier models reach roughly **17%** accuracy on
open-answer analysis tasks in BixBench, and process-level evaluations show the failures are
mostly silent rather than loud. Building a fifth benchmark adds little.

The gap worth filling is the other side: **infrastructure that assumes the agent is
unreliable** and makes its output verifiable anyway.

## The design rule

Every value an agent can report must be traceable to a recorded execution: tool name, tool
version, input digest, output digest, exit status. A claim without a matching provenance
record is refused at the API boundary.

This inverts the usual arrangement. Instead of trusting the model and checking afterwards,
the transport refuses to carry unattributed numbers.

## What it exposes

Registered today, when their backends are present:

| Tool | Backend |
| --- | --- |
| `molecule_properties` | RDKit descriptors |
| `fingerprint` | RDKit ECFP, as hex |
| `similarity_search` | [`fpsearch-rs`](https://github.com/aposfys/fpsearch-rs) over a prebuilt index |

Planned, once the pipelines they wrap produce results: `curate_chembl`
([`chem-benchmark-audit`](https://github.com/aposfys/chem-benchmark-audit)), `screen_ligands`
([`dhfr-campaign`](https://github.com/aposfys/dhfr-campaign)), `compare_variants`
([`pangenome-variant-bench`](https://github.com/aposfys/pangenome-variant-bench)).

A tool whose backend is missing is not registered at all, and `build_registry` returns a
note saying why. Registering a tool that fails on first call would leave the agent unable to
distinguish a broken tool from an analysis that legitimately found nothing.

## Guardrails

- **No unattributed values.** Enforced by `provenance.assert_reportable`, which is on the
  response path, not in a review step.
- **No silent partial results.** A tool that fails returns a failure. There is no code path
  that returns a truncated result set as though it were complete — the most dangerous
  failure mode in agentic analysis, because the output looks correct.
- **Read-only by default.** Tools that write, delete, or spend money require explicit
  opt-in per session and are logged separately.
- **Resource ceilings per call.** Wall-clock, memory and result-size limits, so a runaway
  agent loop cannot exhaust the machine.
- **Inputs are digested, not trusted.** Every input is hashed before use, so a rerun that
  claims to reproduce a result can be checked rather than believed.


## Where the ceilings are real and where they are not

The wall-clock and output-size ceilings are enforced everywhere. The memory ceiling is not:
`RLIMIT_AS` behaves as expected on Linux, but macOS does not bound address space the same
way, and a limit low enough to be useful stops a CPython child starting at all.

Rather than set a limit that silently does nothing, `MEMORY_LIMIT_ENFORCEABLE` gates it and
`CommandResult.memory_limit_applied` reports what actually happened. A guardrail you believe
in but that is not running is worse than no guardrail, and this package is not entitled to
that mistake given what it is for.
