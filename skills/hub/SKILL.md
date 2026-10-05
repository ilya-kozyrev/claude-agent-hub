---
name: hub
description: Tools and recommended rules for a stage hub — the one interactive session that plans a stream of work and runs headless Claude Code or Codex agents. Load it when you are the hub of a stage, when starting a stage, taking over or handing off a hub shift, when spawning or messaging a long-running background agent, when you need a review of a change, and when you need to wait for events — journal lines, an agent's status, a script's question, an alarm. Also load it when the user mentions agent-hub or "the hub skill", or asks you to plan work for agents or to run work through agents.
---

# Stage hub: tools and recommended rules

## Host and engine

Run the bundled tools through the host's shell tool. Resolve the plugin root from `PLUGIN_ROOT` (Codex),
`CLAUDE_PLUGIN_ROOT` (Claude), or this installed skill's location (two directories above `skills/hub`).
Use that root's `bin/<tool>` when a command is missing or shadowed on PATH. `HUB_BIN` is set in detached workers.
Template and documentation paths below are relative to this root.
For installation assessment or task routing, read `<plugin-root>/docs/agents/README.md`;
this skill owns the stage workflow once the plugin is selected.

Choose the executor engine before choosing a model. Offer the owner one engine choice during initial stage planning:
Codex, Claude, or a mixed team, with the coordinator's current host as the default. An existing explicit choice
already answers this question; otherwise proceed with the host default while awaiting an optional preference.
Record the choice in the stage's `hub-rules.md` and carry it into briefs and handoffs. A Codex hub defaults to
Codex executors; a Claude hub defaults to Claude executors. Choose each worker's model and effort within that
engine. Claude model names in general task-sizing advice apply to Claude workers; using such advice to switch
engines requires an explicit engine choice from the owner. Reviewer engines may follow an explicitly configured
review policy.

Pass the chosen engine explicitly with `agent spawn --engine claude|codex`. Without that flag, `AGENT_HUB_ENGINE`
can supply a configured default; otherwise the launcher detects a Codex host through `CODEX_THREAD_ID` and falls
back to Claude in an ordinary terminal. Native subagents run in their host; mixed teams use detached executors.
Codex uses its configured model when `--model` is omitted; pass an actual available model id or an explicit
`AGENT_HUB_CODEX_MODEL_MAP` alias. Claude aliases stay Claude-only. Read `docs/codex.md` for installation,
hook trust, full access, and native worker setup. Full access keeps the lock hooks active.

## First commands

Do these before anything else, in this order:

1. `hub start --stage <S> --session self` — S is a short name for the goal (*Starting a stage*). If
   `hub` answers with an error such as `invalid choice` or `not a git command`, another `hub` (GitHub CLI) is ahead of
   the plugin's on PATH: run `<plugin-root>/bin/hub start …` and tell the owner in one line.
2. `ask search <words of the goal>` — decisions already on record are settled.
3. Grill, record, plan — in this order, details in *Planning a stage*: load the `grilling` skill when it is
   installed (otherwise grill by hand: rounds of numbered questions, a recommendation each); `ask add` and `ask close`
   each answer; propose the plan and wait for the owner's yes. Write no code and start no agents before that yes.
   Skip the grilling only as *Planning a stage* ends: say so in one line.

A **stage** is one stream of work (a release, a migration, a sprint) with its own directory under the hub home
(`$AGENT_HUB_HOME`, else a repository's `.agent-hub/config.json` `"project"` / `"user"`, else `~/agent-hub`; `hub home`
prints where it is and why, and how to grant a session access to it; if `hub start` warns that it is the legacy
`~/.claude/agent-hub`, tell the owner in one line — `hub home migrate` moves it, a dry run first). The **hub** is the
one interactive session that plans the stage, writes briefs, spawns headless agents and answers them. The **owner** is
the person the hub works for. Everything they share is a file:

