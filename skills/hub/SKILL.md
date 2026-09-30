---
name: hub
description: Tools and rules for a stage hub (coordinator) session that runs headless Claude agents. Load it when you are the hub or coordinator of a stage, when taking over or handing off a hub shift, when spawning or messaging a long-running background agent, and when you need to wait for events — journal lines, an agent's status, a script's question, an alarm.
---

# Stage hub: tools and rules

A **stage** is one stream of work (a release, a migration, a sprint) with its own directory under the hub home
(`$AGENT_HUB_HOME`, default `~/.claude/agent-hub`). The **hub** is the one interactive session that plans the stage,
writes briefs, spawns headless agents and answers them. Everything they share is a file:

| File | Written by | Read by |
|---|---|---|
| `<stage>/coordinator/work/journal-YYYY-MM-DD.md` — one line per event, `- HH:MM [tag] text` | `jlog`, `agent`, `hub`, `roles broadcast` | `jwait`, `agent-top`, humans |
| `<stage>/agents/<role>/` — `brief.md`, `inbox.md`, `log.jsonl`, `meta.json` | `agent spawn/send` and the `claude -p` run | `agent status`, `agent-top` |
| `<stage>/roles.json` — who plays which role, by full session id | `roles`, `agent`, `hub takeover` | `roles`, `jlog` (tag lookup) |
| `<stage>/questions.md` — owner questions and agents' own decisions | `ask` | `ask`, SessionStart hook, `hub` digest |
| `board.md` — locks on shared resources (merges to main, deploys, staging) | `lock`, `hub takeover` | the `board_locks` hook |
| `<stage>/night-queue.md` — work allowed while the owner is away | the hub | `nightq`, the optional night nudge |

The tools are on PATH while the plugin is enabled (`${CLAUDE_PLUGIN_ROOT}/bin`); each has `--help` with the full
syntax. Stage: `--stage`, else `$HUB_STAGE`, else `default`. The hub's tag is `hub-<N>` (N = shift number).

## Taking over a shift

1. `hub takeover --stage <S> --n <N> --session <your full session id> [--handoff <file>]` — one command: the previous
   hub's locks (`--skip-lock stage` if its executor still works under that lock; `--take-main-merge` to take the merge
   role too), `coordinator:` in `night-queue.md`, `roles set hub`, a start line in the journal. A step that does not
   verify stops the command and names the step; a re-run finishes the rest. `--dry-run` first if unsure.
2. The takeover digest (≤ 3 KB) puts § 0 of the handoff next to the `ask` register. Check every "the owner said" in the
   handoff against the register (open questions, owner answers, standing decisions). If they disagree, the register
   wins; ask the owner.
3. Start the first `jwait` — the ready command is in the digest; its `--since` (the handoff time) delivers the lines
   written during the handover. Without `--since` a new tag's first run only marks the journal as read.

Leaving: `hub handoff --stage <S> --n <N>` writes a `HANDOFF-hub-*.md` draft with the facts filled in and TODOs; fill
the TODOs (skill `handoff`). Environment facts come from `<stage>/handoff-facts.sh` if it exists. Locks are not
released — the successor's `hub takeover` takes them. Write the handoff while you still have context to spare.

## Waiting

Waiting is **one** `jwait` in Bash with `run_in_background: true`; the harness wakes you when it exits.
- `jwait --journal --tag hub-<N> --tag hub --match '\b(MERGED|STOP|DONE|BLOCKED|EXIT|QUESTION)\b' --for 2h` —
  lines addressed to the hub and executors' status lines. Your own lines (your tag and its sub-tags `hub-<N>/…`) do not wake you.
- `jwait --file <script output> --match 'AWAITING ANSWER'` — a script's question; a question asked before `jwait`
  started is delivered too.
- `jwait --until 20:23 --note "check the nightly import"` — an alarm; exit 3 and a line `ALARM …`.
- Sources and filters combine in one command. What was read is remembered: lines that arrived while you worked come
  with the next `jwait`, and a rewritten journal does not repeat old lines.

