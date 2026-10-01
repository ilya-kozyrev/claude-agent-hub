---
name: hub
description: Tools and recommended rules for a stage hub — the one interactive session that plans a stream of work and runs headless Claude agents. Load it when you are the hub of a stage, when starting a stage, taking over or handing off a hub shift, when spawning or messaging a long-running background agent, when you need a review of a change, and when you need to wait for events — journal lines, an agent's status, a script's question, an alarm. Also load it when the user mentions agent-hub or "the hub skill", or asks you to plan work for agents or to run work through agents.
---

# Stage hub: tools and recommended rules

## First commands

Do these before anything else, in this order:

1. `hub start --stage <S> --session "$CLAUDE_CODE_SESSION_ID"` — S is a short name for the goal (*Starting a stage*). If
   `hub` answers with an error such as `invalid choice` or `not a git command`, another `hub` (GitHub CLI) is ahead of
   the plugin's on PATH: run `${CLAUDE_PLUGIN_ROOT}/bin/hub start …` and tell the owner in one line.
2. `ask search <words of the goal>` — decisions already on record are settled.
3. One round of questions, each as "Q1 … → Recommendation: …", then a plan (*Planning a stage*). Write no code and
   start no agents before the owner approves the plan.

A **stage** is one stream of work (a release, a migration, a sprint) with its own directory under the hub home
(`$AGENT_HUB_HOME`, default `~/.claude/agent-hub`). The **hub** is the one interactive session that plans the stage,
writes briefs, spawns headless agents and answers them. The **owner** is the person the hub works for. Everything
they share is a file:

| File | Written by | Read by |
|---|---|---|
| `<stage>/coordinator/work/journal-YYYY-MM-DD.md` — one line per event, `- HH:MM [tag] text` | `jlog`, `agent`, `hub`, `roles broadcast` | `jwait`, `agent-top`, humans |
| `<stage>/agents/<role>/` — `brief.md`, `inbox.md`, `log.jsonl`, `meta.json` | `agent spawn/send` and the `claude -p` run | `agent status`, `agent-top` |
| `<stage>/roles.json` — who plays which role, by full session id | `roles`, `agent`, `hub start/takeover` | `roles`, `jlog` (tag lookup) |
| `<stage>/questions.md` — owner questions and agents' own decisions | `ask` | `ask`, SessionStart hook, `hub` digest |
| `board.md` — locks on shared resources (merges to main and whatever the project names) | `lock`, `hub takeover` | the `board_locks` hook |

The tools are on PATH while the plugin is enabled (`${CLAUDE_PLUGIN_ROOT}/bin`, after the user's own entries: an older
command of the same name — GitHub CLI `hub` from Homebrew, an old `jlog` — can answer instead; if `hub start` or the
session start says so, call the tools as `${CLAUDE_PLUGIN_ROOT}/bin/<tool>` and tell the owner in one line); each has
`--help` with the full syntax. Stage: `--stage`, else `$HUB_STAGE`, else `default`. The hub's tag is `hub-<N>` (N = shift number, derived).

**Minimal mode.** One hub and a few agents need `hub start` once (it gives the hub its journal tag) and then three
tools: `agent` (spawn, status, send, stop), `jlog` and `jwait`. `roles`, `ask`, `lock`, `hub takeover/handoff` and the
handoff skill matter once you have more than one interactive session, more than one shift, or a shared resource;
leave them until then.

## Starting a stage

`hub start --stage <S> --session <your full session id>` — once, by the first hub of a new stage: creates the stage
directory, registers you as `hub-1`, writes the start line and prints the first `jwait`. The session id is
`$CLAUDE_CODE_SESSION_ID` in a terminal session (`echo $CLAUDE_CODE_SESSION_ID`); in Claude Desktop, the `local_…` id of
the session. Run it from the project's checkout so its `.agent-hub/` is found. If that checkout has no `.agent-hub/`
yet, offer the `agent-hub:setup` skill: it asks which shared resources the project has and writes the lock rules.
`hub start` prints an ATTENTION line when the Claude Code CLI is older than 2.1.285 (the model aliases then resolve to
older models: tell the owner to update Claude Code) or when a same-named command shadows one of the plugin's tools.

## Taking over a shift

