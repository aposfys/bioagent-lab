# bioagent-lab
An MCP server that can run my pipelines, and cannot invent their results.

[![CI](https://github.com/aposfys/bioagent-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/aposfys/bioagent-lab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Every value an agent can report must be traceable to a recorded execution: tool name, tool version, input digest, output digest, exit status. A claim without a matching provenance record is refused at the API boundary — not flagged in a log, not appended as a caveat. The transport refuses to carry unattributed numbers, so a hallucinated result cannot reach the user even when the model produces one.

### It works, end to end

```
export FPSEARCH_BIN=/path/to/fpsearch FPSEARCH_INDEX=/path/to/chembl.idx
make install && make serve
```

Asking for aspirin's neighbours in a 2.85M-molecule ChEMBL index, through the server:

```json
{
  "reportable": true,
  "provenance": {
    "tool": "similarity_search",
    "tool_version": "0.1.0",
    "input_digest": "a32bd8367026...",
    "exit_status": 0
  },
  "result": {
    "hits": [
      {"id": 25,      "tanimoto": 1.0000},
      {"id": 3833404, "tanimoto": 0.8889},
      {"id": 350343,  "tanimoto": 0.8571}
    ],
    "engine_report": "5 hits in 31.35ms — examined 247488 of 2854800 (91.3% skipped)"
  }
}
```

CHEMBL25 *is* aspirin, so the top hit at 1.0000 is the search finding the query itself. Hand the same structure back with one hit changed and the server returns `"reportable": false` and withholds the payload, because no execution produced that value.

### Tools

| Tool | Backend | Permission |
| --- | --- | --- |
| `molecule_properties` | RDKit descriptors | read-only |
| `fingerprint` | RDKit ECFP, as hex | read-only |
| `similarity_search` | [`fpsearch-rs`](https://github.com/aposfys/fpsearch-rs) over a prebuilt index | read-only |

A tool whose backend is absent is **not registered**, and startup says why. An agent cannot tell "this tool is broken" from "this analysis found nothing", so that distinction is made where a human can see it.

```
bioagent --list-tools          # what is registered, and what was skipped
bioagent --allow writes        # privileged classes are opt-in, per session
```

### Guardrails

- **No unattributed values.** `assert_reportable` sits on the response path, not in a review step.
- **No silent partial results.** `complete` is tracked separately from `exit_status`, because a truncated result that exits 0 is the dangerous case — it looks correct. Oversized output is a failure, never a trim.
- **Read-only by default.** `writes` and `spends` need explicit opt-in and are logged separately from read-only traffic.
- **Ceilings per call.** Wall clock, memory and result size. The memory ceiling is only enforceable on Linux, and the result says so rather than claiming a bound that did not hold.
- **Inputs are digested, not trusted**, so a rerun claiming to reproduce a result can be checked.

48 tests. The ones that matter assert the refusals: a fabricated value, a failed tool, and a partial result with a clean exit are each withheld.

### Layout

```
src/bioagent/
  provenance.py   execution records, digests, and the reportability check
  registry.py     tool registration, schema validation, permissions, the call path
  limits.py       per-call wall-clock, memory and output ceilings
  tools.py        the registered tools and their backend detection
  server.py       the MCP server; every response goes through the provenance check
```

### Design notes

- [Analysis: what was done, and why it was done that way](ANALYSIS.md)
[Why an infrastructure layer rather than another benchmark](docs/DESIGN.md)
