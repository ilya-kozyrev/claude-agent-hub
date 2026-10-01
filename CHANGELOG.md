# Changelog

## 0.3.0 — 2026-10-01

Agent discipline: the hooks that keep long agent work cheap ship with the plugin, every rule configurable.

- **Context budget** (`hooks/context_budget.py`, on by default): measures the session's context from its transcript
  (a subagent from its own), warns once per step above `AGENT_HUB_CONTEXT_WARN` and points at `agent-hub:handoff`;
  above `AGENT_HUB_CONTEXT_BLOCK` denies the tools in `AGENT_HUB_CONTEXT_BLOCK_TOOLS` unless the call hands work over
  (`AGENT_HUB_CONTEXT_ESCAPE`: a `HANDOFF-*.md` path or `handoff-ok`).
- **Polling guard** (`hooks/polling_guard.py`, on by default, switchable per repository): denies foreground wait loops
  (also inside `bash -c "…"` and text fed to a shell), long bare `sleep` (with `s/m/h/d` units), self-matching `pgrep -f`, and one-off CI status reads from configurable `gh`/`glab` pattern lists
  (`AGENT_HUB_CI_STATUS_DENY` / `_ALLOW`; logs, traces, write calls incl. `-f`/`--field` and a pipeline lookup by sha
  pass; a list whose every pattern is broken falls back to the defaults). Background
  commands, printed text and heredocs are exempt; `# poll-ok: <reason>` passes deliberately. The message names
  `run_in_background`, `jwait` and the project's own wait command (`AGENT_HUB_WAIT_HINT`). Every `jwait` form the hub
  prints passes it (tested, including extra wake words).
- **Delegation dial** (`hooks/delegation.py`, `/delegation` skill, `delegation` CLI; off by default): levels 0-5 per
  session, globally or from the environment; policy text per level from `AGENT_HUB_DELEGATION_LEVELS`; level rules
  from `AGENT_HUB_DELEGATION_RULES` (default: level 0 denies `Agent`, `Task`, `Workflow`).
- **Subagent effort rules** (`AGENT_HUB_EFFORT_RULES`, `bin/subagent_rules.py`): one rule format for the in-session
  `Agent`/`Task` tool and for `agent spawn` (refused with exit 2, the rule named); a shorthand `{"model": "high|xhigh"}`;
  agent definitions are found in the project, `~/.claude/agents` and installed plugins (`agent-hub:worker-high`).
  No model name is built in; `docs/examples/subagent-policy.json` is a complete example.
- Effort rules are read from the user (environment, else hub home) **and** the repository; each set is evaluated on its
  own and any deny wins, so a repository can only add restrictions.
- **Worker subagents** `agent-hub:worker-low|medium|high|xhigh`: pinned effort, model chosen per call.
- `config.json` accepts JSON lists and objects for the list-valued settings; `hubcore.setting_json`.

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
  - `lock release` without `--repo`, run from another directory, finds this session's only lock of that kind;
    with several it names them and exits 1.
  - Takeover: a main-merge the previous hub held in another repository no longer hides the hub repository's free
    one; a main-merge that was wanted but could not be taken is reported. `AGENT_HUB_TAKE_MAIN_MERGE` accepts a JSON
    boolean.
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
