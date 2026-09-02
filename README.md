# bioagent-lab
An MCP server that can run my pipelines, and cannot invent their results.

[![CI](https://github.com/aposfys/bioagent-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/aposfys/bioagent-lab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Every value an agent can report must be traceable to a recorded execution: tool
name, version, input digest, output digest, exit status. A claim without a
matching provenance record is refused at the API boundary — not flagged in a log,
not appended as a caveat. **The transport refuses to carry unattributed numbers,
so a hallucinated result cannot reach the user even when the model produces one.**

```
export FPSEARCH_BIN=/path/to/fpsearch FPSEARCH_INDEX=/path/to/chembl.idx
make install && make serve
bioagent --list-tools          # what is registered, and what was skipped
make test                      # 48 tests; the ones that matter assert the refusals
```

### It works, end to end

Asking for aspirin's neighbours in a 2.85M-molecule ChEMBL index, through the server:

```json
{
  "reportable": true,
  "provenance": {"tool": "similarity_search", "tool_version": "0.1.0",
                 "input_digest": "a32bd8367026...", "exit_status": 0},
  "result": {
    "hits": [{"id": 25, "tanimoto": 1.0000}, {"id": 3833404, "tanimoto": 0.8889}],
    "engine_report": "5 hits in 31.35ms — examined 247488 of 2854800 (91.3% skipped)"
  }
}
```

CHEMBL25 *is* aspirin, so the top hit at 1.0000 is the search finding the query
itself. Hand the same structure back with one hit changed and the server returns
`"reportable": false` and withholds the payload, because no execution produced
that value.

### Guardrails

- **No unattributed values.** `assert_reportable` sits on the response path, not
  in a review step.
- **No silent partial results.** `complete` is tracked separately from
  `exit_status`, because a truncated result that exits 0 looks correct. Oversized
  output is a failure, never a trim.
- **Read-only by default.** `writes` and `spends` are opt-in per session and
  logged separately.
- **Ceilings per call.** Wall clock, memory and result size. The memory ceiling is
  only enforceable on Linux, and the result says so rather than claiming a bound
  that did not hold.
- **A tool whose backend is absent is not registered**, and startup says why. An
  agent cannot tell "this tool is broken" from "this analysis found nothing".

### Prior work

**Provenance enforcement for LLM agents is an active research area, and the pattern
implemented here is described in it.** This repository is an implementation, not a proposal.

- *From Agent Traces to Trust: A Survey of Evidence Tracing and Execution Provenance in LLM
  Agents* (2026) — defines execution provenance as the typed graph of an agent execution and
  evidence tracing as its projection onto evidence-support relations, and argues trustworthy
  tool use requires tracing why a tool was called, where its arguments came from, and whether
  its output was reliable. That is the model `assert_reportable` enforces.
- *ProvenanceGuard: Source-Aware Factuality Verification for MCP-Based LLM Agents* (2026) —
  consumes MCP traces with stable tool and source IDs, decomposes answers into atomic claims,
  and checks the claim's stated attribution against the routed source. It names
  cross-source conflation as the failure mode: a claim supported *somewhere* in the evidence
  but attributed to the wrong place.
- *Verifiability-First Agents* (2025) — the runtime-rejection design, where an action outside
  the declared tools or lacking attestation is refused rather than logged.

Where this differs is scope rather than principle: refusal sits on the response path of a
working scientific tool server rather than in a verification layer over traces, so a value
that no execution produced cannot leave the process at all. That is an engineering choice
with a real consequence, and it is worth having — but the idea is the field's, not this
repository's.

### More

- [Analysis](ANALYSIS.md) — what was done and why it was done that way
- [Design](docs/DESIGN.md) — why an infrastructure layer rather than another benchmark, the tools, and the layout