1. `hub takeover --stage <S> --session <your full session id> [--handoff <file>]` — one command: the previous hub's
   locks (`--skip-lock <resource>` if its executor still works under that lock; `--take-main-merge` to take the merge
   role too; `AGENT_HUB_TAKE_MAIN_MERGE=true` in the repository's config makes that the default), `roles set hub`, a
   start line in the journal (and `coordinator:` of the night queue, if the stage has one). Your number is the
   registered hub's + 1 (or the successor named in the handoff); `--n` overrides. A step that does not verify stops
   the command and names the step; a re-run finishes the rest. `--dry-run` first if unsure.
2. The takeover digest (≤ 3 KB) puts § 0 of the handoff next to the `ask` register. Check every "the owner said" in the
   handoff against the register. If they disagree, the register wins; ask the owner.
3. Start the first `jwait` — the ready command is in the digest; its `--since` (the handoff time) delivers the lines
   written during the handover.
4. Read the project's hub rules and notes before planning (the digest names them): `hub-rules.md` (overrides of the
   recommended rules below) and `HUB-NOTES.md` (what the team knows: what goes to the owner, how data claims are
   checked). Run `hub takeover` from the project's checkout: the project layer is found from the working directory.

Leaving: `hub handoff --stage <S>` writes a `HANDOFF-hub-*.md` draft with the facts filled in and TODOs; fill the TODOs
(skill `handoff`). Locks are not released — the successor's `hub takeover` takes them. It first looks for sub-agents of
your own session (`--session`, else the registered hub's and the session you run it in) that still run and refuses —
exit 2, listing id, description and age — because they die with you and the successor cannot message them; the ways out
are under *Choosing how to launch work*.

## Waiting

Waiting is **one** `jwait` in Bash with `run_in_background: true`; the harness wakes you when it exits. Give that Bash
call `timeout: 7200000` and keep `--for` at 2h or less: the docs give a background command 30 min without a `timeout`
and 2 h at most (`BASH_MAX_TIMEOUT_MS` raises it), then Claude Code stops it and tells you (CLI 2.1.284 did not stop one
at 30 min — do not rely on either). A stopped `jwait` loses no lines once its tag has run before: the next one
delivers them.
- `jwait --journal --tag hub-<N> --tag hub --match '\b(MERGED|STOP|DONE|BLOCKED|EXIT|QUESTION)\b|AWAITING ANSWER' --for 2h` —
  lines addressed to the hub, agents' status lines and script questions echoed into the journal. Your own lines (your
  tag and its sub-tags `hub-<N>/…`) do not wake you. The digest prints this command with the team's extra wake words
  (`AGENT_HUB_JWAIT_MATCH`) already added; copy it from there. `--for` defaults to 2h, the longest a background Bash
  task is guaranteed. Called with `--caller <session id>` instead of as the hub's tag (no `HUB_TAG`, no registry
  entry for the session), `jwait` does not know your tag: add `--exclude-tag hub-<N>`, or your own `@agent` messages
  wake you.
- `jwait --file <script output> --match 'AWAITING ANSWER'` — a script's question; one asked before `jwait` started is
  delivered too.
- `jwait --until 20:23 --note "check the nightly import"` — an alarm; exit 3 and a line `ALARM …`.
- Sources and filters combine in one command. What was read is remembered: lines that arrived while you worked come
  with the next `jwait`.

Wake up — handle the block — start the next `jwait`. Journal waits and alarms live only in `jwait`: no Monitor on the
journal, no cron, no `sleep` loops.

## Talking

- `jlog "text"` — a journal line with your tag (`--tag`, `$HUB_TAG` or the registry). The journal is append-only:
  never rewrite or delete a line; correct it with a new line that says what it corrects. When you write into another
  stage's journal, use your own tag (`--tag`), not `hub`: that stage's `jwait --tag hub` treats `hub` lines as its own
  and does not wake.
- `roles list | get <role> | set <role> <id> | retire` — the stage's role registry with full session ids; `set` infers
  the kind from the id (`local_…` = Claude Desktop, a uuid = terminal). The address for SendMessage between
  interactive sessions is only ever `roles get <role>`. `roles broadcast --to r1,r2|--all "text"` — rows for
  SendMessage and one journal line `@r1 @r2 text`.
- Owner-question register: `ask search <words…>` — decisions the owner already took on a topic; `ask digest` — the
  whole register, one line per decision; `ask add … --default … --due …` — a new question with the action you will
  take if nobody answers; `ask decided` — a decision you took yourself on a matter the owner normally decides;
  `ask close <id> --answer …` — the owner answered; `ask done <id> --evidence "…"` — the answer was executed;
  `ask list --pending` — answers without `done`.

## Planning a stage: grill before you brief

A brief can only carry decisions that were made. Before proposing a plan for a new stage or a new piece of work,
settle the open decisions with the owner, in this order:

