# bioagent-lab — an agent that can run my pipelines, and cannot invent their results

[![CI](https://github.com/aposfys/bioagent-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/aposfys/bioagent-lab/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230)](https://docs.astral.sh/ruff/)

> **Status: skeleton.** The provenance layer and its tests are real; no tools registered yet.

An MCP server that exposes the analysis pipelines in this portfolio as tools an LLM agent
can call — with a provenance layer that makes it structurally impossible to report a number
the pipeline did not produce.

This is deliberately **not** another agent benchmark. Benchmarks for agentic bioinformatics
already exist and agree on the headline: frontier models reach roughly **17%** accuracy on
open-answer analysis tasks in BixBench, and process-level evaluations show the failures are
mostly silent rather than loud. Building a fifth benchmark adds little.

The gap worth filling is the other side: **infrastructure that assumes the agent is
unreliable** and makes its output verifiable anyway.

## The design rule

Every value an agent can report must be traceable to a recorded execution: tool name, tool
version, input digest, output digest, exit status. A claim without a matching provenance
record is refused at the API boundary — not flagged in a log, not appended as a caveat.

This inverts the usual arrangement. Instead of trusting the model and checking afterwards,
the transport refuses to carry unattributed numbers, so hallucinated results cannot reach
the user even when the model produces them.

## What it exposes

| Tool | From | Does |
| --- | --- | --- |
| `curate_chembl` | [`chem-benchmark-audit`](https://github.com/aposfys/chem-benchmark-audit) | Standardise and split a bioactivity set |
| `similarity_search` | [`fpsearch-rs`](https://github.com/aposfys/fpsearch-rs) | Top-*k* Tanimoto over a local index |
| `screen_ligands` | [`dhfr-campaign`](https://github.com/aposfys/dhfr-campaign) | Score a ligand set against a prepared target |
| `compare_variants` | [`pangenome-variant-bench`](https://github.com/aposfys/pangenome-variant-bench) | Stratified variant comparison |

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

## Layout

```
src/bioagent/
  provenance.py   execution records, digests, and the reportability check
  registry.py     tool registration, schemas and permission classes
  server.py       MCP server
  limits.py       per-call resource ceilings
```

```bash
make install && make serve && make test
```
