# Roadmap

What is planned next, in order. An item moves to the [CHANGELOG](CHANGELOG.md) when it ships. No dates are promised.

## In progress

- **Configurable reviewers.** `AGENT_HUB_REVIEWERS` lists reviewers in order of preference; the first available one
  is used. A reviewer is an `agent spawn` by default; a user may plug in reviewer skills of their own or anyone's.
  `hub reviewer --for <class>` prints which one to start and how. A repository's config can never make the hub run a
  command.
- **Launch choice by observable criteria.** Whether a piece of work is a sub-agent or a headless agent is decided by
  what it does (reads only, or commits, waits on CI, touches production, must be reachable by others), not by an
  estimate of how long it takes. `hub handoff` refuses while the hub's session still has live sub-agents.
- **Polling guard: quoted arguments are data.** `grep "sleep 5m"` and `git commit -m "… sleep 5m"` are no longer
  denied; only text a shell executes (`bash -c`, `eval`, text piped into a shell) is checked for wait loops.

## Next

1. **Interface language.** `AGENT_HUB_LANG` (default `en`; `ru` ships too; any other language is a JSON
   catalog in the hub home, no fork). It covers what a person reads — `agent-top` in every view (screen, `--once`)
   and the summaries printed for the owner. Journal status words (`DONE`, `BLOCKED`) stay as they are:
   waiters match them. Text written for the model (skills, hook messages) stays English; the hub answers in the
   user's language anyway. A test fails the build when a catalog misses a key.
2. **First-run setup wizard.** `delamain:setup` grows from lock resources into the one flow a new user runs after
   installing: where the hub runs (Claude Desktop or a terminal, which decides the optional modules), shared resources
   and the commands that touch them, reviewers, models and context window (the handoff threshold and the context
   budget follow from it), the default delegation level, how the project waits for CI, a `hub-rules.md` of the team's
   own, the `grilling` skill, the interface language. Each answer is proved with a check (`lock rules check`, `hub reviewer --all`,
   `delegation show`), and the flow ends with `hub start`. Running it again shows the current values and changes only
   what you answer differently; `--defaults` for scripted installs. Its questions are shaped by where new users
   actually get stuck.
3. **Executors on other runtimes, Codex first.** `agent spawn --runtime claude|codex`: the agent is launched with
   `codex exec --json`, its thread id is kept for `agent send` (`codex exec resume`), and a JSONL adapter feeds
   `agent-top`; the journal, role registry, inbox and `EXIT` lines stay the same. Work moves off the Claude plan's
   limits onto another vendor's. Claude Code hooks (the lock guard, the polling guard, the context budget) do not run
   inside Codex, so a Codex executor's boundaries come from Codex's own sandbox and approval mode, or its work ends at
   a commit in its worktree and the hub pushes — stated as a requirement, not left to be discovered. A reviewer entry
   gets `runtime: codex` as well.

## Considered, not planned yet

- **`claude --bg` as a backend for `agent spawn`** (a supervisor process, `claude attach` for the owner): waits until
  agent view leaves research preview; a second code path is not worth it before then.
