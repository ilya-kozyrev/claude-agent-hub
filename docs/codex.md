# Claude Code and Codex

Workers default to the coordinator's current host: a Codex hub uses Codex workers and a Claude hub uses Claude
workers. At the initial planning step the hub offers the engine choice once, using that default; an explicit choice
is preserved in the stage rules, briefs and handoffs. Mixed teams are an explicit choice. Model and effort are
chosen after the engine, within its available models.

Review is a separate engine/model choice. For Sol-authored code, prefer a high-effort Claude Opus/Fable reviewer
when its limits allow; otherwise use an available Codex Astra at high. An older Sol is not the default reviewer
for Sol. Configure `AGENT_HUB_REVIEWERS` in that priority order with trusted availability checks; explicit reviewer
entries take precedence. The built-in Codex reviewer defaults to Astra and does not inherit the implementation
model from `AGENT_HUB_CODEX_DEFAULT_MODEL` or the CLI configuration. See [reviewer selection](reviewers.md).

The coordinator and its workers can use different engines. The shared journal, inbox, role registry, question
register, lock board and handoff files remain the protocol. Select an executor with `agent spawn --engine claude`
or `--engine codex`; sending, status and stopping use the engine recorded at spawn.

## Install in Codex

Codex support requires Python 3.11+ on PATH, including for native hook execution: native agent definitions and
configuration use the standard-library TOML parser. The Claude engine continues to support Python 3.10+.

Clone the repository if you do not have a local checkout yet:

```sh
git clone https://github.com/ilya-kozyrev/claude-agent-hub.git
cd claude-agent-hub
```

Use that checkout's absolute path in the marketplace command:

```sh
codex plugin marketplace add /absolute/path/to/claude-agent-hub
codex plugin add agent-hub@agent-hub-codex
codex plugin list --marketplace agent-hub-codex
```