| File | Written by | Read by |
|---|---|---|
| `<stage>/coordinator/work/journal-YYYY-MM-DD.md` — one line per event, `- HH:MM [tag] text` | `jlog`, `agent`, `hub`, `roles broadcast` | `jwait`, `agent-top`, humans |
| `<stage>/agents/<role>/` — `brief.md`, `inbox.md`, `log.jsonl`, `meta.json` | `agent spawn/send` and the selected CLI run | `agent status`, `agent-top` |
| `<stage>/roles.json` — who plays which role, by full session id | `roles`, `agent`, `hub start/takeover` | `roles`, `jlog` (tag lookup) |
| `<stage>/questions.md` — owner questions and agents' own decisions | `ask` | `ask`, SessionStart hook, `hub` digest |
| `board.md` — locks on shared resources (merges to main and whatever the project names) | `lock`, `hub takeover` | the `board_locks` hook |

The hooks add `<plugin-root>/bin` to PATH when enabled and trusted. An older
command of the same name — GitHub CLI `hub` from Homebrew, an old `jlog` — can answer instead; if `hub start` or the
session start says so, call the tools as `<plugin-root>/bin/<tool>` and tell the owner in one line. Each has
`--help` with the full syntax. Stage: `--stage`, else `$HUB_STAGE`, else `default`. The hub's tag is `hub-<N>` (N = shift number, derived).

**Minimal mode.** One hub and a few agents need `hub start` once (it gives the hub its journal tag) and then three
tools: `agent` (spawn, status, send, stop), `jlog` and `jwait`. `roles`, `ask`, `lock`, `hub takeover/handoff` and the
handoff skill matter once you have more than one interactive session, more than one shift, or a shared resource;
leave them until then.

## Starting a stage

`hub start --stage <S> --session <your full session id>` — once, by the first hub of a new stage: creates the stage
directory, registers you as `hub-1`, writes the start line and prints the first `jwait`. Use `--session self`;
the tool resolves the current host's session identity (`CODEX_THREAD_ID` in Codex, `CLAUDE_CODE_SESSION_ID`
in Claude, or `AGENT_SESSION_ID` in a detached worker). In Claude Desktop you may pass the `local_…` id.
An ordinary shell must pass an actual full session id. Run from the project's checkout so `.agent-hub/` is found.
Offer `agent-hub:setup` if it has no `.agent-hub/` yet. Follow warnings about shadowed tools or an outdated CLI.

## Taking over a shift

1. `hub takeover --stage <S> --session <your full session id | self> [--handoff <file>]` — one command (`self` = this
   session's host identity, read by the tool): the previous hub's
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

**Autopilot** (`AGENT_HUB_AUTO_HANDOFF=on`; `<plugin-root>/docs/reference.md`, "Autopilot"): the context budget message tells you when, and gives
the `hub succeed` command with your model, effort, mode and directory filled in. At a quiet point — no agent waiting for your
reply, no merge or lock operation in flight: `hub handoff`, fill the TODOs, run that `hub succeed … --handoff <draft>`,
start the `jwait` it prints using the host wait procedure below. Its start line → tell the owner one line (the successor's
name and any link returned by the launcher) and stop: no more tool calls, no lock released. ALARM → `hub succeed --stage <S> --fallback` (a
headless successor's ALARM: `--again`, if `agent status` says it is not running). A refusal that prints a `jwait` →
run that `jwait`, then retry. Exit 3 (chain limit), exit 2, or any other exit 1 → tell the owner the handoff path and
why, and wait for them. Run `hub succeed` yourself, never from a sub-agent.
A session whose first prompt carries `[agent-hub auto-handoff k/N]` is an automatic successor: run the takeover
command the prompt gives, then work the handoff's queue. The owner may be away: questions go to `ask add` with a
default, and you hand over the same way when your own budget says so.

## Waiting

Waiting is **one** `jwait`, using the shell harness rather than a polling loop.
- **Claude Code:** run Bash with `run_in_background: true`, `timeout: 7200000`, and `--for` at most 2h.
  Its completion notification wakes the coordinator.
- **Codex:** use the shell tool's yielded execution session and its continuation/wait tool. Keep each blocking
  tool wait at most 60 seconds so the coordinator can respond, and do independent work before continuing it.
  Preserve the returned execution id; use the tool's exit code to distinguish an event, an alarm, and a failure.
  A terminal session that cannot continue a shell command asynchronously should use a bounded foreground
  `jwait` and handle its result before starting another. A detached successor uses the same foreground procedure.

A stopped `jwait` loses no lines once its caller has run before: the next one delivers them.
- `jwait --journal --tag hub-<N> --tag hub --match '\b(MERGED|STOP|DONE|BLOCKED|EXIT|QUESTION)\b|AWAITING ANSWER' --for 2h` —
  lines addressed to the hub, agents' status lines and script questions echoed into the journal. Your own lines (your
  tag and its sub-tags `hub-<N>/…`) do not wake you. The digest prints this command with the team's extra wake words
  (`AGENT_HUB_JWAIT_MATCH`) already added; copy it from there. `--for` defaults to 2h, the longest a background Bash
  task is guaranteed. Called with `--caller <session id>` instead of as the hub's tag (no `HUB_TAG`, no registry
  entry for the session), `jwait` does not know your tag: add `--exclude-tag hub-<N>`, or your own `@agent` messages
  wake you.
