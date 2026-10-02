# Claude Code and Codex

Workers default to the coordinator's current host: a Codex hub uses Codex workers and a Claude hub uses Claude
workers. At the initial planning step the hub offers the engine choice once, using that default; an explicit choice
is preserved in the stage rules, briefs and handoffs. Mixed teams are an explicit choice. Model and effort are
chosen after the engine, within its available models.

The coordinator and its workers can use different engines. The shared journal, inbox, role registry, question
register, lock board and handoff files remain the protocol. Select an executor with `agent spawn --engine claude`
or `--engine codex`; sending, status and stopping use the engine recorded at spawn.

## Install in Codex

Codex support requires Python 3.11+ on PATH, including for native hook execution: native agent definitions and
configuration use the standard-library TOML parser. The Claude engine continues to support Python 3.10+.

Use the repository marketplace from a local checkout:

```sh
codex plugin marketplace add /absolute/path/to/claude-agent-hub
codex plugin add agent-hub@agent-hub-codex
codex plugin list --marketplace agent-hub-codex
```

Restart the Codex chat so it loads the installed skills, then ask for `agent-hub:setup` in the project.
`.codex-plugin/plugin.json` packages `./skills/` and explicitly selects `./hooks/codex-hooks.json`;
it does not load the Claude hook configuration. Installation and enabling do not grant hook trust: review
and trust the installed hooks in Codex before using them interactively. Untrusted hooks are skipped.
See [official plugin packaging](https://developers.openai.com/plugins/build/plugins) and
[hook trust](https://learn.chatgpt.com/docs/hooks).

Codex's SessionStart hook selects the Codex engine for that session. In a plain terminal, or when hooks are
untrusted, pass `--engine codex` or set `AGENT_HUB_ENGINE=codex`. The general default remains `claude`.
Use the installed plugin's `bin/` directory explicitly if a command is absent or shadowed on PATH.

### Terminal monitor and older installations

Plugin installation does not replace personal commands or wrappers in `~/.local/bin`, or upgrade an already
running `agent-top`. A wrapper that searches only the Claude cache can keep launching 0.7.x after installing
Codex support. That monitor does not understand Codex process tokens or JSON events: a living Codex worker can
appear dead, with zero turns and an empty feed. Run the new installed plugin's `bin/agent-top` directly, or update
your terminal PATH/symlinks to that directory, then quit and restart the old monitor.

For a version-resolving personal wrapper, search both `~/.claude/plugins/cache/*/agent-hub/*/bin` and
`~/.codex/plugins/cache/*/agent-hub/*/bin` (honour `CLAUDE_CONFIG_DIR` / `CODEX_HOME` overrides). Compare the numeric
version component, not the full path, and use the newest shared runtime. The runtime supports both engines;
choosing its installation directory does not choose the worker engine. Check the selected monitor with
`<installed-plugin>/bin/agent-top --json --agent <role> --feed 10`, using the same hub home and stage as the UI.

## Spawn, message and resume

```sh
agent spawn --engine codex --role builder --cwd /absolute/path/to/project \
  --brief /absolute/path/to/brief.md --worktree
agent status builder
agent send builder "Continue with the next item in the brief"
agent stop builder
```

For Codex, leaving out `--model` uses `AGENT_HUB_CODEX_DEFAULT_MODEL` if configured, otherwise the CLI's configured
model. Pass an available model id when you need a pin; `AGENT_HUB_CODEX_MODEL_MAP` provides explicit aliases.
The plugin does not silently translate Claude model aliases into GPT ids. `CODEX_BIN` chooses the executable.
Choose an effort supported by the selected model with `--effort`.

Before a stage's first detached launch for a CLI/model, check the selected CLI with `codex --version` and
`codex debug models` (substitute `CODEX_BIN` when configured). The desktop app and standalone CLI can have different
model availability. Ordinary implementation uses an available Sol-family model, or the owner's explicit choice.
An unavailable Sol version calls for a CLI compatibility check or an available Sol peer, with the fallback reported;
Astra needs a task-based judgement reason. A model startup error alone does not justify that model class change.

Codex launches with `codex exec --json`; its `thread.started` event supplies the actual thread id saved in
`meta.json`. A message to a finished worker uses `codex exec resume` with that id. A message to a running worker
is appended to its inbox, which the brief tells it to read after each major step. No Claude cross-session API is
needed. See [non-interactive Codex](https://learn.chatgpt.com/docs/non-interactive-mode).

## Full access and hook trust

`--permission-mode bypassPermissions` is the detached default for both engines. Claude receives that mode;
Codex receives `--dangerously-bypass-approvals-and-sandbox`, equivalent to no approval prompts and
`danger-full-access`. Approval policy `never` alone does not grant full filesystem access.
This applies to spawn, resume and the Codex autopilot successor. The lock hooks remain enabled in full access.
See [Codex CLI options](https://learn.chatgpt.com/docs/cli/reference).

Hook trust is a separate control. Detached Codex workers explicitly load the bundled Codex hooks and default
`AGENT_HUB_CODEX_HOOK_TRUST=bypass`: the launcher passes `--dangerously-bypass-hook-trust` so autonomous runs do
not wait for an interactive trust review. **That flag applies to every enabled non-managed hook in that invocation,
including user and project hooks, not only agent-hub's hooks.** Use it with hook sources you have vetted.
Set `AGENT_HUB_CODEX_HOOK_TRUST=reviewed` to require Codex's persisted trust instead; review/trust the definitions
before starting a detached run. Changed hook definitions require renewed review in that mode.

For a restricted reviewer, choose the sandbox explicitly:

```sh
agent spawn --engine codex --role reviewer --cwd /absolute/path/to/project \
  --brief /absolute/path/to/review-brief.md --sandbox read-only
```

The sandbox selection replaces full access for that worker. A read-only worker cannot append a journal or report
on disk: use its captured result/status or explicitly permit the output location through the appropriate sandbox
configuration. `workspace-write` is another supported sandbox. A sandboxed interactive coordinator may need
`--add-dir <hub-home>` to write to the shared home. Full access needs no directory grant.

## Native Codex subagents

Claude's `agents/worker-*.md` files remain Claude definitions. Codex uses standalone TOML files in
`.codex/agents/` or `~/.codex/agents/`; the plugin manifest does not register them automatically.
The setup skill offers four matching effort-pinned files under
`skills/setup/resources/codex-agents/worker-*.toml`. Copy selected files into the project or personal agent directory
without overwriting an existing definition. Their `model` is deliberately omitted: choose an available model at spawn.
See [native Codex subagent configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents).

For detached executors, use `agent spawn --effort`; native TOML files govern in-session subagents, not that launcher.
The delegation dial and effort rules apply through trusted Codex hooks to native spawn calls. Verify your configured
rules with `delegation try`; prefer explicit definitions when effort inheritance would waste the coordinator's budget.

## Coordination and platform differences

- Use `hub start --session self` and `hub takeover --session self` in either host. An ordinary shell must supply an
  actual session id. The Codex identity is `CODEX_THREAD_ID`; a detached worker also receives `AGENT_SESSION_ID`.
- Run one `jwait` through Codex's shell execution session and continuation tools. Keep individual blocking waits
  bounded so the coordinator can still respond; use its returned exit status. Claude's `run_in_background` and
  completion notifications are specific to Claude.
- `agent-top --once`, `--json` and `--widget` work with both event streams. Codex values absent from its stream are
  shown as unavailable rather than inferred. A host that can preview local HTML may open the widget file;
  otherwise the skill returns the text snapshot. No Claude live artifact is required.
- Codex autopilot (`hub succeed --engine codex`) starts a detached Codex successor. It inherits the actual
  rollout model, reasoning effort and sandbox policy, or the recorded launch settings when discovery is unavailable. Supported
  workspace policy fields include network access, writable roots and temporary-directory exclusions; unknown
  policy fields are refused explicitly instead of discarded. An unspecified model
  stays with the CLI configuration. Interactive approval policies become `never` for unattended successors: denied
  tools fail, with no fallback to broader access. `--again` keeps a dead successor's recorded model, effort and sandbox policy. An absent effort stays with the launcher
  default; unsupported effort values are refused before launch.
  `AGENT_HUB_SUCCESSOR_ENGINE` selects a hub-wide successor engine; `--engine` overrides it. The chain limit,
  reservations and takeover checks prevent duplicate launches. Reach the successor through `agent send` and the shared registers;
  in Git, it starts from the main checkout in a fresh named worktree so archiving the old coordinator cannot remove its directory.
  Outside Git it keeps the supplied directory.
  The Claude Desktop/Remote Control phone workflow stays Claude-specific.
- Night queue files and permissions work with both engines. The optional Claude Desktop scheduled nudge and
  Claude outgoing-message budget remain platform-specific; they are not installed as Codex scheduled tasks.

Only commands observed by enabled, trusted hooks can be guarded. External terminal commands and commands that
match no configured rule remain outside the lock board's enforcement. The files remain local to one person and machine.
