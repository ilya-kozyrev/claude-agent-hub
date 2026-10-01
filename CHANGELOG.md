# Changelog

## 0.2.0 — 2026-10-01

Project configuration: a team's own conventions live in its repository, not in a fork of the plugin.

- **Configuration layers.** The same files are read from `<hub home>/<stage>/`, `<repo>/.agent-hub/` (found from the
  working directory up to the git root) and `<hub home>/`:
  - `config.json` — defaults for the existing settings (`AGENT_HUB_MODEL_MAP`, `AGENT_HUB_DEFAULT_EFFORT`,
    `AGENT_HUB_PERMISSION_MODE`, `CLAUDE_BIN`, `AGENT_INIT_TIMEOUT`, new `AGENT_HUB_DEFAULT_REPO`; hub-wide
    `AGENT_HUB_TZ`, `AGENT_HUB_SEND_CAP`, `AGENT_HUB_NIGHT`, `AGENT_HUB_HANDOFF_MAX_BYTES` from the hub home only).
    Environment variables still win. Unknown keys and broken files are reported on stderr and ignored.
  - `lock-rules.json` — the repository's rules apply to commands run in it (cwd, `cd`, `git -C`), together with the
    hub home's.
  - `brief-footer.md` — appended to the footer of every brief of an agent spawned in that repository.
  - `handoff-facts.sh` — now also found in the repository and the hub home, not only in the stage directory.
  - `takeover.sh` — a project step of `hub takeover`, run as `check` / `apply` and verified like the built-in steps.
- `agent spawn` takes model map, effort, permission mode and CLI settings from the agent's `--cwd` repository.
- `lock take/release --repo` defaults to `AGENT_HUB_DEFAULT_REPO` (else `*`).
- `hub takeover` looks at the `main-merge` lock of every repository: `--take-main-merge` takes the hub repository's,
  the others are reported (0.1.0 looked only at the first one found).
- Review hardening:
  - The lock hook no longer goes quiet on a broken `lock-rules.json`: the file (bad JSON, a bad regex, `kinds` that
    is not a non-empty list of known kinds, a symlink to a missing file, a missing `$AGENT_HUB_LOCK_RULES`) is skipped
    with a warning on stderr and to the user on every command, and the built-in merge guards and the other file
    keep applying. Before, any such error made the hook fail open for every rule, built-ins included.
  - `AGENT_HUB_SEND_CAP` is read when used; a bad value is reported and replaced by 10 instead of breaking every
    tool (and both hooks) at import. `AGENT_HUB_HANDOFF_MAX_BYTES` likewise warns.
  - `hub takeover --take-main-merge` run outside the hub repository no longer adds a second, wildcard `main-merge`
    next to the one taken over from the previous hub (that lock refused merges in every other repository).
  - `lock release` without `--repo`, run from another directory, finds this session's only lock of that kind.
  - `hub takeover` says when it finds no `takeover.sh` in the config layers of its working directory.
- New settings: `AGENT_HUB_TAKE_MAIN_MERGE` (repository: takeover takes the hub repository's main-merge by default;
  without it a free main-merge of a configured hub repository is reported in the digest), `AGENT_HUB_JWAIT_MATCH`
  (hub-wide: extra wake words for the digest's `jwait` and for an agent's status word), `CLAUDE_BIN=desktop` (the
  newest CLI bundled with Claude Desktop, following Desktop updates).
- `HUB-NOTES.md` in the config layers: the team's own hub rules; the takeover digest points at it and the `hub`
  skill reads it before planning. The skill also states that the journal is append-only.
- Night nudge prompt: loads the deferred session tools, takes the time from `date`, calls `nightq` by absolute path.
- Night queue: `request_keep_awake` before `caffeinate`. `hub` skill: the `AWAITING ANSWER` wait pattern, the
  production-script rule, a fixed handoff threshold, a "Project configuration" section. Board and night-queue texts no
  longer claim that `deploy-window` holds merges.

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