- `jwait --file <script output> --match 'AWAITING ANSWER'` — a script's question; one asked before `jwait` started is
  delivered too.
- `jwait --until 20:23 --note "check the nightly import"` — an alarm; exit 3 and a line `ALARM …`. `--until` also takes
  `HH:MM:SS` and an ISO time with seconds (`2026-10-04T20:23:30`); `HH:MM` still means that minute's start.
- Sources and filters combine in one command. What was read is remembered: lines that arrived while you worked come
  with the next `jwait`.

Wake up — handle the block — start the next `jwait`. Journal waits and alarms use `jwait`; keep one waiter and continue it through the shell harness.

## Talking

- `jlog "text"` — a journal line with your tag (`--tag`, `$HUB_TAG` or the registry). The journal is append-only:
  never rewrite or delete a line; correct it with a new line that says what it corrects. When you write into another
  stage's journal, do not sign as `hub`: that stage's `jwait --tag hub` treats `hub` lines as its own and does not wake.
  `jlog` signs a foreign-journal line `<your stage>-<tag>` (`[core-c-hub-30]`); your `jwait --tag hub-30` hears the
  answer `@core-c-hub-30`.
- To another stage's hub write in its journal: `tell <stage> "…"` (`--question` for a question) — it addresses `@hub`
  and signs you correctly.
- A direct cross-session message only when the journal cannot do (for example the other hub must act before its next
  wake-up), and only to the address from `tell <stage> --address` / `roles --stage <stage> get hub` — never to a session
  chosen by its name in a list (`ListAgents`): a replaced hub can still run under the same name.
- `roles list | get <role> | set <role> <id> | retire` — the stage's role registry with full session ids; `set` infers
  the kind from the id (`local_…` = Claude Desktop, a uuid = terminal). For Claude cross-session messaging, resolve the address with `roles get <role>`.
  For detached workers of either engine, use `agent send`; Codex has no Claude `SendMessage` API. `roles broadcast --to r1,r2|--all "text"` — registered recipients and one journal line `@r1 @r2 text`.
- Owner-question register: `ask search <words…>` — decisions the owner already took on a topic; `ask digest` — the
  whole register, one line per decision; `ask add … --default … --due …` — a new question with the action you will
  take if nobody answers; `ask decided` — a decision you took yourself on a matter the owner normally decides;
  `ask close <id> --answer …` — the owner answered; `ask done <id> --evidence "…"` — the answer was executed;
  `ask list --pending` — answers without `done`.