Wake up — handle the block — start the next `jwait`. Journal waits and alarms live only in `jwait`: no Monitor on the
journal, no cron, no `sleep` loops.

## Talking

- `jlog "text"` — a journal line with your tag (`--tag`, `$HUB_TAG` or the registry).
- `roles list | get <role> | set | retire` — the stage's role registry with full session ids. The address for
  SendMessage is only ever `roles get <role>`.
- `roles broadcast --to r1,r2|--all "text"` — "role, id, budget left" rows for SendMessage and one journal line
  `@r1 @r2 text`. After every single send — `roles sent <from> <to>`, a failed one too.
- Claude Desktop pauses a session's outgoing cross-session sends after 10 messages without the user typing in it
  (`roles budget`; after the user writes there — `roles reset <role>`). At budget 0 write `jlog "@<tag> …"`; the
  recipient sees it through `jwait --tag`.
- Owner-question register: `ask search <words…>` — decisions the owner already took on a topic (all stages and
  statuses); `ask digest` — the whole register, one line per decision; `ask add … --default … --due …` — a new
  question with the action you will take if nobody answers; `ask decided` — a decision you took yourself on a matter
  the owner normally decides; `ask close <id> --answer …` — the owner answered; `ask done <id> --evidence "…"` — the
  answer was executed; `ask list --pending` — answers without `done`. `ask add|decided|close|done` stamp the time and
  print a ready journal line: copy the id and time from it.

## Executors

- Executors and stewards stay silent between events. They write to the hub only MERGED / STOP / DONE / BLOCKED / a
  question: the status word, the report path and one sentence. The full report is `work/<tag>-REPORT.md`.
- A wake-up with nothing new is a hub turn of "no action", without analysis.
- Long work (a merge steward, a rehearsal, anything over an hour) is a headless agent, not an in-session sub-agent:
  `agent spawn --role R --cwd DIR --model opus|sonnet|haiku [--effort high] --brief FILE`. It survives the hub's
  handoff, any hub can talk to it, and the old hub closes at handoff instead of staying its host.
  The executor's tag is `hub-<N>-<role>` (a sub-tag `hub-<N>/…` would be filtered out of your own `jwait`; `agent spawn` refuses it).
  A run that ends abnormally or without a status word leaves `EXIT <role>: …` in the journal under its tag.
  `agent status [R]` — alive or not, age of the last event, turns, the last line it said.
  `agent send R "…"` — alive: into its inbox and the journal; process gone: the session resumes with this message and
  replays the unread inbox (`agent status` shows unread messages).
  `agent stop R` — stop it and retire the role. An agent's question arrives as `@hub QUESTION …`; answer with `agent send`.
- Model and effort: pass them per agent. Defaults are configurable (`AGENT_HUB_DEFAULT_EFFORT`, `AGENT_HUB_MODEL_MAP`,
  `AGENT_HUB_PERMISSION_MODE`); headless runs default to `bypassPermissions` because nobody is there to approve a tool
  call — give such an agent a brief that says what it must not touch.
- A brief follows `${CLAUDE_PLUGIN_ROOT}/templates/brief-executor-template.md`; the hub fills "Owner decisions — do not
  reopen" from `ask search <topic words>`. When an executor's result disagrees with a recorded decision, the hub checks
  that section before asking the owner: if the decision exists, apply it, do not ask again.
- A review of one artifact runs at most 3 rounds. After that only blockers with a concrete scenario are accepted; the
  hub decides and records `ask decided`.

## Evidence

- Before claiming a fact about data or systems, look it up (a query, a command, a sub-agent with the schema in its
  brief). A negative result counts only with a positive control on the same query.
- Money, budget and anything that leaves the company go to the owner as `ask add` with a default action, not as the
  hub's decision.

## Watching agents

`agent-top` is a live console (curses) of every agent: state, current action, last words, unread inbox, locks, owner
questions and plan limits; `agent-top --once` prints the same picture as text. In chat, the `agent-top` skill shows it
as a widget.
