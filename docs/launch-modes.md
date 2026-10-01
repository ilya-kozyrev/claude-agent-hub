# Choosing how to launch work

A hub can hand a piece of work to six kinds of worker. They differ in what kills them, who can talk to them, what lands
in the hub's context and what they cost. This page gives the decision table the `hub` skill applies, the defaults with
numbers, and the experiments behind them (Claude Code CLI 2.1.274, macOS, 2026-10-01).

## The modes

| | Foreground sub-agent | Background sub-agent | Headless agent (`agent spawn`) | `claude --bg` session | Cloud session | Desktop session |
|---|---|---|---|---|---|---|
| Started by | Agent tool | Agent tool, `run_in_background: true` | `agent spawn` | `claude --bg "<task>"` | `claude --cloud` | the owner or an app tool |
| Runs in | the hub's process; the hub waits | the hub's process; the hub keeps working | its own detached `claude -p` process | the `claude daemon` supervisor | Anthropic's cloud | Claude Desktop |
| Ends with | its turn | its turn; killed when the hub's process exits (E5) | its turn; survives the hub's exit and handoff | `claude stop`; survives the terminal | its task | the owner |
| Who can talk to it | nobody while it runs | only the parent session: `SendMessage` to its id (E8) | any session: `agent send` (inbox while alive, resume after) | any local session by name (E14); the owner with `claude attach` | nobody | the owner |
| What reaches the hub | its whole result | a ~1 KB launch note, a ~0.7 KB completion notice and its result (E4) | one journal status line; the report is a file | nothing unless it writes the journal | a fetched report | nothing |
| Visible in | the hub's UI, `agent-top` | `agent-top` (rows `<parent role>/<id>`), `/tasks` | `agent-top`, `agent status`, the journal | `claude agents` | the cloud UI | Desktop |
| Starting context | ~16k tokens (E13) | ~16k tokens | ~27k tokens + the brief footer | as a new session | — | — |

Cloud sessions are for review today: a bundle made from a GitLab checkout cannot push back. A `claude --bg` session
works (E14) but is not wired into the hub's tools: it has no stream-json log for `agent-top`, no `EXIT` line when it
dies, and `--dangerously-skip-permissions` needs a one-time interactive acceptance.

Claude Code's other parallel mechanisms, and where they sit here:
- **Agent view** (`claude agents`, research preview) is the screen over `claude --bg` sessions: dispatch, watch,
  attach. Same lifetime and limits as the `claude --bg` column.