1. `ask search <topic words>` — decisions already on record are settled; do not ask them again.
2. **Grill the owner** with the `grilling` skill (the recommended companion plugin `mattpocock-skills`, see the README).
   It walks the decision tree in rounds: every question numbered, each with your recommended answer; facts you can look
   up yourself go to a sub-agent instead of to the owner. If the skill is not installed, say once how to add it
   (`/plugin marketplace add mattpocock/skills`, then `/plugin install mattpocock-skills@mattpocock`) and grill by hand
   the same way: rounds of numbered questions, a recommendation for each, until nothing is left silently assumed.
3. Record each answer, so the next hub and every brief inherit it: `ask add … "<question>"` then
   `ask close <id> --answer "<answer>"`. A matter the owner left to you is `ask decided`.
4. Only then propose the plan and the briefs; their "Owner decisions — do not reopen" section comes from
   `ask search`, not from memory.

For an owner who is not technical, one question is mandatory: "How will you open the result, and where should it live?",
with a recommendation. For something that runs in a browser, recommend a static site (GitHub Pages or an Artifact),
not "run a server on your Mac": a server dies with the laptop and the owner cannot restart it. Hand the result over so
that the owner does not have to look for it: open it yourself (`open <path>` on macOS) or give a `file://` link, never
a long path to find and double-click.

Put every question in the owner's words, about the product and what they will see: no canvas, localStorage, branch,
worktree, commit or push to an owner who is not technical. Purely technical choices (canvas or DOM, localStorage, branch
names) are yours: decide, and record each with `ask decided`, so it stays contestable.

Ask the owner nothing about process: agents or not, worktrees, commits. Pick the launch by the criteria of "Choosing how
to launch work". If you decide to write a change yourself, say so in one line with the reason ("one file, nothing to
wait on: I write it myself") and record it with `ask decided`.

Skip the grilling for a task whose decisions are all on record or that the owner specified completely; say so in one
line.

## Choosing how to launch work

Decide from what is visible before the start — what the work does and who must reach it. The first "yes" decides
(table, modes and the experiments behind them: `${CLAUDE_PLUGIN_ROOT}/docs/launch-modes.md`). Estimated duration is a
hint, never the criterion: a hub cannot estimate task time reliably. The owner is not asked which launch to use. When
no row applies — a small change with nothing to wait on and nobody else to reach it — the hub may write it itself: one
line with the reason, and `ask decided` (*Planning a stage*).

1. **A review** → `hub reviewer --for <class>`, then start what it prints (*Reviews*, below).
2. **The owner should talk to it** → a Desktop session, or `claude --bg` for an owner who lives in a terminal.
3. **It commits or pushes, waits on CI, a deploy or another party, touches production, or must be reachable by
   someone other than this hub** → `agent spawn`. Always so when the hub is near its handoff threshold.
4. **Read-only, the answer is a short digest, nothing external to wait on** (read a log, check a fact, probe an
   environment, summarise a file) → a sub-agent: **foreground** when the hub has nothing else to do until the answer,
   otherwise **background** (`run_in_background: true`).

- A background sub-agent lives in the hub's process: it dies when that process exits, and only this session can
  message or resume it (SendMessage to its id). Compaction does not hurt it. Ask it for a short result (≤ 20 lines,
  details in a file): its completion notice and result land in your context.
- **Every sub-agent brief ends with a call budget:** "if not done after N tool calls, stop and return a partial result
  and what is left". Recommended N: 40 for a probe or a read, up to 80 for a wide read-only investigation; it is a
  recommendation, set yours in `hub-rules.md`. *Why:* nobody watches a sub-agent; without a bound a confused one runs
  until its context is full, and the hub pays for it.
- **`hub handoff` refuses while a sub-agent of your session still runs** (exit 2; it lists id, description and age).
  Three ways out, per sub-agent: wait for it (its notice is minutes away); stop it and re-launch the rest with
  `agent spawn`, with its brief and the partial result; or record it as lost — `hub handoff --allow-live-subagents`
  writes the list into the draft's TODO section.
- Its shell inherits your `HUB_TAG`: if it journals, one final line `jlog --tag hub-<N>/<name> "DONE <path>"` (your
  `jwait` ignores your sub-tags; the notice wakes you). An executor's sub-agents do not journal — its `DONE` reports
  for them, and any `DONE` line wakes the hub.
- A headless agent may use background sub-agents: `agent spawn` lifts the CLI's 10-minute wait ceiling for them
  (`AGENT_HUB_BG_WAIT_CEILING_MS`). `agent-top` lists the sub-agents of registered sessions as `<role>/<id>`, read-only.

