# bioagent-lab
An MCP server that can run my pipelines, and cannot invent their results.

[![CI](https://github.com/aposfys/bioagent-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/aposfys/bioagent-lab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Status: skeleton.** The provenance layer and its tests are real. No tools are registered yet, and the server itself is not written.

Every value an agent can report must be traceable to a recorded execution: tool name, tool version, input digest, output digest, exit status. A claim without a matching provenance record is refused at the API boundary — not flagged in a log, not appended as a caveat. The transport refuses to carry unattributed numbers, so hallucinated results cannot reach the user even when the model produces them.

### Running it
```
make install && make test
make serve        # not implemented yet
```

### Layout
```
src/bioagent/
  provenance.py   execution records, digests, and the reportability check
```
Planned: `registry.py` (tool registration, schemas, permission classes), `server.py` (the MCP server), `limits.py` (per-call resource ceilings).

### Design notes
[Why an infrastructure layer rather than another benchmark, the tools it will expose, and the guardrails](docs/DESIGN.md)