- **Agent teams** (experimental, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`): a lead session and teammates with their
  own context windows that message each other. Not measured here; the docs warn that token use grows with the number
  of teammates. Use it when the workers must talk to each other, not to the hub.
- **Cross-session messaging** (`SendMessage`/`ListAgents` between sessions on one machine): reaches any running
  session by its name — an interactive one, a busy `claude -p` run (E8), a `claude --bg` session (E14) — but never a
  sub-agent of another session, and nothing once the process is gone. `agent send` keeps working after an agent's
  process ends (it resumes the session) and leaves a journal line; prefer it for headless agents.

## Decision table

Ask the questions in order; the first "yes" decides.

| # | Question | Launch as |
|---|---|---|
| 1 | Is it a review of a pushed branch that may spend the cloud credit? | cloud session |
| 2 | Should the owner talk to it directly? | Desktop session (or `claude --bg` if the owner lives in a terminal) |
| 3 | Must it outlive this hub session — a handoff, a Desktop restart, a night — or run longer than **~30 min**? | `agent spawn` |
| 4 | Must anyone except this hub session talk to it, or must other sessions see its status in the journal? | `agent spawn` |
| 5 | Is the hub near its handoff threshold (see below)? | `agent spawn` |
| 6 | Does the hub need the answer before its next step, and does it fit in **~10 min**? | foreground sub-agent |
| 7 | Otherwise (the hub has other work, ≤ ~30 min, the hub stays up) | background sub-agent |

Other axes:
- **Parallelism.** Background sub-agents run in parallel inside the hub's process (20 at once and 3 levels of
  nesting by default, per the docs; not measured here). Long parallel work is several headless agents, each with its
  own process, journal tag and locks.
- **Cost.** Foreground and background cost the same tokens; neither re-reads the hub's context. What a sub-agent
  costs the hub is what it returns, so ask for a short result (≤ 20 lines) and put the details in a file. A headless
  agent starts ~10k tokens heavier and talks only through the journal and its report. The model is chosen per call:
  long routine work goes to Opus or Sonnet, not to a capped judgement model.
- **Visibility.** Headless agents and the sub-agents of the sessions in the role registry (the hub after
  `hub takeover`, every spawned agent) show in `agent-top`; sub-agents read-only. A sub-agent's state comes from its
  parent's transcript (a completion notice for a background one, the Agent call's result for a foreground one, E18)
  and from whether the parent's process still runs (`~/.claude/sessions/<pid>.json`, E19).

Why ~30 min for a background sub-agent: it dies with the hub's process and only the hub's own session can resume it
(E5, E6, E8). The longer it runs, the likelier a restart, a handoff or a quit app costs the redo. The number is a
judgement; the measured limits are the ones above and the 10-minute ceiling below.

## The hub near its threshold

A background sub-agent cannot be handed over: the successor is another session and cannot message it (E8), and when
the old hub closes it dies (E5). Before `hub handoff`, or once the context crosses the threshold you fixed in advance:
- nothing new starts as a sub-agent that may outlive the hub — it is an `agent spawn`;
- a running background sub-agent is either waited for (its notice is minutes away), or stopped and its remainder
  relaunched with `agent spawn` with the brief and the partial result, or named in the handoff as lost work.
Compaction is not a reason: a sub-agent keeps running through it and its notice arrives afterwards (E7).

## Sub-agents inside a headless agent

A headless agent is a `claude -p` run. When its turn ends it waits for its background sub-agents, but only up to the
CLI's ceiling (10 min by default), then kills them (E10); a sub-agent's own activity does not extend the wait (E11).
`agent spawn` therefore starts every run with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` (wait until they finish —
a 19-minute sub-agent completed, E12; `AGENT_HUB_BG_WAIT_CEILING_MS` sets another value). While they run the agent shows as alive; `agent stop` ends
both. The executor reports for its sub-agents — they do not write the journal, because the hub's `jwait` wakes on any
`DONE` line.

## Starting a headless agent from the hub

Run `agent spawn` as a normal (foreground) Bash call: it returns within seconds, once the agent's run has started.
The docs say that when Claude Code stops a background Bash task — at exit or from `/tasks` — processes it detached
with `setsid` stop too. In the experiment (E16) a spawned agent survived both its parent session's exit and the
killing of the background task that launched it, because it had already been reparented; nothing is gained by
running it in the background, so do not rely on that.

## Journal lines from sub-agents

A sub-agent's shell inherits the parent's environment, `HUB_TAG` and `CLAUDE_CODE_SESSION_ID` included (E2), so a
bare `jlog` writes under the parent's tag. The convention:
- the hub's own background sub-agent may write one final line for the record under a sub-tag:
  `jlog --tag hub-<N>/<name> "DONE <report path>"`; the hub's `jwait` drops its own sub-tags, and the completion
  notice is what wakes the hub;
- an executor's sub-agents write nothing to the journal (above).

## What did not make it into the plugin

- Recording sub-agents in `roles` (kind `subagent`): their id is an address only inside the parent session (E8), no
  other session or a successor hub could use it, and nothing would retire the entry. `agent-top` finds them from the
  transcripts instead.
- `claude --bg` as a backend for `agent spawn`: promising (a supervisor, attach, peers can message it by name), but
  the stream-json log, `EXIT` lines, init check and fixed session id that `agent status`/`agent-top` rely on would need
  a second code path, and a killed session followed by `--resume` started a copy (E14). An open question.

## Experiments

Each run used a headless `claude -p --model haiku` parent in a temp directory that launched one sub-agent through
the Agent tool, with a separate journal root (`AGENT_HUB_HOME` for the plugin's tools); every process and background
session was stopped and removed afterwards.

| # | Behaviour | Evidence |
|---|---|---|
| E1 | A `claude -p` run whose turn ended stays alive until its background sub-agent's turn ends, then runs one more turn on the notice | parent replied `LAUNCHED`, sub-agent ran a 60 s command; process exited after 84 s with two `result` events (`LAUNCHED`, `NOTIFIED`), exit 0 |
| E2 | The sub-agent's shell inherits the parent's environment | its `env` showed the parent's `HUB_TAG`, `HUB_STAGE`, the journal root and `CLAUDE_CODE_SESSION_ID` = the parent's session id; `jlog --tag …` from it wrote the journal, exit 0 |
| E3 | Transcript: `~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl` + `agent-<id>.meta.json` | meta: `agentType`, `description`, `model`, `requestShape: "background"`, `spawnDepth`; lines carry `isSidechain: true`, `agentId`, `timestamp`, and `type` after the nested `message` — no `init`/`result` events, so `agent-top` reads them with a JSON parse, not its stream-json fast path |
| E4 | What the parent sees | launch tool result ~1,050 chars (agent id, output file, "do not read the transcript"); completion `<task-notification>` ~700 chars + the result text, with `<usage>` (sub-agent tokens, tool uses, duration); stream-json shows `task_started` / `task_progress` / `task_notification` events |
| E5 | Parent killed (SIGTERM) while the sub-agent works | parent, the sub-agent's shell and its child process all gone within 3 s; no orphan; the work was never done |
| E6 | Parent resumed (`--resume`) after the kill | the resumed parent first receives a notice `status stopped — didn't finish before the previous session ended`; `SendMessage` to the sub-agent's id resumed it with its history; it redid the step and notified `completed` |
| E7 | `/compact` in the parent while the sub-agent runs | compaction succeeded (28.6k tokens before); the sub-agent finished 50 s later and the parent handled the notice |
| E8 | Another session messages the sub-agent | `SendMessage` to its id from a second session: "No transcript found for agent ID"; `ListAgents` there lists sessions, not sub-agents. The busy headless parent itself was listed as a peer and a message to it was delivered as a new turn |
| E9 | Model and effort | per-call `model: "sonnet"` honoured (resolved by the CLI version — 2.1.274 gave `claude-sonnet-5`); `effort: high` pinned by the agent definition recorded on every sub-agent assistant line |
| E10 | The `-p` wait ceiling | with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=20000` the parent printed "Background tasks still running after 20s; terminating" and exited at 28 s; `subagent_stats.killed.system = 1`; no notice in the transcript |
| E11 | The ceiling counts from the parent's turn end | a sub-agent making a tool call every 12 s was killed at the same 20 s ceiling after its first call |
| E12 | Ceiling 0 | with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` a sub-agent made two 560 s calls; the parent, whose turn ended at 7 s, waited and exited at 1,139 s after handling the notice, exit 0 |
| E13 | Cost shape | sub-agent's first call: ~16k context tokens (system prompt, CLAUDE.md, tools); a fresh headless parent in the same setup: ~27k |
| E14 | `claude --bg` | returns at once; hosted by `claude daemon` → `bg-pty-host`; `claude agents --json` lists it (`kind: background`, `status`, `state`); inherits the launching shell's environment (`jlog` worked); transcript at the usual `projects/<project>/<session>.jsonl`; a peer's `SendMessage` to its name ran a command in it; `--bg -p` refused; `--dangerously-skip-permissions` refused until accepted interactively; a variadic flag (`--allowedTools Bash "<task>"`) swallowed the prompt; after SIGTERM to its process it was not restarted (`state: blocked`) and `claude --bg --resume <id>` started a copy with the history |
| E15 | A sub-agent that backgrounds its own command | its turn ends at once and the parent gets a `completed` notice with an interim result; the backgrounded command is killed when the `-p` parent exits |
| E16 | `agent spawn` and the parent session's exit | a `claude -p` session ran `agent spawn` once as a foreground and once as a background Bash call, then exited after 10 s: both agents (fake CLI holding 45 s) kept running and wrote their `result`; a third spawn inside a background task that was still running (`agent spawn … && sleep 120`) also survived when the CLI killed that task at exit |
| E17 | Bash timeouts | with `BASH_DEFAULT_TIMEOUT_MS=15000` a foreground 40 s command was moved to the background at 15 s (`is_backgrounded`), and a background `jwait --for 12h` was not stopped at 15 s; both were stopped when the `-p` run exited. The docs give background commands 30 min by default (the Bash call's `timeout` raises it, 2 h at most unless `BASH_MAX_TIMEOUT_MS`), but in an interactive-style session on CLI 2.1.284 a background command started without `timeout` was still running at 31 min. The skill's waiting rule passes `timeout: 7200000` with `jwait --for 2h` either way |
| E18 | Foreground sub-agent | `requestShape: "foreground"` in its meta; no `<task-notification>` in the parent; the parent's `tool_result` for the meta's `toolUseId` carries its answer |
| E19 | Which processes run | `~/.claude/sessions/<pid>.json` holds `pid` and `sessionId` for every running CLI process, headless and Desktop-hosted alike; no stale files were left by the runs above |

Docs and experiment: the docs say a `-p` run waits for background sub-agents "until 10 minutes of continuous idle
waiting"; in the experiment the sub-agent's own tool calls did not reset that clock (E11). The docs' limits on
concurrency (20) and nesting depth (3) and the claim that `--bg` sessions survive a reboot were not tested.