### Reviews

`hub reviewer --for <class>` walks the configured reviewers (`AGENT_HUB_REVIEWERS`, default one ordinary `agent
spawn`) and prints the first that is available now and exactly how to start it: an `agent spawn --role review-… --brief
<BRIEF>` line, or "load skill `<skill>`" for a reviewer skill the user plugged in. Write the brief from
`${CLAUDE_PLUGIN_ROOT}/templates/brief-review.md`, start the reviewer as printed, and **verify each finding against the
code** before acting on it — a review is a colleague's opinion. Classes, the config, the skill reviewer contract:
`${CLAUDE_PLUGIN_ROOT}/docs/reviewers.md`.

## Executors

- Work that commits, pushes or waits (a merge steward, a rehearsal, a CI wait — see "Choosing how to launch work") is
  a headless agent, not an in-session sub-agent:
  `agent spawn --role R --cwd DIR --model opus|sonnet|haiku|fable [--effort high] --brief FILE [--worktree [BRANCH]]`.
  It survives the hub's handoff and any hub can talk to it. The executor's tag is `hub-<N>-<role>` (a sub-tag
  `hub-<N>/…` would be filtered out of your own `jwait`; `agent spawn` refuses it). A run that ends abnormally or
  without a status word leaves `EXIT <role>: …` in the journal under its tag.
  `agent status [R]` — alive or not, the model it runs on, age of the last event, turns (the last run's next to the total
  after a resume), the last line it said, its worktree.
  `agent send R "…"` — alive: into its inbox and the journal; process gone: the session resumes with this message and
  replays the unread inbox. `agent stop R` — stop it and retire the role. An agent's question arrives as
  `@hub QUESTION …`; answer with `agent send`.
- **Background processes.** An executor lists the processes it started in the background (servers, watchers) in its
  report and stops them before `DONE`. At handoff the hub checks for listening ports left by the project
  (`lsof -iTCP -sTCP:LISTEN`) and stops what the project started and nobody needs.
- **Worktrees.** Two agents writing in one checkout overwrite each other's files. Give every agent that writes code
  `--worktree [BRANCH]` (default branch `agent/<role>`): it runs in an existing worktree of that branch, or in
  `<repo>/.worktrees/<branch>` of the main repository — one place per repository, excluded in `.git/info/exclude`.
  `agent spawn --worktree` refuses a repository with no commits: in a new, empty one the hub makes the first commit
  itself and says so in one line.
  Nothing removes a worktree; at handoff list them (`git worktree list`) and remove the finished ones
  (`git worktree remove <path>`).
- Model and effort: pass them per agent. An alias (`opus`, `sonnet`, `haiku`, `fable`) is resolved by the CLI to its
  latest model, so read the id in `agent spawn`'s journal line; if `agent spawn` or `hub start` warns that the CLI is
  older than 2.1.285, tell the owner to update Claude Code (an old CLI runs older models). Defaults are configurable
  (`AGENT_HUB_DEFAULT_EFFORT`, `AGENT_HUB_MODEL_MAP` — an opt-in pin, `AGENT_HUB_PERMISSION_MODE`); headless runs default to `bypassPermissions` because nobody is there to approve a tool
  call — give such an agent a brief that says what it must not touch.
- A brief follows `${CLAUDE_PLUGIN_ROOT}/templates/brief-executor-template.md` (short); the advanced one,
  `brief-executor-advanced.md`, adds production permissions, size limits and evidence rules for teams that need them.
  The hub fills "Owner decisions — do not reopen" from `ask search <topic words>`. When an executor's result disagrees
  with a recorded decision, the hub checks that section before asking the owner.

## Locks

A lock is on a named resource. `main-merge` is built in: merges into, and pushes to, the protected branches are
refused to everyone but its holder. Every other resource — a deploy window, a staging environment, a migration head,
a shared test database — is named by the project in `lock-rules.json` (`<repo>/.agent-hub/` or the hub home), with
the commands that touch it. `lock rules` lists what applies where you are; `lock take <resource> --until … --why …`
refuses a name nobody configured and prints the known ones; `lock rules check "<command>"` shows which lock would
refuse a command. To set the resources up, use the `agent-hub:setup` skill.

## Project configuration

