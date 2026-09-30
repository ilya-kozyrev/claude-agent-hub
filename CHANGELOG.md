# Changelog

## 0.1.0 — 2026-09-30

First public release.

- `agent spawn / status / send / stop`: detached headless `claude -p` agents with a brief, an inbox, resume after
  exit with unread-message replay, an `EXIT` journal line for runs that end without a status word.
- `jlog` and `jwait`: the stage journal and the single background waiter (journal and file sources, filters,
  `--since` replay, alarms).
- `roles`: role registry by full session id (Claude Desktop, headless and terminal sessions), send budget, broadcast.
- `ask`: owner-question register with default actions, due times, answers, agents' decisions and execution evidence.
- `lock` and the `board_locks` hook: a lock board for merges to main, deploy windows and shared environments, with
  custom rules in `lock-rules.json`.
- `hub takeover / handoff`: one-command hub shift handover.
- `nightq`: a night queue with a permission matrix; optional night-nudge task template.
- `agent-top`: curses console, `--once`, `--json` and the `--widget` HTML for the `/agent-top` chat skill.
- Skills: `hub`, `handoff`, `agent-top`. Hooks: lock guard, owner-question summary at session start, handoff size cap.