Restart the Codex chat so it loads the installed skills, then ask for `agent-hub:setup` in the project.
Ask the session what is running; the `status` skill answers in words from fresh `agent-top` data.
`.codex-plugin/plugin.json` packages `./skills/` and explicitly selects `./hooks/codex-hooks.json`;
it does not load the Claude hook configuration. Installation and enabling do not grant hook trust: review
and trust the installed hooks in Codex before using them interactively. Untrusted hooks are skipped.
See [official plugin packaging](https://developers.openai.com/plugins/build/plugins) and
[hook trust](https://learn.chatgpt.com/docs/hooks).

Codex's SessionStart hook selects the Codex engine for that session. In a plain terminal, or when hooks are
untrusted, pass `--engine codex` or set `AGENT_HUB_ENGINE=codex`. In a plain terminal with no configured engine or detected Codex host, the default is `claude`.
Use the installed plugin's `bin/` directory explicitly if a command is absent or shadowed on PATH.

### Update to a new version

`codex plugin add` for a new version deletes every older version directory under the plugin cache,
`~/.codex/plugins/cache/<marketplace>/agent-hub/` (`$CODEX_HOME` moves it; the marketplace here is `agent-hub-codex`).
A Codex session that is still running on an older version loses its hooks the moment its directory is gone: the lock
guard and the other hooks stop applying to it. Before updating, copy the version directories aside; right after the
`add`, put back every one that vanished and check with `diff -rq` against the copy:

```sh
CACHE="${CODEX_HOME:-$HOME/.codex}/plugins/cache/agent-hub-codex/agent-hub"
SAVE="$(mktemp -d)"
cp -a "$CACHE/." "$SAVE/"                      # every version directory installed now

git -C /absolute/path/to/claude-agent-hub pull
codex plugin add agent-hub@agent-hub-codex

for dir in "$SAVE"/*/; do                      # put back each one the add removed
  v="$(basename "$dir")"
  [ -d "$CACHE/$v" ] || cp -a "$dir" "$CACHE/$v"
done
diff -rq "$SAVE" "$CACHE"                      # only the new version may be listed ("Only in …"), nothing else
```

Restart the Codex chat to load the new version. Remove an older version directory yourself once no session or
background worker runs on it.

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

The header labels Claude and Codex usage separately. Codex account limits come from the newest timestamped
observations in the last 256 KB of up to 32 recently modified local rollouts, refreshed every 30 seconds. These
are logged snapshots, without a network request or model call; the summary shows observation age and reset time.
Window labels use the reported duration (including plans with only a weekly window). Missing data is omitted,
not shown as zero, and separate `limit_id` buckets remain separate in the header and JSON `codex_limits` field.

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

To another stage's hub, use `tell <stage> "…"` first. For a direct message, use only the registry address from
`tell <stage> --address`; never select a session by its display name. Detached Codex hubs use `agent send` to the
matched worker role, including after `hub takeover` registers it as `hub`. Native Codex sessions on a CLI with
`queue` support use `codex queue --thread <registered UUID> --message "…"`. Resume is for a stopped worker.

`hub takeover` checks detached PID/process-token identity or the existing shared daemon's read-only `thread/read`
runtime status through `codex app-server proxy`. A missing/older CLI, unavailable daemon or unknown state is silent;
rollout recency alone is not liveness evidence. The warning never stops a session.
Native predecessor detection is verified only with a fake transport; it stays silent when no app-server daemon runs.

## Full access and hook trust

`--permission-mode bypassPermissions` is the detached default for both engines. Claude receives that mode;
Codex receives `--dangerously-bypass-approvals-and-sandbox`, equivalent to no approval prompts and
`danger-full-access`. Approval policy `never` alone does not grant full filesystem access.
This applies to spawn, resume and the Codex CLI autopilot successor. The lock hooks remain enabled in full access.
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

- Use `hub start --goal "<what the stage delivers>" --session self` and `hub takeover --session self` in either host. An ordinary shell must supply an
  actual session id. The Codex identity is `CODEX_THREAD_ID`; a detached worker also receives `AGENT_SESSION_ID`.
- Run one `jwait` through Codex's shell execution session and continuation tools. Keep individual blocking waits
  bounded so the coordinator can still respond; use its returned exit status. Claude's `run_in_background` and
  completion notifications are specific to Claude.
- `agent-top`, `agent-top --once` and `--json` work with both event streams. Codex values absent from its stream are
  shown as unavailable rather than inferred. Codex has no `/agent-top`: run `agent-top` in a shell. The live pane is a
  Claude Code mod and does not draw in Codex.
- Codex console autopilot (`hub succeed --engine codex --surface cli`, or automatic console detection) starts a detached Codex successor. It inherits the actual
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


## Desktop autopilot

`hub succeed --engine codex --surface auto` detects an actual app hub through both
`CODEX_INTERNAL_ORIGINATOR_OVERRIDE=Codex Desktop` and `CODEX_APP_TOOLS_PIPE_PATH`, excluding detached
`AGENT_ROLE` workers. `CODEX_THREAD_ID` alone identifies a Codex session, not a desktop surface. Detached children
strip app attribution/transport markers. `--surface cli` and `--headless` keep the ordinary detached launch,
model/effort/sandbox inheritance and fresh CLI worktree rules. `--surface desktop` prepares a request without
calling a CLI or accessing any app socket. It never silently falls back to CLI.

The current **app agent** executes this procedure automatically after preparing the handoff:

1. Run `hub succeed --stage <S> --engine codex --surface desktop --handoff <file>`. Keep its request token.
   The command reserves one successor/chain count and writes its takeover brief. Preparation is not launch success.
2. Call native `list_projects`. Find the unique saved local project whose path, normalized to its Git main
   checkout (including realpath/symlinks), matches the request's `project_root`. Use the returned projectId/path;
   if there is no unique match, report the failure and keep the predecessor. Never hardcode a project ID.
3. Run `hub desktop-request --stage <S> --request <token> --project-id <returned ID> --project-path <returned path>`.
   Its JSON has `create_thread` arguments and `already_dispatched`. Only when false, pass `create_thread` to
   the supported native `create_thread` tool. Dispatch is reserved before this call; a repeated command returns
   true and must not create another thread. The request uses the saved project's local environment by default, actual
   `model`/`thinking` fields when known. Only an explicit owner worktree request uses `--desktop-worktree` on succeed;
   it requires a Git project and omits startingState to use the project's default branch. An explicit existing
   `--branch <branch>` request also selects a worktree and supplies startingState. No branch is invented or created.
4. Confirm native output with `hub desktop-bind --stage <S> --request <token> --project-id <returned ID>` plus
   `--thread-id <actual threadId>` and/or `--client-thread-id <clientThreadId>`. Client IDs are opaque (for example
   `client-new-thread:…`), stored separately, and cannot become registry identities. If only a client ID returns,
   keep the request pending. Supported app observations or the successor's own registration can supply the actual
   ID. `list_threads` alone is not readiness proof: a newly running task may not appear there yet. Never use a
   client ID with a thread API, or invent an operation/host/thread ID. No operation API is called without a returned ID.
5. Continue the printed `jwait` in the shell harness, preserving its execution session and exit status. The successor
   runs its brief's `hub takeover --session self --auto-handoff --desktop-request <token>` from its actual cwd.
   Its own CODEX_THREAD_ID, main project, persisted rollout settings and stage-home write access are validated
   before role/lock migration. Takeover reconciles actual identity/cwd and retains the original chain count.
   If takeover prints `MOVE <path>`, run the printed command from that fresh worktree, keeping the same
   thread and request. The verified cwd is where takeover completes; a native local thread does not waive
   the hub location rule.
   Confirm `hub desktop-status --stage <S> --request <token> --verified` (exit 0) before stopping the predecessor.
   Status shows requested and observed model/effort/sandbox/approval separately. Report preservation only from
   observed data. Bind/takeover can arrive in either order; repeats retain the same identity/count. A later hub
   invalidates the request, so stale confirmations/takeovers cannot replace it.

The supported create_thread/handoff_thread schemas have **no sandbox or approval setting**. Requested policy is
carried in the brief/state, not smuggled into API arguments. Desktop defaults/UI determine actual policy. Full
Access cannot be promised by these APIs, and approval `never` is not Full Access. A successor with unknown rollout
policy, read-only access, or a workspace sandbox that excludes the stage home fails honestly before migration;
the predecessor stays active. If policy permits the home, status records the actual policy even when it differs
from requested. The protocol changes no global settings or installations and grants no broader access to other hubs.

On native error, run `hub desktop-fail --stage <S> --request <token> --why <reason>`. Unknown results retain an
uncertain reservation: inspect supported app evidence or await self-registration; do not create another successor.
Only confirmed failure **before any thread was created** permits `--no-thread-created`; this resets dispatch on the
same request. `hub succeed … --again --surface desktop` prints that same request without increasing the chain.
Once any client/actual ID was recorded, a no-create assertion is rejected. Desktop reservations survive timeouts
and owner chain resets; they are not automatically dropped while an app thread might still exist.

Successor briefs work the finite handoff queue first. `jwait` runs only while outstanding work or external events
remain; an empty/completed queue journals DONE and finishes without an unconditional nine-minute wait.
