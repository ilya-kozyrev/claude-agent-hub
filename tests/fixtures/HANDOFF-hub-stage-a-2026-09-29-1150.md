# Handoff "Hub stage-a #16" → "Hub stage-a #17" — stage-a — 2026-09-29 11:50 — ENTRY POINT

## 0. First steps for the successor
1. `hub takeover --stage stage-a --n 17 --session <your id>`.
2. Start the first `jwait` from the takeover digest.
3. The builder agent is rebasing; wait for its DONE.

## 1. Where things stand
| What | State | Where it shows |
|---|---|---|
| Builder | rebasing the feature branch | `agent status builder` |

## 2. Queue
1. Review the builder's report.