A repository can carry its own hub conventions in `<repo>/.agent-hub/` (the hub home and `<hub home>/<stage>/` hold
the same files): `config.json` (defaults: model map, effort, permission mode, the lock repo, the reviewers), `lock-rules.json`
(shared resources and their commands), `brief-footer.md` (appended to every brief of an agent spawned with `--cwd` in
that repository), `handoff-facts.sh` (the § 1 rows of `hub handoff`), `takeover.sh` (an extra verified step of
`hub takeover`), `hub-rules.md` (overrides of the recommended rules below) and `HUB-NOTES.md` (the team's knowledge).
Read `hub-rules.md` from every layer — hub home, then the repository, then the stage directory; a later file wins on
the same subject — and `HUB-NOTES.md` before planning at all.

## Recommended hub rules

These are the defaults of the plugin's author, each paid for by an incident or a bill. Follow them unless
`hub-rules.md` says otherwise; a rule there replaces the one below on the same subject and adds anything new
(example: `${CLAUDE_PLUGIN_ROOT}/templates/hub-rules-example.md`).

1. **Agents stay silent between events.** An executor writes to the hub only `DONE` (finished), `BLOCKED` (cannot go
   on), `STOP` (its brief's stop condition hit), `MERGED` (a merge steward merged a PR) or a `QUESTION`: the status
   word, the report path and one sentence; the full report is `work/<tag>-REPORT.md`. *Why:* every line wakes the hub,
   and every wake-up re-reads the hub's whole context.
2. **A wake-up with nothing new is a turn of "no action"**, without analysis. *Why:* the same — a hub that thinks
   aloud on every wake-up spends its context on nothing.
3. **Work that commits or pushes, waits on something external, touches production or must be reachable by others is a
   headless agent.** *Why:* an in-session sub-agent belongs to its parent session — another session cannot address it
   and it does not carry over to the next hub; a headless one has its own session id, keeps working through a handoff
   and any hub can message it.
4. **A change to a production script is written by an executor and reviewed; the hub does not write it.** *Why:* the
   hub's context is the stage's memory; spending it on code costs the plan, and a hub reviewing its own code is not a
   review.
5. **A review of one artifact runs at most 3 rounds.** After that only blockers with a concrete failure scenario are
   accepted; the hub decides and records `ask decided`. *Why:* later rounds find style, not bugs, and each costs a
   full read.
6. **Write the handoff at a context size fixed in advance — about a third of the model's context window** (~350k
   tokens on a 1M-token window, ~70k on 200k), not when the context is nearly spent. *Why:* the handoff itself and the
   last turns need room, and quality drops well before the window is full. Put your number in `hub-rules.md` if it
   differs.
7. **Evidence before claims.** Before stating a fact about data or systems, look it up (a query, a command, a
   sub-agent with the schema in its brief). A negative result counts only with a positive control on the same query.
   *Why:* a search that cannot find anything reads exactly like "there is none".
8. **Money and anything that leaves the team go to the owner** as `ask add` with a default action, not as the hub's
   decision. *Why:* they are the decisions that cannot be undone by the next commit.
9. **Grill before you brief** (above). *Why:* a brief with a silent assumption produces confident work on the wrong
   problem.
10. **A change gets the review its class says** (`hub reviewer --for <class>`): `docs` — documentation, or tooling and
    configuration whose own positive and negative controls ran and are shown in the PR — gets no model review; `code`
    gets one review; `risky` (money, migrations, production, permissions) gets the same single review with its brief
    narrowed to that risk, not a second reviewer. *Why:* a review costs a full read of the diff and its context, and a
    second reviewer on the same risk mostly finds the same thing twice; a narrower brief gets more out of one reader.
11. **The reviewer is a different model from the author.** *Why:* a reader of the author's own model reads the code
    the way it was written and returns a confident summary, which reads like agreement.

## Optional modules (macOS + Claude Desktop)

- **Night queue** (`<stage>/night-queue.md`, `nightq`, `templates/night-queue-template.md`): work allowed while the
  owner is away, with a permission matrix; an optional Claude Desktop scheduled task (`templates/night-nudge-task.md`)
  wakes a silent hub. Skip it unless you run the hub overnight on a Mac with Claude Desktop.
- **Send budget** (`roles sent|budget|reset`, `AGENT_HUB_SEND_CAP`): Claude Desktop pauses a session's outgoing
  cross-session messages after 10 sends without the user typing in it. After every send — `roles sent <from> <to>`;
  at budget 0 write `jlog "@<tag> …"` instead. Terminal sessions do not need it.

## Watching agents

`agent-top` is a live console (curses) of every agent: state, current action, last words, unread inbox, locks, owner
questions and plan limits; `agent-top --once` prints the same picture as text. In chat, the `agent-top` skill shows it
as a widget.
