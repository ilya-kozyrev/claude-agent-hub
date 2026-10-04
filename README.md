# agent-hub

A Claude Code and Codex plugin for running long, parallel work with **one hub session and many headless agents**.

The hub is your interactive Claude Code or Codex session. It writes a brief and starts detached workers with
`agent spawn --engine claude|codex`. Agents report through a shared **journal**, take messages through an **inbox**,
ask the owner through a **question register**, and respect **locks** on shared resources such as merging to main.
When the hub's context fills up, it writes a **handoff** and a fresh hub takes over — the agents keep running.
With **autopilot** on, the hub starts its successor automatically: Claude supports its background Remote Control
workflow; Codex starts a detached Codex successor. `agent-top` shows both engines in the terminal or as a chat widget.

Codex installation, full access, hook trust and native worker definitions: [Codex support](docs/codex.md).

Everything is plain files under one directory and a handful of small Python CLIs. No server, no database.

New here? Start with [Getting started](docs/getting-started.md) — from an idea to merged code in eleven steps.

## Why

A single chat session is a poor place to run a week of work:

- **Long sessions get slower, worse and more expensive.** Claude Code sends the whole conversation with every request,
  so each turn costs as much as the history behind it. In one project 16 % of the turns of a coordinating session were
  pipeline polls, each re-reading 300–600k tokens of context.
- **Subagents work within one session.** They are the right tool for a search or a log read, but they report to the
  session that spawned them, into its context. Work that runs for hours, must outlive the session or must be reachable
  by others goes to a headless `claude -p` agent that reports one journal line per event.
- **`/compact` is a summary you do not choose.** A handoff is a short file with a fixed structure, written before the
  context is full and readable by a person and by the next session; decisions, questions and locks live in files.

```
 BEFORE: one session does everything              AFTER: the hub plans, agents work, files remember

 ┌───────────────────────────────┐                ┌──────────────┐  brief   ┌──────────────────┐
 │ chat session                  │                │  hub session │ ───────▶ │ agent: builder   │ claude -p,
 │  plan + build + test + review │                │  (plans,     │ ◀─────── │ agent: reviewer  │ detached,
 │  + logs + merge + questions   │                │   decides)   │  journal │ agent: migrator  │ survives the hub
 │  … context full, work stalls  │                └──────┬───────┘          └────────┬─────────┘
 └───────────────────────────────┘                       │   journal · inbox · questions · locks │
                                                         └──────────── files on disk ─────────────┘
                                                 a new hub reads the handoff and takes over; agents keep going
```

The full argument, with numbers, and the case against `/compact` for long work:
[Why a hub and headless agents](docs/why.md).

## How it compares with Claude Code's own facilities

Claude Code can already run several things at once. What each one keeps for you differs; read the table, then pick the
lightest tool that covers your case. Every Claude Code cell is checked against the official docs (numbers in brackets,
links below); `—` means the docs do not say.

| | Outlives the session that started it | Another session can message it | Fixed session id | State is shared through | Locks on shared resources | Platform, status |
|---|---|---|---|---|---|---|
| **Sub-agent in a session** (also in the background) | — Works "within a single session"; a finished one is resumed by resuming that session. What a running one does when the session exits is not documented [1] | Only the session that spawned it (`SendMessage` by name or ID); it reports to that conversation [1][2] | An agent ID and optional name, valid inside the parent session [1] | Its final message goes into the parent's context; transcript on disk; optional per-agent `memory` directory [1] | — (optional `isolation: worktree` separates files) [1][11] | Built in [1] |
| **Background Bash task** (`run_in_background`) | No: cleaned up when Claude Code exits, detached children included (macOS, Linux); it keeps running only if you background the whole session [3] | No: a shell command, not an agent [2] | A task ID inside the session [3] | An output file Claude reads [3] | — | Built in; 30 min by default, 2 h at most per command [3][4] |
| **`claude -p --resume` by hand** | Yes: your own process; the conversation is stored and `--resume <id>` continues it [5][6] | Yes through cross-session messaging (v2.1.224+): a `-p` worker takes messages unattended if its `--settings` set `crossSessionInbound: accept`; not in `--bare` mode. Otherwise resume it with a new prompt [6][7] | `--session-id <uuid>` [5] | What you build: stdout, stream-json, files [6] | — | Wherever Claude Code runs [10]; `--max-turns`, `--max-budget-usd` [5] |
| **Background sessions** (`claude --bg`, agent view) | Yes: a supervisor process runs them after you close the terminal or start another session [8] | Yes: reply from agent view or `claude attach <id>`; reachable by cross-session messaging [7][8] | A short ID printed at start (`claude logs / attach / stop <id>`) [5][8] | Its own conversation; each session moves into its own worktree before editing; results go to you, not to another session [2][8] | — | Research preview [2][8] |
| **Agent teams** | No: the team config is removed when the session ends; `/resume` does not restore in-process teammates; one team per session [9] | The lead, the teammates and you; a team is not shared across sessions [9] | Names chosen by the lead; session IDs sit in runtime team config you must not edit [9] | A shared task list (`~/.claude/tasks/<team>/`) and JSON mailboxes [9] | Task claiming uses file locking; nothing for external resources, and teammates must own different files [9] | Experimental, off by default; split panes need tmux or iTerm2 [9] |
| **agent-hub headless agents** | Yes: detached `claude -p` or `codex exec` in its own process group; survives the hub closing, compacting or handing over | Yes: `agent send` writes its inbox while it runs and resumes it after it exits | Yes: Claude `--session-id` or the Codex thread id, kept in `meta.json` | Files: brief, inbox, journal, reports, question register | A lock board enforced by a hook: merges to protected branches and the commands you list | macOS and Linux; a third-party plugin, MIT |