## Planning a stage: grill before you brief

A brief can only carry decisions that were made. Before proposing a plan for a new stage or a new piece of work,
settle the open decisions with the owner, in this order:

1. `ask search <topic words>` — decisions already on record are settled; do not ask them again.
2. **Grill the owner** with the `grilling` skill (the recommended companion plugin `mattpocock-skills`, see `<plugin-root>/docs/install.md#recommended-companion-grilling`).
   It walks the decision tree in rounds: every question numbered, each with your recommended answer; facts you can look
   up yourself go to a sub-agent instead of to the owner. If the skill is not installed, say once how to add it
   (`/plugin marketplace add mattpocock/skills`, then `/plugin install mattpocock-skills@mattpocock`) and grill by hand
   the same way: rounds of numbered questions, a recommendation for each, until nothing is left silently assumed.
3. Record each answer, so the next hub and every brief inherit it: `ask add … "<question>"` then
   `ask close <id> --answer "<answer>"`. A matter the owner left to you is `ask decided`.
4. Only then propose the plan and the briefs, and wait for the owner's yes; their "Owner decisions — do not reopen"
   section comes from `ask search`, not from memory. Record the approved plan: `ask plan --stage <S> "<the plan in
   one line>"` (`agent spawn` warns when the stage has none).

For an owner who is not technical, one question is mandatory: "How will you open the result, and where should it live?",
with a recommendation. For something that runs in a browser, recommend a static site (for example GitHub Pages),
not "run a server on your Mac": a server dies with the laptop and the owner cannot restart it. Hand the result over so
that the owner does not have to look for it: open it yourself (`open <path>` on macOS) or give a clickable local file or web link.

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
(table, modes and the experiments behind them: `<plugin-root>/docs/launch-modes.md`). Estimated duration is a
hint, never the criterion: a hub cannot estimate task time reliably. The owner is not asked which launch to use. When
no row applies — a small change with nothing to wait on and nobody else to reach it — the hub may write it itself: one
line with the reason, and `ask decided` (*Planning a stage*).

1. **A review** → `hub reviewer --for <class>`, then start what it prints (*Reviews*, below).
2. **The owner should talk to it** → an interactive session in their chosen host. Claude additionally supports
   `claude --bg`; Codex detached workers are reached through `agent send` or a separate CLI resume after they stop.
3. **It commits or pushes, waits on CI, a deploy or another party, touches production, or must be reachable by
   someone other than this hub** → `agent spawn`. Always so when the hub is near its handoff threshold.
