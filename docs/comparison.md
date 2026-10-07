# Why and how Delamain compares

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
[Why a hub and headless agents](why.md).

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
| **Delamain headless agents** | Yes: detached `claude -p` or `codex exec` in its own process group; survives the hub closing, compacting or handing over | Yes: `agent send` writes its inbox while it runs and resumes it after it exits | Yes: Claude `--session-id` or the Codex thread id, kept in `meta.json` | Files: brief, inbox, journal, reports, question register | A lock board enforced by a hook: merges to protected branches and the commands you list | macOS and Linux; a third-party plugin, MIT |

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

What Delamain adds is not a new way to start a second session. It is a worker that survives a session boundary and a
handoff, an id fixed at spawn so any session can message or resume it by role, files as the protocol (a journal any
session can wait on, an owner-question register) and a lock board that refuses a merge, or a command you listed, for
everyone but the holder. If a sub-agent, a background session or `claude -p` covers your case, use it. The argument is in
[docs/why.md](why.md).