Sources, Claude Code documentation read on 2026-10-01:
[1] [Subagents](https://code.claude.com/docs/en/sub-agents) ·
[2] [Run agents in parallel](https://code.claude.com/docs/en/agents) ·
[3] [Interactive mode: background Bash commands](https://code.claude.com/docs/en/interactive-mode#background-bash-commands) ·
[4] [Tools reference: when a background command stops](https://code.claude.com/docs/en/tools-reference#when-a-background-command-stops) ·
[5] [CLI reference](https://code.claude.com/docs/en/cli-reference) ·
[6] [Run Claude Code programmatically](https://code.claude.com/docs/en/headless) ·
[7] [Cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging) ·
[8] [Agent view](https://code.claude.com/docs/en/agent-view) ·
[9] [Agent teams](https://code.claude.com/docs/en/agent-teams) ·
[10] [Advanced setup](https://code.claude.com/docs/en/setup) ·
[11] [Worktrees](https://code.claude.com/docs/en/worktrees).

What agent-hub adds is not a new way to start a second session. It is a worker that survives a session boundary and a
handoff, an id fixed at spawn so any session can message or resume it by role, files as the protocol (a journal any
session can wait on, an owner-question register) and a lock board that refuses a merge, or a command you listed, for
everyone but the holder. If a sub-agent, a background session or `claude -p` covers your case, use it. The argument is in
[docs/why.md](docs/why.md).

## How it works

```mermaid
flowchart LR
    owner(["Owner"])
    hub["Hub session<br/>(Claude Code or Codex)"]
    subgraph agents["Headless agents — Claude Code or Codex, detached"]
        a1["builder"]
        a2["reviewer"]
        a3["migrator"]
    end
    subgraph files["Hub home — default ~/agent-hub, a setting (Where the hub's files live)"]
        brief[/"agents/&lt;role&gt;/brief.md"/]
        inbox[/"agents/&lt;role&gt;/inbox.md"/]
        log[/"agents/&lt;role&gt;/log.jsonl + meta.json"/]
        journal[/"coordinator/work/journal-DATE.md"/]
        roles[/"roles.json"/]
        questions[/"questions.md"/]
        board[/"board.md (locks)"/]
    end
    owner <-->|chat| hub
    hub -->|"agent spawn: writes"| brief
    hub -->|"agent send (alive): appends"| inbox
    hub -->|"agent spawn / send (gone): starts or resumes"| agents
    agents -->|"JSON event output"| log
    agents -->|"reads after each step"| inbox
    agents -->|"jlog: DONE / BLOCKED / QUESTION"| journal
    hub -->|"jlog, roles broadcast"| journal
    journal -->|"jwait wakes the hub"| hub
    hub <-->|"ask add / close / search"| questions
    hub <-->|"lock take / release"| board
    hub <-->|"roles set / get"| roles
    board -.->|"board_locks hook refuses merges to protected branches and the commands you list under another's lock"| agents
    log -->|"read-only"| top["agent-top<br/>console + /agent-top widget"]
    journal --> top
    questions --> top
    board --> top
```

| Tool | What it does |
|---|---|
| `agent spawn / status / send / stop` | Start a detached Claude Code or Codex agent from a brief; check it; message it (inbox while alive, resume after exit); stop it. |
| `jlog` | Append `- HH:MM [tag] text` to today's stage journal. |
| `jwait` | The only waiter: block (in the background) until new journal or log lines match, or until an alarm time. |
| `roles` | Who plays which role, by full session id; cross-session send budget; broadcast. |
| `ask` | The owner-question register: questions with a default action and a due time, answers, decisions taken by agents. |
| `lock` | The lock board for shared resources: `main-merge` is built in, every other resource is named by your project in `lock-rules.json`. `lock rules` shows, writes and tests those rules. |
| `hub start / takeover / handoff` | Register the first hub of a stage; hand a hub shift over in one command each. The shift number is derived. |
| `hub succeed` | Autopilot: start the successor of an automatic handoff — a background Remote Control session, else a headless hub. |
| `nightq` | Optional (macOS + Claude Desktop): a night queue with a permission matrix, for work that may continue while the owner sleeps. |
| `agent-top` | Live console of all agents (curses), `--once` text, `--json`, `--widget` HTML. |

More diagrams and the file formats: [docs/architecture.md](docs/architecture.md).

## Screens

`agent-top --once` (synthetic demo data, `docs/render_demo.sh`):

```text
 agent-top ● 2 ✓ 1 ✗ 1 stage-a · locks 1 · questions 1 (overdue 1) · limit 5h 34% 7d 52%                       14:01:17
  ROLE      TASK                           STATUS MODEL           AGE TURN  CTX     $ ✉  NOW / LAST
● builder   Rebase payments and get CI gr… live   opus-5-5/hi      0s    6  94k     — ✉1 ▸ Bash: run the full test suit…
● reviewer  Review PR #41 (export to Parq… live   sonnet-5-5/hi    0s    2  62k     —    ▸ Read: /work/webapp/src/expor…
✗ migrator  Rehearse migration 0042 on a … error  opus-5-5/hi     20m    1  62k $1.92    Dry-running the migration on a…
✓ docs      Update the API docs for the e… done   sonnet-5-5/hi   14m    1  62k $0.84    DONE docs updated, report at w…

Locks (lock list)
  main-merge webapp until 2026-10-02 14:01 — Hub stage-a #3: stage hub merges main

Owner questions (ask summary)
  stage-a — open 1, overdue 1
    Q-A-001 [stage-a] open OVERDUE — Turn the new export on by default?
    blocks: the release; default by 2026-09-30T12:01: ship with the flag off

Journal (last 5 lines):
13:09 [hub-3] start: "Hub stage-a #3" took over from "Hub stage-a #2"; locks: main-merge
13:11 [hub-3-builder] started headless agent builder (claude-opus-5-5/high)
13:41 [hub-3-migrator] EXIT migrator: error_max_turns, error; code 1, turns 80 — agent status migrator
13:46 [hub-3-docs] DONE docs updated, report at work/hub-3-docs-REPORT.md
14:00 [hub] @hub-3-builder after the suite, push and open the PR
```

Interactively, `agent-top` adds a live feed per agent (thoughts ✎, commands ▸, results ◂), its brief and inbox, the
journal with a filter, and `m` / `x` to message or stop an agent after a y/N prompt.

The `/agent-top` chat widget (a sketch of the HTML that `agent-top --widget` produces, same data):

![agent-top chat widget sketch](docs/agent-top-widget.svg)

### agent-top inside Claude Code: a live pane

Claude Code (mods are on by default) runs the plugin's mod, `hooks/agent-top.tsx`, in the terminal and in the
Desktop Code tab. It replaces the chat widget as the primary view there:

- **`/agent-top [role] [--stage S] [--all]` opens a pane.** It never opens by itself. Views: **Agents** (`a`; a row or
  its digit key `1`–`9` opens the agent card), the **agent card** (header and a live feed of the last 30 events; `b`
  goes back), **Journal** (`j`) and **Summary** (`s`: locks, owner questions, plan limits including Codex). It refreshes
  every 3 s while open; a role opens that agent's card. Claude and Codex agents are listed alike, as in the console.
- **A status line and toasts.** The status line reads `agents ● 2 ✓ 5 ✗ 1` (nothing when there are no agents). A toast
  appears when an agent finishes, fails or dies and when a new owner question opens; what was already there when the
  session started is never announced. With the pane closed the mod looks every 15 s.
- **Read-only.** No send, stop or message button. The mod writes nothing: it runs `bin/agent-top --json` and draws the
  result. Messaging and stopping stay in the console (`m` / `x`) and in `agent send` / `agent stop`.
- **Older Claude Code ignores the module**, and the `agent-top` skill keeps working there, in Codex and in VS Code chat.
  Where no pane can be drawn (`claude -p`), `/agent-top` prints the text picture, like `agent-top --once --width 100`.
  If `bin/agent-top` is missing the mod goes quiet instead of failing.

## Install

**Platform.** macOS and Linux, Python 3.10+ for Claude or 3.11+ for Codex (standard library only), the selected `claude` or `codex` CLI on `PATH`. Claude Code 2.1.287 or later: older versions are unsupported. Windows is not
supported: the tools need `fcntl`, `setsid`, `ps` and `curses`. Claude Code itself does run natively on Windows
([setup](https://code.claude.com/docs/en/setup)); the limit is agent-hub's. WSL is untested.

**Claude Code:**

```text
/plugin marketplace add ilya-kozyrev/claude-agent-hub
/plugin install agent-hub@claude-agent-hub
```

**Codex, from a local checkout:**

```sh
codex plugin marketplace add /absolute/path/to/claude-agent-hub
codex plugin add agent-hub@agent-hub-codex
```

Review and trust its hooks before starting an interactive Codex hub. The explicit Codex manifest selects
`hooks/codex-hooks.json` and packages the same five skills. Full access and hook trust are separate settings;
[Codex support](docs/codex.md) explains detached defaults and restricted reviewers.

The order: install, then your first message `/agent-hub:hub …` in the repository (see [Quickstart](#quickstart)), then
[`agent-hub:setup`](#after-install-run-agent-hubsetup-in-each-repository) once per repository.

> **Permissions.** Headless agents run with `--permission-mode bypassPermissions` by default: a `claude -p` run has
> nobody to approve a prompt, and any other mode silently stalls on the first blocked tool. Treat every agent as a
> process with your user's rights — say in its brief what it must not touch, run it in a worktree or sandbox, or set
> `AGENT_HUB_PERMISSION_MODE` (for example `acceptEdits`) and accept that some tools will be refused.
>
> **Run the hub in bypass mode too** (start it with `claude --dangerously-skip-permissions`). The plugin
> is built for a hub that works while nobody watches it, and only `bypassPermissions` lets it: in `default` and
> `acceptEdits` every `agent`, `jlog` or `gh` call waits for your click; in `auto` the classifier refuses actions that
> leave the machine or touch shared branches — a hub in `auto` had its `gh pr merge` refused and stopped until the
> owner restarted it in bypass. Other modes work only with you at the keyboard approving each step. The autopilot
> successor inherits the mode (`AGENT_HUB_SUCCESSOR_PERMISSION_MODE`); bypass needs its disclaimer accepted once in a
> terminal (`claude --dangerously-skip-permissions`), otherwise the successor falls back to `auto`.

For Codex, `bypassPermissions` maps to `--dangerously-bypass-approvals-and-sandbox` (full access and no approval
prompts). `--sandbox read-only` or `workspace-write` chooses a restricted worker instead. Detached Codex runs also
use the separately configured hook-trust policy; hooks stay enabled. See [Codex permissions](docs/codex.md#full-access-and-hook-trust).

### What installing changes

- **Tools on `PATH`.** While the plugin is enabled its `bin/` is on the Bash tool's `PATH`, so Claude can call `agent`,
  `jlog`, `jwait` and the rest directly. To use them in your own terminal too, add `bin/` to your `PATH` or symlink the
  tools. A Claude Code session's id is in `$CLAUDE_CODE_SESSION_ID` (`echo` it in the session). When it is empty, for
  example in a plain shell outside Claude Code, `lock take` refuses unless you pass `--force`: the lock would have no
  owner the hook could recognise. The plugin's `bin/` comes after your own `PATH` entries, so an older command of the
  same name wins — in practice the GitHub CLI `hub` from Homebrew, or an old copy of `jlog` in `~/.local/bin`. `hub start`
  and a SessionStart hook warn once when any command of the plugin (every executable in its `bin/`: `hub`, `jlog`,
  `jwait`, `agent`, `ask`, `roles`, `lock`, `agent-spawn`, …) resolves outside it; the fix is to put the plugin's `bin/`
  first on `PATH` or remove the old tool. A command that resolves into an installed plugin's `bin/` (the Claude or Codex
  plugin cache, the marketplace folder) is not reported. To keep a personal shim that dispatches into the plugin (say
  `~/.local/bin/hub` linked to a script that execs the newest installed `bin/`), put the line `# agent-hub: dispatcher`
  among the first ten lines of the script (right after the shebang; symlinks are followed): the warning skips it.
- **Five skills.** `hub` (the workflow), `handoff`, `setup` (`agent-hub:setup`), `delegation` and `agent-top`
  (`/agent-hub:agent-top`, or `/agent-top` when no other skill has that name; in Claude Code the mod answers it
  with a live pane before the skill runs); four pinned-effort Claude worker subagents.
  Codex worker TOML resources are copied by setup; they are not automatically registered by the plugin manifest.
- **Hooks**, each with its own reach (the [agent-discipline](#agent-discipline) hooks — context budget, polling guard,
  delegation dial and subagent rules — are described in their own section):
  - `board_locks` (before every Bash call) runs in every Claude Code session on the machine, but acts only on merges
    and pushes to protected branches and on commands your `lock-rules.json` names. Any error of its own lets the
    command through.
  - `handoff_size` (Write or Edit of `HANDOFF-*.md`) and `questions` (the owner-questions line at session start) act
    only in the hub home, in repositories that have `.agent-hub/`, under the directories of the hub-wide setting
    `AGENT_HUB_SCOPE_DIRS`, and, for `questions`, in agents started by `agent spawn`. A session in an unrelated
    project hears nothing from them.
  - `path_shadow` (session start) warns when a command of the same name as one of the plugin's tools comes first on
    `PATH`. It does nothing, and writes nothing, until a hub home exists (`hub start` creates it). Then it speaks every
    time in the same places as `questions`, and once per distinct set of paths elsewhere.
- Nothing else: no daemon, and nothing is written to your repositories until you run `agent-hub:setup`. The hub's own
  files go to `~/agent-hub` (created by `hub start`; see [Where the hub's files live](#where-the-hubs-files-live)).

### After install: run `agent-hub:setup` in each repository

Ask your coordinator to use the `agent-hub:setup` skill in the repository's checkout. A new, empty project may skip it for now:
the hub offers it when it is needed. It looks at the repository, then asks one round of numbered questions with a
recommended answer for each: which branches are protected, which environments two sessions must not change at once,
which commands touch each. It writes `.agent-hub/lock-rules.json` and `.agent-hub/config.json` and proves the rules
with positive and negative checks (`lock rules check`). A project with no deployment ends with `main-merge` only, and
that is a complete setup. Commit `.agent-hub/`: it is the team's shared convention (see [Team use](#team-use)).

### Recommended companion: grilling

The hub settles open decisions with you before it writes any brief. It does that best with the `grilling` skill from
[mattpocock/skills](https://github.com/mattpocock/skills) (MIT): rounds of numbered questions, each with a recommended
answer, until nothing is left assumed. agent-hub does not bundle it; install it next to this plugin:

```text
/plugin marketplace add mattpocock/skills
/plugin install mattpocock-skills@mattpocock
```

Without it the `hub` skill grills by hand in the same format; the answers go to the question register either way.

## Minimal mode

You do not need all of it. One hub and a few agents need three tools: `agent` (spawn, status, send, stop), `jlog` and
`jwait`, plus `hub start` once per stage, which registers your session as `hub-1` and so gives `jlog` its journal tag.
`roles`, `ask`, `lock`, `hub takeover` and `hub handoff` matter once you have more than one interactive session, more
than one shift, or a shared resource; leave them until then. The night queue, the night nudge and the send budget are
optional modules for macOS with Claude Desktop.

## Quickstart

Start the first message of a session with `/agent-hub:hub`, for example `/agent-hub:hub I want CSV export on the
reports page …`. The slash command always loads the `hub` skill; a plain-language mention of it may be ignored by a
smaller model, which then plans and codes on its own. Or run the commands yourself:

```bash
export HUB_STAGE=stage-a                      # one directory per stream of work under the hub home

# 1. once per stage: register this session as hub 1 (creates the stage directory, prints the first jwait)
hub start --stage stage-a --session "$CLAUDE_CODE_SESSION_ID"

# 2. write a brief (template: templates/brief-executor-template.md) and start an agent in its own worktree
agent spawn --role builder --cwd ~/code/webapp --model sonnet --worktree --brief ./brief-builder.md

# 3. watch it
agent status builder                          # alive?, last event, turns, last line, worktree
agent-top                                     # live console; agent-top --once for a text snapshot

# 4. message it — alive: into its inbox; finished: the session resumes with the message
agent send builder "after the tests pass, open the PR"

# 5. wait for its status line without polling (run in the background from Claude)
jwait --journal --tag hub --match '\b(DONE|BLOCKED|EXIT|QUESTION)\b' --for 2h

# 6. stop it
agent stop builder
```

`--worktree [BRANCH]` (default branch `agent/<role>`) runs the agent in an existing worktree of that branch, or in
`<repo>/.worktrees/<branch>` of the main repository, which `agent spawn` adds to `.git/info/exclude`. Two agents writing
in one checkout overwrite each other, so give each agent that writes code its own. Nothing removes a worktree: once the
branch is merged, `git worktree remove <path>`.

The brief template is short: why, decisions already made, steps with a check for "done", verification, where to stop and
a turn limit. `agent spawn` appends a footer that tells the agent how to talk back: `jlog "DONE <report path>"` when
finished, `jlog "@hub QUESTION …"` then `BLOCKED` when it needs an answer, and to read its inbox after every major step.
The footer names `jlog` as `"$HUB_BIN/jlog"`, and the agent starts with the plugin's `bin/` first on its `PATH` and in
`$HUB_BIN` (rebuilt at every spawn and resume, so a resumed agent follows a plugin update): an older `jlog` found first
would write to a journal the hub never reads.
The longer `templates/brief-executor-advanced.md` adds production permissions, size limits and evidence rules;
`templates/brief-review.md` is the brief for a reviewer.

A full working day, step by step: [docs/a-day-with-agent-hub.md](docs/a-day-with-agent-hub.md).

## Cost and turn limits

- **Limits are shared.** Your plan's usage limits are spent by your interactive session and by every headless agent
  together, and running several sessions at once multiplies token usage
  ([Claude Code docs](https://code.claude.com/docs/en/agents)).
- **Each turn re-reads the agent's whole context**, so cost grows faster than the number of turns, and a very long
  agent is the most expensive shape there is. [docs/why.md](docs/why.md) lists measured examples from one project, such
  as an executor that ran 1,100 turns because it was never cut into pieces.
- **Give every brief a turn limit and a stop condition**, and cut day-long work into pieces: a fresh agent for each, with
  a short report or handoff file between them. The turn limit is a line in the brief; agent-hub does not enforce it.
- **`agent-top` shows a dollar figure only when the CLI reports one** (the cost of finished runs); a live run shows `—`.
- **Agents run on the latest models if Claude Code is current.** `--model opus|sonnet|haiku|fable` goes to the CLI,
  which resolves the alias to the newest model of that family: Claude Code 2.1.287 (the minimum supported version) and
  later gives `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-4-5-20251001` and `claude-fable-5-1`, an older CLI
  gives older models. Keep Claude Code updated; `agent spawn` and `hub start` warn when the CLI is older than 2.1.287,
  and without `CLAUDE_BIN` they start the
  newer of `claude` on `PATH` and the CLI bundled with Claude Desktop (`agent spawn` prints which). The plugin pins no
  ids, since a pin goes stale with the next release: the id each run reports is shown by `agent status`, the journal's
  `started headless agent` line, the roles note and `agent-top` (`sonnet-5-5`, not `sonnet`). The CLI's version is read
  with `claude --version` (5 s at most; the line `<version> (Claude Code)`) and remembered by path, size and modification
  time in `<hub home>/.state/cli-version/`. If you must hold a model, pin it with
  `AGENT_HUB_MODEL_MAP`.
- **Turns are counted per run.** `agent status` and `agent-top` show the last run's turns next to the total once an
  agent was resumed (`turns 31 (total 60)`; `31/60` in the agent-top list), so a limit in the brief can be checked.

## Agent lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant H as Hub session
    participant F as Files (brief, inbox, journal, log)
    participant A as Agent (Claude or Codex)
    H->>F: write brief.md
    H->>A: agent spawn --role builder --brief …
    Note over A: detached, own process group,<br/>fixed session id, bin/ on PATH
    A->>F: jlog "started …" · stream-json → log.jsonl
    H->>F: jwait --journal … (background)
    H->>F: agent send builder "…" (alive → inbox.md + @tag journal line)
    A->>F: reads inbox.md after its current step
    A->>F: writes work/TAG-REPORT.md
    A->>F: jlog "DONE work/TAG-REPORT.md"
    Note over A: turn ends = process exits
    F-->>H: jwait exits with the DONE line
    H->>A: agent send builder "one more thing" (process gone → recorded engine resume, unread inbox replayed)
    A->>F: jlog "DONE …"
    H->>A: agent stop builder (SIGTERM → SIGKILL, role retired)
```

If a run crashes or ends without a status word, a small wrapper journals `EXIT <role>: …` under the agent's tag, so
the hub's `jwait` wakes anyway.

Headless agent, foreground or background sub-agent of the hub, `claude --bg` or Desktop session — which to use when,
decided by what the work does and who must reach it rather than by how long it takes, with the measurements behind it:
[docs/launch-modes.md](docs/launch-modes.md). `hub handoff` refuses while a sub-agent of the hub's session still runs.

Reviews are configurable: by default a reviewer is an ordinary `agent spawn`, and `hub reviewer --for <class>` chooses
among the reviewers you listed — your own reviewer skills included — and prints how to start it:
[docs/reviewers.md](docs/reviewers.md).

## Owner questions

```mermaid
flowchart LR
    q{"Agent or hub hits a<br/>decision the owner owns"} -->|"agent: jlog '@hub QUESTION …' + BLOCKED"| h["Hub"]
    q -->|hub| h
    h -->|"ask search &lt;words&gt;"| known{"Already decided?"}
    known -->|yes| relay["Hub applies it:<br/>agent send &lt;role&gt; '…'"]
    known -->|no| add["ask add --default … --due …<br/>→ Q-A-007 in questions.md"]
    add --> owner(["Owner answers in chat"])
    add -->|"due passes"| dflt["ask default-taken:<br/>the default action is done,<br/>the answer is still awaited"]
    owner --> close["ask close Q-A-007 --answer …"]
    close --> relay
    relay --> done["ask done Q-A-007 --evidence …"]
```

Every open question carries the action that happens if nobody answers by its due time, so work is never silently
stuck. A decision an agent takes on its own on a matter the owner normally decides is recorded with `ask decided` —
visible, contestable. The plan the owner approved is recorded with `ask plan` (`agent spawn` warns while its stage has
none); `ask add|decided|plan --print-id` prints just the new id, for scripts. At session start a hook prints one line per stage — open, overdue, awaiting execution — in the
hub home, in repositories with `.agent-hub/` and for hub agents.

## Team use

- **One hub home belongs to one person on one machine.** The board, the journal and the registers are local files, so
  two people cannot share a hub home, and a lock held by one person's hub is invisible to another's.
- **`.agent-hub/` committed in a repository shares conventions, not agents or locks**: the lock resources and rules, the
  brief footer, the hub rules, the team's notes, the config defaults. Everyone who installs the plugin and opens the
  repository gets the same guard and the same briefs; each runs their own hub.
- **Where the hub keeps its files can be a convention too**: `"AGENT_HUB_HOME": "project"` committed in
  `.agent-hub/config.json` puts each person's hub files inside their own checkout (`.agent-hub/local/`, excluded from
  git). It is still local to that person and machine. A repository can choose only `"project"` or `"user"`, never a path
  (see [Where the hub's files live](#where-the-hubs-files-live)).

## File layout

```text
<hub home>/                           default ~/agent-hub (see Where the hub's files live)
├── board.md                          lock board (lock)
├── config.json                       optional: settings (see Configuration)
├── lock-rules.json                   optional: shared resources and the commands that touch them
├── hub-rules.md, HUB-NOTES.md        optional: your rules and notes for every hub (see Configuration layers)
├── .jwait-state/<caller>.json        what each jwait caller has already seen
├── .state/                           context-budget warnings, delegation levels (agent discipline)
└── <stage>/                          one directory per stream of work
    ├── roles.json                    role → full session id, kind, tag; send counts
    ├── questions.md                  owner-question register (ask)
    ├── auto-handoff.json             autopilot: automatic handoffs in a row, the successor last started
    ├── night-queue.md, night-log.md  optional night queue (nightq; macOS + Claude Desktop)
    ├── handoff-facts.sh              optional: prints environment rows for hub handoff (also brief-footer.md, takeover.sh)
    ├── agents/<role>/                one headless agent
    │   ├── brief.md                  copy of the brief it was started with
    │   ├── inbox.md                  messages sent while it runs
    │   ├── log.jsonl                 stream-json of every run (spawn and resumes)
    │   ├── stderr.log
    │   └── meta.json                 session id, pid, model, effort, runs, unread messages
    └── coordinator/
        ├── HANDOFF-hub-<stage>-<date>.md
        └── work/
            ├── journal-YYYY-MM-DD.md one line per event: - HH:MM [tag] text
            ├── <tag>-REPORT.md       agents' reports
            └── hub-<n>-takeover-brief.md  autopilot: the brief of a headless successor

<repo>/.agent-hub/                    committed: the team's conventions, same file names as above (Configuration layers)
<repo>/.worktrees/<branch>/           agent worktrees from `agent spawn --worktree`, excluded in .git/info/exclude
```

## Where the hub's files live

The hub home (journals, inboxes, the question register, the lock board, handoffs) is resolved for the directory a tool
runs in, or for a hook the session's directory, in this order:

1. `AGENT_HUB_HOME` in the environment: any path. Set it in your shell, or for every Claude Code session with
   `{"env": {"AGENT_HUB_HOME": "…"}}` in your Claude Code settings.
2. A repository's `.agent-hub/config.json`, key `AGENT_HUB_HOME`: `"project"` or `"user"`, nothing else (any other value
   is ignored with a one-line warning: a cloned repository must not choose paths the tools write to). `"project"` is
   `<main checkout>/.agent-hub/local/`, shared by all worktrees of the repository and added once to `.git/info/exclude`;
   `"user"` is the user default.
3. The user default, `~/agent-hub`, a visible directory.
4. Legacy: while `~/agent-hub` does not exist and `~/.claude/agent-hub` (the default up to 0.6) does, the legacy one,
   with a warning at session start, in `hub start` and in `hub home`.

Two choices. **One shared home** (`~/agent-hub`, recommended): hubs of different projects can talk and share the lock
board and the locks. **Inside the project** (`"project"`): nothing outside the repository, and projects do not see each
other. `git clean -fdx` deletes the project home, journals and registers included.

Why not under `~/.claude`: Claude Code treats `.claude` as a protected directory
([permission modes § Protected paths](https://code.claude.com/docs/en/permission-modes.md)). A Write or Edit there is
prompted in `default` and `acceptEdits`, routed to the classifier in `auto`, denied in `dontAsk`, and `permissions.allow`
rules cannot pre-approve it; only `bypassPermissions` passes. The Bash sandbox
([§ Protected paths](https://code.claude.com/docs/en/sandboxing.md)) denies writes to most of `~/.claude` with no
`allowWrite` exemption, so under `/sandbox` `jlog`, `ask` and `hub` could not write there at all. A plain directory
granted with `--add-dir`, `/add-dir` or `permissions.additionalDirectories` is writable by the sandbox and needs no
prompt for edits in `acceptEdits`.

A session started outside the home needs that grant: `/add-dir <home>` (this session), `{"permissions":
{"additionalDirectories": ["<home>"]}}` in `~/.claude/settings.json` (every session), or `claude --add-dir <home>`.
Children need nothing: `agent spawn`, a resume (`agent send` to a finished agent), the autopilot successor and the
headless successor get `AGENT_HUB_HOME=<the parent's home>`, so parent and children never resolve differently, and
`--add-dir <home>` when the home is not under their directory. A stage that is not in the resolved home but exists in
`~/agent-hub` or the legacy home is refused with an error naming where it is: migrate the legacy home (or `mv` that one
stage when the home is another one), set `AGENT_HUB_HOME` to that place, or `mkdir -p <home>/<stage>` to start afresh.

```bash
hub home [--cwd DIR] [--json]   # the home, the layer that chose it, protected or not, the grant lines with your path
hub home migrate                # dry run: what would move from the legacy home to the resolved one
hub home migrate --apply        # do it; --from DIR / --to DIR name other homes
```

`migrate --apply` refuses while any agent of any stage of the source is alive or a background hub (an autopilot
successor) of one of its stages runs, and when a source path already exists in the target. It copies into a staging
directory beside the target (modes kept), verifies the count and the bytes, moves the copy into place only then (a
failed copy leaves nothing at the target), rewrites the old absolute path in every `*.json`
under the new home (roles, agents' meta, `.jwait-state`, `.state`, autopilot state), leaves the `.md` history as written
and renames the source to `<source>.migrated-YYYYMMDD`. It never deletes; a second run says there is nothing to migrate.
Run it while no hub session of the source is working: it cannot see an interactive session, and a line such a
session writes during the copy stays behind in the renamed source.

## Configuration

Settings are environment variables; each can also be set in a `config.json` (below), the environment winning.

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_HUB_HOME` | `~/agent-hub` | The hub home above. The environment (any path), or a repository's `.agent-hub/config.json` with `"project"` or `"user"` only; the hub home's `config.json` cannot set it. [Where the hub's files live](#where-the-hubs-files-live). |
| `HUB_STAGE` | `default` | Stage when `--stage` is not given (environment only). |
| `HUB_TAG` | from `roles` | Journal tag of the caller (set for agents automatically; environment only). |
| `AGENT_HUB_TZ` | local zone | IANA time zone of journal times and deadlines. Hub-wide. |
| `AGENT_HUB_MODEL_MAP` | none | Opt-in pin of aliases to model ids (without it an alias follows the CLI, which resolves it to its latest model), e.g. `sonnet=claude-sonnet-…,opus=claude-opus-…` (in JSON also `{"sonnet": "…"}`). A model id may use letters, digits and `. _ : @ [ ] / -` only (a Bedrock id or an ARN is fine); a pair outside that is reported and left out. |
| `AGENT_HUB_DEFAULT_EFFORT` | `high` | Effort for `agent spawn` without `--effort` (haiku gets none). |
| `AGENT_HUB_ENGINE` | `claude` | Default executor engine (`claude` or `codex`); Codex SessionStart selects `codex` for that host. |
| `CODEX_BIN` | `codex` on PATH | Codex executable for detached workers. |
| `AGENT_HUB_CODEX_DEFAULT_MODEL` | CLI configured model | Optional Codex model pin when spawn omits `--model`. |
| `AGENT_HUB_CODEX_MODEL_MAP` | none | Explicit Codex model aliases; Claude aliases are not translated automatically. |
| `AGENT_HUB_CODEX_HOOK_TRUST` | `bypass` | Detached Codex hook trust policy: bypass runs all enabled hooks without persisted review; `reviewed` requires Codex trust. |
| `AGENT_HUB_PERMISSION_MODE` | `bypassPermissions` | Permission mode of headless agents (nobody is there to approve a prompt). |
| `AGENT_HUB_DEFAULT_REPO` | the git repository you run in (a worktree: its main repository), else `*` | Repository of `lock take/release` and of the main-merge lock `hub takeover --take-main-merge` takes; `*` (every repository) only outside a git checkout or with an explicit `--repo '*'`. `lock rules init` writes it into `.agent-hub/config.json`. |
| `AGENT_HUB_TAKE_MAIN_MERGE` | `false` | `true` (string or JSON boolean): `hub takeover` takes the hub repository's main-merge as if `--take-main-merge` were given. Without it, a free main-merge of a configured hub repository is reported in the digest. |
| `CLAUDE_BIN` | the newer of `claude` on PATH and the CLI bundled with Claude Desktop | The CLI to run agents with: a path, a name on PATH, or `desktop` — the newest CLI bundled with Claude Desktop (macOS), which follows Desktop updates. |
| `AGENT_INIT_TIMEOUT` | `120` | Seconds to wait for a new run's init event before calling the spawn failed. |
| `AGENT_HUB_REVIEWERS` | one `agent` entry | Ordered JSON list of reviewers, first available wins (`hub reviewer`); entries are agents or reviewer skills, with an optional `check` command, `until` date and change classes. A `check` is never run from a repository's config. [docs/reviewers.md](docs/reviewers.md). |
| `AGENT_HUB_REVIEW_MODEL`, `AGENT_HUB_REVIEW_EFFORT` | `opus`, `high` | Model and effort of an `agent` reviewer that names none. Pick a model other than your executors' (the reviewer is not the author). |
| `AGENT_HUB_BG_WAIT_CEILING_MS` | `0` | How long an agent's run, after its turn ends, waits for its background sub-agents before the CLI kills them (passed as `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`; `0` = until they finish, the CLI's own default is 10 min). |
| `AGENT_HUB_SEND_CAP` | `10` | Cross-session sends per sender before `roles` falls back to the journal (Claude Desktop only). Hub-wide. |
| `AGENT_HUB_NIGHT` | `23:00-08:00` | Night window for the optional `nightq`. Hub-wide. |
| `AGENT_HUB_HANDOFF_MAX_BYTES` | `15360` | Size cap of `HANDOFF-*.md` enforced by the hook. Hub-wide. |
| `AGENT_HUB_SCOPE_DIRS` | none | Directories, separated by `:`, where the `handoff_size` and `questions` hooks act in addition to the hub home and repositories with `.agent-hub/`. Hub-wide: a repository's `config.json` cannot set it. |
| `AGENT_HUB_JWAIT_MATCH` | none | Extra wake words, a regex added to the built-in `MERGED\|STOP\|DONE\|BLOCKED\|EXIT\|QUESTION\|AWAITING ANSWER`: used by the digest's `jwait` command and counted as an agent's status word. Hub-wide. |
| `AGENT_BOARD_FILE`, `AGENT_HUB_LOCK_RULES` | in the hub home | Override the board and the hub home's lock-rules file (environment only; a named lock-rules file must exist). |

### Configuration layers

A team keeps its conventions in its repository instead of forking the plugin. The tools read the same file names
from three places, most specific first (`agent-hub:setup` writes the first two files of the project layer for you):

| Layer | Where | Found by |
|---|---|---|
| stage | `<hub home>/<stage>/` | the command's stage |
| project | `<repo>/.agent-hub/` | the working directory, searched upwards to the git root (a linked worktree without its own `.agent-hub/` uses the main checkout's); for `agent spawn`, its `--cwd`; for the lock hook, the command's directory after `cd` / `git -C` |
| home | `<hub home>/` | always |

| File | Layers | Combination | Used by |
|---|---|---|---|
| `config.json` | project, home | per key, project first; hub-wide keys only from home | every tool |
| `lock-rules.json` | project, home | rules of both, project first; protected branches united | `board_locks` hook |
| `brief-footer.md` | stage, project, home | first found | `agent spawn`: appended after the standard footer; `{role}` `{tag}` `{stage}` `{report}` `{inbox}` are filled in |
| `handoff-facts.sh` | stage, project, home | first found | `hub handoff`: prints rows `\| What \| State \| Where it shows \|` for § 1 |
| `takeover.sh` | stage, project, home | first found | `hub takeover`: an extra verified step (below) |
| `hub-rules.md` | stage, project, home | all of them; a later layer wins on the same subject (home, then project, then stage) | the hub: overrides of the `hub` skill's recommended rules, each with its reason (example: [templates/hub-rules-example.md](templates/hub-rules-example.md)); the takeover digest points at it |
| `HUB-NOTES.md` | stage, project, home | first found | the hub: what the team knows (what needs the owner, how to check data claims, …); the takeover digest points at it and the `hub` skill reads it before planning |

`config.json` is a flat JSON object of the settings above; keys starting with `_` are comments. A key a layer may not
set (a hub-wide key in a repository, a misspelling) and a broken file are reported on stderr and ignored, so a typo
never stops a tool:

```json
{"_comment": "webapp hub conventions",
 "AGENT_HUB_MODEL_MAP": {"sonnet": "claude-sonnet-x-y"},
 "AGENT_HUB_DEFAULT_EFFORT": "high",
 "AGENT_HUB_DEFAULT_REPO": "webapp"}
```

`lock-rules.json` names the shared resources of your project and the commands that touch them, for example:

```json
{"protected_branches": ["main"],
 "resources": {"deploy-window": "a production rollout is in progress",
               "staging": "the shared staging environment"},
 "rules": [{"match": "\\bmake deploy-prod\\b", "kinds": ["deploy-window"], "action": "production deploy"},
           {"match": "\\bhelm upgrade .* -n staging\\b", "kinds": ["staging"], "action": "staging rollout"}]}
```

A lock is on a named resource. `main-merge` is the only one built in: `gh pr merge`, `glab mr merge`, merge calls
through `gh api` / `glab api` and `git push` to a protected branch (`main` and `master` unless `protected_branches`
says otherwise) need it. Every other resource — a deploy window, a staging environment, a migration head, a shared
test database — exists because your file names it. A name is lowercase letters, digits and hyphens. `resources`
(optional) declares the names with a description; when it is present, every rule's `kinds` must be declared there (or
be `main-merge`), so a typo is an error, not a lock nobody takes. A resource with no rule, such as the expected head of
a migration chain, is informational: people take and read the lock, no command is refused for it.

`match` is a Python regex searched in the command's words joined by single spaces; the first matching rule wins.
`kinds` is a non-empty list of resource names. A file that cannot be used (bad JSON, a bad regex, bad or undeclared
`kinds`, a symlink to a missing file) is skipped with a warning on every command — on stderr and to the user — while
the built-in rules and the other file keep guarding; fix it, the guard is incomplete until then. Rules in the hub home
apply to commands run anywhere, so keep there the rules that must hold outside a checkout (a deploy job started with
`-R group/repo` from your home directory), as a regular file rather than a symlink into a checkout whose branch can
change. Add `# lock-ok: <reason>` to a command to pass it deliberately. A lock guards one repository (`--repo`, default
`*`), so a rule known in every repository still only stops commands aimed at the locked one.

`lock take <resource>` refuses a name nobody configured where you run it and lists the known ones (a name already on the
board stays takeable, for a handover); `lock release` accepts any name. The rules have their own commands:

```bash
lock rules                                         # resources and the commands each one guards, here
lock rules init --protected main release           # writes .agent-hub/lock-rules.json + config.json
lock rules add staging --about "the shared staging environment" \
    --match '^helm upgrade\b.* -n staging\b' --action "staging rollout"
lock rules check "helm upgrade app -n staging" --expect staging     # runs the real hook on a scratch board
lock rules check "helm upgrade app -n preview" --expect-none
```

`takeover.sh` is run twice per takeover from the hub's working directory: `takeover.sh check` exits 0 when its target
state is already there (or there is nothing to do) and 1 when it must act; then `takeover.sh apply`, after which
`check` must exit 0. Any other exit stops the takeover like a failed built-in step; `--dry-run` runs only `check`. It
gets `HUB_STAGE`, `HUB_N`, `HUB_TAG`, `HUB_NAME`, `HUB_SESSION`, `HUB_CLI_SESSION`, `HUB_PREVIOUS`, `HUB_TAKEOVER_AT`,
`HUB_HANDOFF` and `AGENT_HUB_HOME`.

Scripts in `.agent-hub/` run with your permissions when you run `hub handoff` or `hub takeover` in that repository,
and `brief-footer.md` goes into your agents' prompts — treat the directory like a Makefile and review it in code review.

## Agent discipline

Three habits make long agent work slow and expensive, and instructions alone do not stop them: a session keeps going
long after its context is huge, a session waits for something in a foreground loop, and a subagent silently inherits
the session's (expensive) effort. The plugin ships one hook against each, every rule configurable, plus pinned-effort
worker subagents.

```text
 SessionStart ────────── delegation.py session-start   inject the delegation level's policy        (dial on)
 UserPromptSubmit ────┬─ delegation.py prompt          re-inject it after the level changed         (dial on)
                      └─ context_budget.py             warn once per step above the warn threshold
 PreToolUse  Bash ────── polling_guard.py              deny foreground wait loops, long sleeps,
                                                       self-matching pgrep -f, one-off CI status reads
             Agent|Task|Workflow ─ delegation.py pre-tool   deny by level rules and subagent effort rules
             * ───────── context_budget.py             past the block threshold deny Agent/Task/SendMessage
                                                       (a handoff still passes)
 PostToolUse * ───────── context_budget.py             warn once per step above the warn threshold
 agent spawn (CLI) ───── bin/subagent_rules.py         the same effort rules for headless agents
```

| Hook | Default | Prevents |
|---|---|---|
| `context_budget.py` | on (warn 300k, step 50k, block 500k tokens) | A session that keeps working with a huge context, where every turn re-reads it. Past the warn threshold it tells the session to write a handoff (`agent-hub:handoff`); past the block threshold it denies new `Agent` / `Task` / `SendMessage` calls unless the call hands work over (names a `HANDOFF-*.md` file or carries `handoff-ok`). With [autopilot](#autopilot-the-hub-hands-over-by-itself) on, a stage hub is told to hand over to a successor itself, and past the block threshold it is forced to. |
| `polling_guard.py` | on | Foreground waiting: `until …; do sleep N; done` (also inside `bash -c "…"` or text fed to a shell: `| bash`, `bash <<EOF`), a bare `sleep` over 30 s (`5m`, `1h` count), `pgrep -f` that matches the waiting shell itself, and one-off CI status reads (`gh run view/list/watch`, `gh pr checks`, `glab ci status`, `glab api …/pipelines`). Allowed: background commands, short bounded retries, logs and traces, write calls (`-X POST`, `-f`/`--field`), a pipeline lookup by commit sha, quoted text no shell runs (`git commit -m "… sleep 5m …"`, `grep "sleep 5m"`: quoted text is data unless it is the argument of `bash -c`, `eval` or `ssh`, or is fed to a shell), and anything with `# poll-ok: <reason>`. The message points at `run_in_background`, `jwait` and your own wait command. |
| `delegation.py` | dial **off**; effort rules none | The dial (levels 0-5, `/delegation`) tells the session how much to hand to subagents and denies `Agent`/`Workflow` at level 0. Effort rules deny subagent launches whose model × effort you do not want — in the session and in `agent spawn`. |

Each hook fails open: an error of its own (a broken config, an unreadable transcript) never blocks a tool call.

### Autopilot: the hub hands over by itself

Codex uses `hub succeed --engine codex` to start a detached Codex coordinator in its own worktree from the main
checkout. It preserves model, effort and supported sandbox restrictions, including full access, across handoffs.
Use `agent send` to reach it; [Codex support](docs/codex.md) describes its setup. The Remote Control procedure
below applies to Claude.

Off by default: it starts background sessions, which nobody should get unasked. Turn it on in the hub home's
`config.json` (`"AGENT_HUB_AUTO_HANDOFF": "on"`; `agent-hub:setup` asks). Then, in the session registered as a stage's
hub:

1. At the warn threshold the context-budget message becomes the procedure: at the next quiet point (no agent waiting
   for a reply, no merge or lock operation in flight) `hub handoff`, fill the TODOs, then `hub succeed` — the hook
   writes the exact command with the hub's model, permission mode and directory.
2. `hub succeed` starts `claude --bg --remote-control <stage>-hub-<n+1>` with the prompt
   `/agent-hub:hub take over stage … [agent-hub auto-handoff k/N]`, journals its id, its Remote Control link and
   `claude attach <id>`, and prints a `jwait` for the successor's takeover line (`AGENT_HUB_SUCCESSOR_TIMEOUT`).
   The successor starts the way a Claude Desktop session does: from the repository's main checkout, in a new worktree
   of its own (`--worktree <stage>-hub-<n+1>` → `<main checkout>/.claude/worktrees/<stage>-hub-<n+1>` on branch
   `worktree-<stage>-hub-<n+1>`, from the main checkout's HEAD; a taken name gets `-2`, `-3`…), never in the hub's
   own directory — that may be a Desktop session's worktree, removed when the session is archived. Outside git it
   starts in the hub's directory. Nothing removes the worktree: `claude rm <id>` does once the session is done.
3. When the line arrives the old hub tells you the successor's name and link in one line and stops. It releases
   nothing: the successor's `hub takeover` moves the locks.
4. Fallbacks, each journaled with its reason: bypass mode without the accepted disclaimer → `auto` (`acceptEdits` for
   Haiku); the CLI not logged in, or the main checkout not trusted by it →
   a headless hub (`agent spawn --cwd <main checkout> --worktree <stage>-hub-<n+1>`, in its permission mode: `bypassPermissions` unless `AGENT_HUB_PERMISSION_MODE` says
   otherwise — a `claude -p` hub has nobody to approve a prompt); no takeover by the deadline → `hub succeed --fallback` journals the session's log
   tail, stops it and starts the headless hub. You talk to a headless hub through `ask` and `agent send`.
5. At most `AGENT_HUB_AUTO_HANDOFF_CHAIN` automatic handoffs in a row (default 10). At the limit the hub writes its
   handoff, starts no successor and waits for you. Your own prompt in the hub's session, or a takeover you start by
   hand (without the `--auto-handoff` the successor's command carries), resets the count.

The numbers: the hub's own is its roles tag's (`hub-N`, a legacy `хаб-N`, any tag ending in `-N`), else the outgoing
number of the handoff given to `hub succeed`; the successor's comes from the function `hub takeover` numbers by, and the
successor's `hub takeover --auto-handoff` takes the number it was started under — so its name, its start line (the
`jwait` match) and the chain agree.

Past the block threshold the hub's Bash passes only when every command of the line is `hub handoff`, `hub succeed`,
`jlog` or `jwait` (output redirected only to `/dev/null`, a descriptor or a HANDOFF file), and Write/Edit only on a
`HANDOFF-*.md` file. Only the registered hub can run `hub succeed`, only with autopilot on (`--force` for you at a
terminal), and only one successor per shift starts; a refused call prints when to retry and the `jwait` to wait with.
A successor that never took over stops blocking the shift: `hub succeed --again` drops its record once it is not
running, and your own prompt in the hub's session drops it once the takeover timeout has passed. A sub-agent of the hub
shares the hub's session id and could run `hub succeed` too — the hub runs it itself, never delegates it.

A successor not in bypass mode starts with the hub's own commands (`hub takeover/handoff/succeed`, `jlog`, `jwait`,
`ask`, `roles`, `lock list`, `agent status`) and the hub home allowed (`--settings`), so it takes over without a prompt;
anything else asks, and you answer over Remote Control. It never gets `agent spawn` pre-allowed. Both kinds of
successor are pinned to the old hub's home (`AGENT_HUB_HOME`, plus `--add-dir <home>` when it is not under their
directory); the background one does not inherit `AGENT_SESSION_ID` (a headless hub's own id), which would make its
`--session self` name the old hub.

Requirements: a logged-in standalone `claude` CLI (`claude auth login` — Claude Desktop's login does not reach
`claude --bg`), the repository's main checkout trusted by the CLI (run `claude` there once and accept the prompt), and for a
successor in bypass mode a one-time `claude --dangerously-skip-permissions` in a terminal. How to reach the successor:
[Getting started](docs/getting-started.md#leave-the-hub-running).

### Worker subagents

A subagent runs at the effort its definition pins; without one it **inherits the session's effort**, so a session
at a high effort makes every search subagent just as expensive. The plugin ships `agent-hub:worker-low`,
`worker-medium`, `worker-high` and `worker-xhigh`: general-purpose subagents that pin only the effort, so you choose
the model per call:

```text
Agent(subagent_type="agent-hub:worker-medium", model="sonnet", prompt=…)
```

There is no model-pinned variant: an effort rule can require or forbid any model × effort pair, so a combination such
as "this model only at xhigh" is a rule, not another agent file.

### Settings

All settings follow [Configuration](#configuration): environment first, then `config.json`. **Hub home only** marks
the user's own limits, which a repository's `.agent-hub/config.json` cannot set; the others may also come from it.
The environment still wins for every key, so whatever sets environment variables for a session (your shell, a
`settings.json` `env` block) can change these limits too — the guarantee is about repository config files.

| Setting | Default | Where | Meaning |
|---|---|---|---|
| `AGENT_HUB_CONTEXT_BUDGET` | `on` | hub home only | `off` (or JSON `false`) disables the context-budget hook. |
| `AGENT_HUB_CONTEXT_WARN`, `AGENT_HUB_CONTEXT_WARN_STEP` | `300000`, `50000` | hub home only | First warning, then one more every step. |
| `AGENT_HUB_CONTEXT_BLOCK` | `500000` | hub home only | From here the tools below are denied. |
| `AGENT_HUB_CONTEXT_BLOCK_TOOLS` | `["Agent", "Task", "SendMessage"]` | hub home only | Tools denied past the block threshold. |
| `AGENT_HUB_CONTEXT_ESCAPE` | `HANDOFF-<name>.md` or `handoff-ok` | hub home only | Regex; a tool input matching it anywhere passes (handing over). Deliberately loose: the block is a nudge that leaves a trace in the transcript, not a lock — a prompt that merely cites a handoff file passes. |
| `AGENT_HUB_CONTEXT_TODO` | points at `agent-hub:handoff` | hub home only | The "what to do" sentence of both messages. |
| `AGENT_HUB_STATE_DIR` | `<hub home>/.state` | hub home only | Warning buckets and delegation levels. |
| `AGENT_HUB_AUTO_HANDOFF` | `off` | hub home only | `on` (or JSON `true`): [autopilot](#autopilot-the-hub-hands-over-by-itself) — the stage hub hands over to a successor by itself. |
| `AGENT_HUB_AUTO_HANDOFF_CHAIN` | `10` | hub home only | Automatic handoffs in a row without the owner; `0` = never start a successor. |
| `AGENT_HUB_SUCCESSOR_MODEL` | the hub's own | hub home only | The successor's model (alias or `claude-…` id); default: the model of the hub's last turn. |
| `AGENT_HUB_SUCCESSOR_PERMISSION_MODE` | `inherit` | hub home only | The successor's `--permission-mode`; `inherit` = the hub's own (plan mode starts it in the default mode). |
| `AGENT_HUB_SUCCESSOR_TIMEOUT` | `600` | hub home only | Seconds to wait for the successor's takeover line before the headless fallback. |
| `AGENT_HUB_POLL_GUARD` | `on` | repo or home | `off` disables the polling guard (e.g. in a repository with its own). |
| `AGENT_HUB_POLL_MAX_SLEEP`, `AGENT_HUB_POLL_MAX_BOUNDED_WAIT` | `30`, `90` | repo or home | Seconds: a bare sleep; a bounded loop's iterations × sleep. |
| `AGENT_HUB_POLL_ESCAPE` | `poll-ok` | repo or home | The marker word of `# poll-ok: <reason>`. |
| `AGENT_HUB_CI_STATUS_DENY`, `AGENT_HUB_CI_STATUS_ALLOW` | `gh` and `glab` lists | repo or home | Regex lists, searched in each command segment; a denied segment that matches an allow pattern passes. A list replaces the defaults — print them with `python3 hooks/polling_guard.py --defaults`. |
| `AGENT_HUB_WAIT_HINT` | a `gh run watch` line | repo or home | One line for the deny message: your project's own CI wait command. |
| `AGENT_HUB_DELEGATION` | `off` | hub home only | `on` (or JSON `true`) enables the dial: policy injection and level rules. |
| `AGENT_HUB_DELEGATION_DEFAULT` | `3` | hub home only | Level when no session, environment (`AGENT_HUB_DELEGATION_LEVEL`) or global level is set. |
| `AGENT_HUB_DELEGATION_LEVELS` | built-in texts | hub home only | `{"3": {"name": "BALANCED", "policy": "…"}, …}` — your text per level. |
| `AGENT_HUB_DELEGATION_COMMON` | one sentence | hub home only | Appended to every level's policy. |
| `AGENT_HUB_DELEGATION_RULES` | level 0 denies `Agent`, `Task`, `Workflow` | hub home only | Rule list, evaluated while the dial is on (may test `level`). |
| `AGENT_HUB_EFFORT_RULES` | none | repo **and** home | Rule list or shorthand for every subagent launch: the `Agent`/`Task` tool and `agent spawn`. The user's set (environment, else hub home) and the repository's are evaluated separately and any deny wins: a repository can add restrictions, never loosen yours. |

### Subagent rules

`AGENT_HUB_DELEGATION_RULES` and `AGENT_HUB_EFFORT_RULES` share one format: a JSON list, first match decides, no
match allows (each set on its own — see `AGENT_HUB_EFFORT_RULES` above). A rule's `when` tests fields of the call with globs (a list means "any of"):

| Field | Value |
|---|---|
| `tool` | `Agent`, `Task`, `Workflow`, or `agent-spawn` |
| `level` | the delegation level `0`-`5`, or `off` while the dial is off |
| `subagent_type` | as called, e.g. `agent-hub:worker-high`, `Explore`, `fork`; empty when not given |
| `defined` | `true` when a definition was found (project `.claude/agents`, `~/.claude/agents`, installed plugins' `agents/`) |
| `model` | the call's `model`, else the definition's `model:`, else `inherit`; for `agent spawn` the alias and the id it maps to |
| `model_from` | `param`, `definition` or `inherit` |
| `effort` | the definition's pinned `effort:`, else `inherit`; for `agent spawn` the effort used (`none` when the model takes none) |

```json
{"AGENT_HUB_EFFORT_RULES": [
  {"when": {"model": "*haiku*"}, "decision": "allow"},
  {"when": {"effort": ["inherit", "max"]}, "decision": "deny",
   "reason": "Pin the effort: use agent-hub:worker-medium or worker-high ({subagent_type} at {effort})."}]}
```

The shorthand `{"AGENT_HUB_EFFORT_RULES": {"sonnet": "high|xhigh"}}` means "this model only at these efforts". The
denial names the rule (`[AGENT_HUB_EFFORT_RULES rule 1]`); `delegation try --type <type> --model <model>` shows what
the rules say about a call without making it. A malformed list is reported on stderr and ignored.

[docs/examples/subagent-policy.json](docs/examples/subagent-policy.json) is a complete example for a user whose
sessions run at a high effort: the smallest model free at any type, every other model only through a pinned-effort
worker with an explicit model, one mid-size model only at high or xhigh, forks denied, level 0 closing `Agent` and
`Workflow`.

## Limitations

Codex-specific setup, trust requirements and platform differences are in [Codex support](docs/codex.md).
The Claude-specific facilities below apply when the selected host/engine is Claude.

- The `"project"` home is shared by the worktrees of an ordinary clone; the worktrees of a bare repository each get
  their own.
- macOS and Linux only (`fcntl`, `setsid`, `ps`, `curses`). Windows is not supported and WSL is untested; Claude Code
  itself runs natively on Windows. Python 3.10+ for Claude, 3.11+ for Codex; standard library only.
- The selected CLI must be on `PATH` (or set `CLAUDE_BIN` / `CODEX_BIN`); on macOS the CLI bundled with Claude Desktop is used when it
  is newer. Model aliases follow the CLI; Claude Code older than 2.1.287 is unsupported (its aliases resolve to older models).
- Headless agents run with `bypassPermissions` by default. Give every agent a brief that says what it must not
  touch, or set `AGENT_HUB_PERMISSION_MODE`.
- The hub home must be writable without a prompt, so keep it out of `.claude`, which Claude Code protects (the legacy
  `~/.claude/agent-hub` is read-only under `/sandbox`; `hub home migrate` moves it). A session started outside the home
  needs it granted (`/add-dir`); agents and the autopilot successor get the grant from the tools. The `"project"` home
  is deleted by `git clean -fdx`. See [Where the hub's files live](#where-the-hubs-files-live).
- The hub must be an interactive session (Claude Desktop, or a terminal session): its background `jwait` wakes it. In
  `claude -p` the hub's background Bash `jwait` is killed when the turn ends; `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`
  keeps background sub-agents alive, not background Bash tasks, so a headless hub learns about `DONE` only from its
  next message.
- One machine, one person: the files are local and the locks are advisory `flock`s plus a hook, not a distributed lock
  service. Two people cannot share a hub home (see [Team use](#team-use)).
- Locks guard only what the hook recognises: merges and pushes to protected branches, and the commands your
  `lock-rules.json` lists. A command run outside enabled, trusted host hooks, or one no rule matches, is not stopped.
- The turn limit of a brief is an instruction to the agent, not something agent-hub enforces. Cost and plan limits are
  Claude Code's, shared with your interactive session.
- Optional modules need macOS and Claude Desktop: the night nudge (waking a silent hub at night needs Claude Desktop's
  scheduled tasks; see [templates/night-nudge-task.md](templates/night-nudge-task.md)), the send budget, roles of kind
  `desktop` and `hub takeover --session local_…` (they read Claude Desktop's session metadata). Terminal sessions work
  as kind `cli`. Interactive terminal, `claude -p` and `claude --bg` sessions receive cross-session messages while
  their process is alive, and nothing once it is gone; for a headless agent prefer `agent send` (it resumes a finished
  session and leaves a journal line) — see [docs/launch-modes.md](docs/launch-modes.md).
- Autopilot needs the standalone `claude` CLI logged in and the project directory trusted by it (see
  [Autopilot](#autopilot-the-hub-hands-over-by-itself)); otherwise its successor is a headless hub, which you reach
  through `ask` and `agent send` rather than from your phone.
- `sendPrompt` buttons do not work in the Claude Code desktop tab, so the `/agent-top` widget has no buttons; it names
  the commands to type instead.

## Roadmap

What comes next and in what order: [ROADMAP.md](ROADMAP.md).

## Tests

```bash
bash tests/run_all.sh
```

Every test runs with `HOME` and `AGENT_HUB_HOME` in throw-away directories and a stand-in CLI
(`tests/fake_claude.py`) instead of `claude`, so nothing touches your real hub home and no model is called.

The agent-top mod has its own tests, `hooks/agent-top.test.tsx`: `claude plugin test .` from the plugin root, with a
Claude Code that has mods. `tests/t_mod.sh` checks the packaging and runs them when such a `claude` is on `PATH` (or in
`MOD_CLAUDE`); without one it prints SKIP.

## License

MIT — see [LICENSE](LICENSE).