4. **Read-only, the answer is a short digest, nothing external to wait on** (read a log, check a fact, probe an
   environment, summarise a file) → a sub-agent: **foreground** when the hub has nothing else to do until the answer,
   otherwise **background** (through the host's native subagent API).

- An in-session sub-agent depends on the host's session lifecycle; its native follow-up API is for that session.
  Use a detached executor when a successor must reach or resume it. In Claude, compaction preserves the sub-agent. Ask it for a short result (≤ 20 lines,
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
- A headless agent may use native sub-agents. For Claude, `agent spawn` lifts its 10-minute wait ceiling
  (`AGENT_HUB_BG_WAIT_CEILING_MS`); Codex uses its own native subagent lifecycle. `agent-top` lists the sub-agents of registered sessions as `<role>/<id>`, read-only.

### Reviews

For Sol-authored code, choose a judgement reviewer: Claude Opus/Fable at high effort when its limits allow,
otherwise an available Codex Astra at high. A different or older Sol is not the default reviewer for Sol.
Reviewer engine choice is separate from the implementation engine; this review policy can select Claude for a
Codex implementation. Check the chosen engine's available models and limits before launch, record the reviewer
choice in stage rules and its brief, and honour the owner's explicit reviewer policy. For a Claude author,
use its configured independent Fable or Codex reviewer. One reviewer is sufficient.

`hub reviewer --for <class>` walks the configured reviewers (`AGENT_HUB_REVIEWERS`, default one ordinary `agent
spawn`) and prints the first that is available now and exactly how to start it: an `agent spawn --role review-… --brief
<BRIEF>` line, or "load skill `<skill>`" for a reviewer skill the user plugged in. Write the brief from
`<plugin-root>/templates/brief-review.md`, start the reviewer as printed, and **verify each finding against the
code** before acting on it — a review is a colleague's opinion. Classes, the config, the skill reviewer contract:
`<plugin-root>/docs/reviewers.md`.
Configure the list in this order with availability checks for limited reviewers; if a legacy entry selects a
Sol reviewer for Sol-authored work, bring that entry into line with the approved policy before using its command.

## Executors

- Work that commits, pushes or waits (a merge steward, a rehearsal, a CI wait — see "Choosing how to launch work") is
  a headless agent, not an in-session sub-agent:
  `agent spawn --engine claude|codex --role R --cwd DIR [--model MODEL] [--effort high] --brief FILE [--worktree [BRANCH]]`.
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
- Model and effort: choose per agent. Claude supports `opus|sonnet|haiku|fable` aliases and optional
  `AGENT_HUB_MODEL_MAP` pins. Codex supports available model ids and optional `AGENT_HUB_CODEX_MODEL_MAP` aliases;
  omit the model to use `AGENT_HUB_CODEX_DEFAULT_MODEL` or the CLI configuration. Choose effort supported by that model.
  Before the first detached Codex launch for a selected CLI/model in a stage, check that CLI's `--version` and
  `debug models` catalog (use `CODEX_BIN` when configured), including its configured default when omitting `--model`.
  Desktop model availability does not establish standalone CLI availability. Ordinary implementation uses an
  available Sol-family model, subject to the owner's explicit model choice. Resolve an unavailable Sol version by
  checking CLI compatibility or selecting an available Sol peer and reporting the fallback. Reserve Astra for a
  task whose judgement needs justify it, stating the reason before launch; a startup/model error is a compatibility
  issue rather than a reason to raise the task's model class. Keep the chosen engine through this recovery.
  `AGENT_HUB_PERMISSION_MODE=bypassPermissions` is the headless default: Claude uses its bypass mode, Codex uses
  `--dangerously-bypass-approvals-and-sandbox`. For Codex read-only review, pass `--sandbox read-only` instead.
  Codex hook trust is separate: see `docs/codex.md`; read the returned errors when a restricted operation fails.
- A brief follows `<plugin-root>/templates/brief-executor-template.md` (short); the advanced one,
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
(example: `<plugin-root>/templates/hub-rules-example.md`).

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

## Optional modules

- **Night queue** (`<stage>/night-queue.md`, `nightq`, `templates/night-queue-template.md`): work allowed while the
  owner is away, with a permission matrix; an optional Claude Desktop scheduled task (`templates/night-nudge-task.md`)
  wakes a silent Claude hub. The queue files work with either engine; this Desktop scheduled nudge stays Claude-only.
  Codex autopilot creates a detached Codex successor, without a Claude Remote Control phone link.
- **Send budget** (`roles sent|budget|reset`, `AGENT_HUB_SEND_CAP`): Claude Desktop pauses a session's outgoing
  cross-session messages after 10 sends without the user typing in it. After every send — `roles sent <from> <to>`;
  at budget 0 write `jlog "@<tag> …"` instead. Terminal sessions do not need it.

## Watching agents

`agent-top` is a live console (curses) of every agent: state, current action, last words, unread inbox, locks, owner
questions and plan limits; `agent-top --once` prints the same picture as text; `agent-top --json` is for scripts. In Claude Code (2.1.287 or
later) the person types `/agent-top` for a live read-only side pane. Where mods do not draw (Codex, VS Code chat,
`claude -p`, Remote Control views) there is no `/agent-top`: use the console in a shell.
