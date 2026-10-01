# Changelog

## Unreleased

A newcomer test showed that a smaller model given "Use the agent-hub hub skill. …" never loaded the `hub` skill and
wrote the code itself, while a first message starting with `/agent-hub:hub` loaded it. The first group of changes below
is docs and skill text only.

- **The first message starts with `/agent-hub:hub`** in `docs/getting-started.md` (step 1, the takeover line, the
  sample session) and the README Quickstart, with the reason: the slash command always loads the skill, a
  plain-language mention may be ignored by a smaller model.
- **Getting started says what you should see** after the first message: the stage start line (`hub-1`) and a round of
  questions Q1, Q2 … each with a recommendation; if they are missing, the skill did not load.
- **Setup may be skipped in a new, empty project** (getting-started and README say so; the hub offers
  `agent-hub:setup` when it is needed). The README names the order: install, first message, setup per repository.
- **The `hub` skill describes more triggers**: the user mentions agent-hub or "the hub skill", or asks to plan work for
  agents or to run work through agents.
- **The `hub` skill opens with "First commands"**: `hub start`, `ask search`, one round of questions with a
  recommendation each, then a plan; no code and no agents before the owner approves it.
- **Grilling a non-technical owner** now has a mandatory question, "How will you open the result, and where should it
  live?", with a recommendation for a static site (GitHub Pages or an Artifact) over a server on the owner's machine.
- **Background processes.** The hub skill (§ Executors) and the executor brief template tell an executor to list the
  servers and watchers it started in its report and stop them before DONE; at handoff the hub checks for listening
  ports left by the project (`lsof -iTCP -sTCP:LISTEN`).
- **Writing into another stage's journal** takes your own tag, not `hub`: that stage's `jwait --tag hub` treats `hub`
  lines as its own and does not wake.

A second newcomer test took a Sonnet 5.5 hub through the whole flow (grilling, `hub start`, an agent in a worktree, an
Opus review, a fix round, a merge). It found agents running on old models, tools shadowed by same-named commands, and
a hub that talked the owner out of using agents.

- **Agents run on the latest models by default, through the CLI.** An alias (`opus`, `sonnet`, `haiku`, `fable`) is
  resolved by the Claude Code CLI; the plugin pins no ids (they go stale with the next model release), and
  `AGENT_HUB_MODEL_MAP` stays an opt-in pin. Claude Code 2.1.285 resolves them to `claude-sonnet-5-5`,
  `claude-opus-5-5`, `claude-haiku-4-5-20251001` and `claude-fable-5-1`; 2.1.274 resolved `sonnet` to `claude-sonnet-5`.
  - Without `CLAUDE_BIN`, `agent spawn` starts the newer of `claude` on `PATH` and the CLI bundled with Claude Desktop
    (a tie or an unreadable version keeps `PATH`) and prints which one it took and why.
  - The model id the run reports in its init event is recorded in the agent's meta (`resolved_model`) and shown by the
    `started headless agent` journal line (`claude-sonnet-5-5/high, asked for sonnet`), `agent status`, and `agent-top`
    (screen, `--once`, the widget, `--json` as `model_id`): `sonnet-5-5`, not `sonnet`.
  - `agent spawn` and `hub start` warn once when the CLI is older than 2.1.285: update Claude Code, an older CLI
    resolves the aliases to older models. The version is read from the `<version> (Claude Code)` line of
    `claude --version` (a shim's other lines are ignored), with a 5 s limit, and remembered by path, size and
    modification time in `<hub home>/.state/cli-version/`; `hub start --dry-run` writes nothing.
  - `fable` is accepted wherever `opus`, `sonnet` and `haiku` are: `agent spawn --model`, `hub reviewer`
    (`AGENT_HUB_REVIEW_MODEL`, a reviewer's `model`), the effort rules, the docs.
- **Tool isolation.** An agent's brief footer names `jlog` as `"$HUB_BIN/jlog"`: a shell may put an old `jlog` ahead of
  the plugin's, and its `DONE` would go to a journal the hub never reads. `HUB_BIN` is the plugin's `bin/`, exported in
  the agent's environment and rebuilt at every spawn and resume, so a resumed agent follows a plugin update (a path
  written into the brief would point into a version directory that is removed later). The agent already started with the
  plugin's `bin/` first on its `PATH`; a test now holds that. `hub start` and a new SessionStart hook
  (`hooks/path_shadow.py`) warn once when any command of the plugin (every executable in its `bin/`) resolves outside
  it, naming the path and the fix. The hook does nothing until a hub home exists, then speaks every time inside the
  hub's scope and once per distinct set of paths elsewhere. The usual cause is GitHub CLI `hub` from Homebrew (README).
- **`agent send` signs its journal line with the caller's tag**: `HUB_TAG`, else the roles-registry entry of the calling
  session (the hub keeps `hub-<N>`), else `cli`; it was `hub` for everyone, so a hub did not recognise a line written by
  someone else and a newcomer was alarmed.
- **Turns per run.** `agent status` and `agent-top` show the last run's turns next to the total once an agent was resumed
  (`turns 31 (total 60)`; `31/60` in the agent-top list), and so does the `EXIT` line.
- **`agent spawn --worktree` in a repository with no commits** fails with "the repository has no commits yet — make a
  first commit" and leaves nothing behind (it used to fail inside `git worktree add`). The check applies only where a
  new branch is made from `HEAD`: an existing branch works beside an unborn `HEAD`. The hub skill makes the first
  commit itself and says so in one line.
- **The `hub` skill, § Planning and § Choosing how to launch work:** the owner is asked nothing about process (agents or
  not, worktrees, commits); the hub picks the launch by the section's criteria and, when it writes a small change itself,
  says so in one line with the reason and records `ask decided`. Questions to the owner are in the owner's words; purely
  technical choices (canvas, localStorage, branch names) are the hub's, recorded with `ask decided` so they stay
  contestable. For a non-technical owner the hub opens the result (`open <path>`) or gives a `file://` link, never a
  long hidden path. Getting started: "A small change the hub may make itself; say 'through agents' if you want
  otherwise" and a short "A new, empty project" section that also holds the setup-skip sentence.
- **Limitations.** In `claude -p` the hub's background Bash `jwait` is killed when the turn ends;
  `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` keeps background sub-agents alive, not background Bash tasks, so a headless hub
  learns about `DONE` only from its next message (README, `docs/launch-modes.md`, getting started).

## 0.5.0 — 2026-10-01

Reviewers become a setting, the launch choice rests on what is visible before the start instead of an estimated
duration, and the polling guard stops denying quoted text that no shell runs (`git commit -m "… sleep 5m …"`,
`grep "sleep 5m"`) while catching more ways of feeding a loop to a shell.

- **Configurable reviewers.** New setting `AGENT_HUB_REVIEWERS` (environment, a repository's `.agent-hub/config.json`
  or the hub home's): an ordered JSON list, the first available entry wins. An entry is an `agent` (an ordinary
  `agent spawn`, model and effort from the new `AGENT_HUB_REVIEW_MODEL` / `AGENT_HUB_REVIEW_EFFORT`, default
  `opus` / `high`) or a `skill` (a reviewer skill the user plugs in), with an optional `check` command (exit 0 =
  available now, 10 s timeout, run in the hub home), `until` date and `for` change classes. A `check` from a
  repository's config is never run — the entry is skipped with a warning (the refusal covers the hub's own config
  files; a trusted repository's `.claude/settings.json` `env` block can still set the list). `name`, `skill`
  (`plugin:skill` allowed), `model`, `effort` and the change classes must match strict patterns from every layer, and
  every value of the printed `agent spawn` line is shell-quoted, so a repository's config cannot put commands or
  instructions into what the hub runs or reads. A broken entry is reported and skipped; a list with no valid entry gives
  the built-in default, one `agent` reviewer. The hub skill and `docs/launch-modes.md` no longer route reviews to a
  cloud session: a review is `hub reviewer`, and a cloud service is a reviewer skill if the user has one.
- **`agent spawn --model` is validated more strictly**, by the rule `hub reviewer` shares with it: `opus`, `sonnet`,
  `haiku`, an alias of `AGENT_HUB_MODEL_MAP`, or a full id `claude-…` made of letters, digits and `. _ : @ [ ] -` (a
  Vertex id `claude-sonnet-4-5@20250929` is fine) (it used to take anything starting with `claude-`). A mapped value
  of `AGENT_HUB_MODEL_MAP` must be a model id of the same characters plus `/` (a Bedrock id or an ARN is fine); a pair
  outside that is reported and left out. `--json` no longer repeats a `check` that was not run, and echoed keys and
  values are cut to 30 characters.
- **`hub reviewer [--for CLASS] [--json] [--all]`** walks the list and prints the chosen reviewer and exactly how to
  start it (the full `agent spawn` line with `<REPO>` / `<BRIEF>` placeholders and no `--worktree`, or "load skill …");
  `--all` lists every entry with why it was skipped; exit 1 when none is available.
- **`templates/brief-review.md`** (a self-contained review brief with a round-N variant) and **`docs/reviewers.md`**
  (the config, the choice order, the change classes `docs` / `code` / `risky`, the skill reviewer contract, how to
  write one). New recommended hub rules: a change gets the review its class says, and the reviewer is a different
  model from the author.
- **Launch choice by observable criteria.** The hub skill's "Choosing how to launch work" and the decision table of
  `docs/launch-modes.md` choose by what the work does: read-only with a short digest and nothing external to wait on
  is a sub-agent (foreground when the hub has nothing else to do, else background); anything that commits or pushes,
  waits on CI / a deploy / another party, touches production or must be reachable by someone else is `agent spawn`;
  estimated duration is a hint only. Every sub-agent brief ends with a call budget (a recommended N in the skill).
- **`hub handoff` guard.** Before writing the draft it looks for live sub-agents of the hub's own session
  (`--session`, else the registered hub's and the calling session when it is another one); if any runs it exits 2 and
  lists them (id, description, age) with the three ways out. `--allow-live-subagents` goes on and writes them into the
  draft's TODO. The discovery and state logic `agent-top` used for sub-agents moved to the shared `bin/subagents.py`;
  `agent-top` behaves as before.
- **`jwait` default `--for` is now 2h** (was 12h): a background Bash task is not guaranteed to live longer. The hub
  skill also says to add `--exclude-tag <hub tag>` when `jwait` is called with `--caller <session id>` instead of as
  the hub's tag, or the hub's own `@agent` messages wake it.
- **Polling guard: quoted text is data until a shell runs it.** Since 0.4.0 `git commit -m "… sleep 5m …"`,
  `grep "sleep 5m"` and the body of a `gh api` call were denied: a quote counted as the start of a command, so any
  quoted `sleep` or `while` looked like a wait (and `sleep 5m` now reads as 300 s). The guard now looks inside a quoted
  string only when a shell executes it — the argument of `bash|sh|zsh|dash|ksh -c` (also after `timeout`, `env`, `sudo`,
  `time`, or in `xargs sh -c`), of `eval` or `ssh`, a here-string to a shell, the text of `echo` / `printf` / `cat`
  piped to a shell, and `$(…)` inside double quotes. Every other quoted argument is data, and a `;` or `|` inside it no
  longer splits the command. **Not denied any more**, on purpose — 0.4.0 denied these only because every quote
  counted as a command: the `-c` / `-e` strings of interpreters (`python3 -c "import os; os.system('sleep 300')"`,
  `perl -e 'sleep 300'`, `node -e "execSync('sleep 300')"`) and the forms the guard does not look into, being no shell
  parser — `bash -c "$(echo '…')"`, `eval "$(…)"`, `bash <(echo '…')`, `VAR='until …'; bash -c "$VAR"`,
  `echo '…' > w.sh && bash w.sh`. Every other deny of 0.4.0 stays.
- Polling guard, CI-status rules: a quoted string is read only in a `gh` / `glab` command (it carries the API path), so
  `git commit -m 'ci: wrap gh run view in a script'` and `grep 'gh run view' f` are no longer reads of CI status; the text
  of a `gh` / `glab` call's own arguments (`gh issue comment 1 --body 'gh run view'`) still is.
- Polling guard, text fed to a shell: "fed" is decided per pipeline, not for the whole command; `xargs` counts only
  with `sh -c` (`echo "sleep 5m" | xargs echo` is not a wait); a shell behind a wrapper with flags (`sudo -u app bash`,
  `sudo -E bash`, `/usr/bin/env bash`, `time bash`), a heredoc that reaches a shell through an intermediate stage
  (`cat <<EOF | tee f | bash`), a line continuation or a trailing `|` before the shell, `(echo '…') | bash`, a shell
  word glued from several strings (`bash -c 'until … '"$F"' …'`) and shell options before `-c` (`bash -eo pipefail -c`,
  `bash -c --`), a here-string glued to `<<<` (`bash <<<'…'`), printing grouped in `( … )` or `{ …; }` and piped to a
  shell, a group around the consumer (`(bash <<< '…')`, `| (bash)`), blank lines after a `|`, the wrappers `setsid`,
  `command`, `nice`, `ionice`, `stdbuf`, `doas`, `timeout` with flags, and stdin shells behind `ssh host`, `su`,
  `sudo -i|-s` and `. /dev/stdin` are caught; `\$(…)` in double quotes is a literal, and a here-string is no longer
  read as a heredoc.
- Polling guard: only the 300 characters before a quoted string are read to decide whether it runs, so a command with
  tens of thousands of strings is judged in well under a second.

## 0.4.0 — 2026-10-01

A shape for teams other than the author's — generic lock resources, a setup flow, a first-hub start, the author's
hub rules kept as recommended defaults a project can override — and background sub-agents in the hub's toolbox.
**Breaking:** `deploy-window`, `stage` and `migration-head` are no longer built-in lock resources; a project that
uses them declares them in its `lock-rules.json` (same names, no board migration).

- **Choosing how to launch work.** `docs/launch-modes.md` and a section of the `hub` skill: when a piece of work is a
  foreground or background sub-agent of the hub, a headless agent, a cloud or a Desktop session, with defaults
  (~10 min / ~30 min) and the rule for a hub near its handoff threshold, backed by experiments with the CLI.
- `agent spawn` runs wait for their background sub-agents: `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` by default
  (the CLI kills them after 10 min otherwise); new setting `AGENT_HUB_BG_WAIT_CEILING_MS`.
- `agent-top` lists the sub-agents of the sessions in a stage's role registry, read-only, as `<role>/<id>`: state from
  the parent's transcript (completion notices; a foreground sub-agent's Agent-call result) and from whether the parent
  process runs (`~/.claude/sessions/<pid>.json`), current action, model and effort, feed from the sub-agent's
  transcript.
- **Locks on generic named resources.** Only `main-merge` is built in (merges into, and pushes to, the protected
  branches). Every other resource is named by the project in `lock-rules.json`, with an optional
  `"resources": {name: description}` object; when it is present, a rule naming an undeclared resource is refused (a
  typo is an error, not a lock nobody takes). `lock take` refuses a name that is not configured where it runs and
  lists the known ones; a name already on the board stays takeable (a handover); `lock release` takes any name; board
  records of any kind keep parsing. **Breaking:** `deploy-window`, `stage` and `migration-head` are no longer built
  in — a project that uses them declares them in its `lock-rules.json` (same names, no board migration).
- **`lock rules`**: `show [--json]` (resources and the commands each guards, here), `init` (writes
  `.agent-hub/lock-rules.json` and `config.json` with `AGENT_HUB_DEFAULT_REPO`), `add <resource> --about … [--match …
  --action …]` (validated before the file is replaced), `check "<command>" [--expect R | --expect-none]` (the real hook
  against a scratch board where every resource is held by someone else).
- **Skill `agent-hub:setup`**: asks which shared resources the project has and which commands touch each (numbered
  questions with recommended answers), writes the rules with `lock rules`, proves them with positive and negative
  checks. A project with no deployment ends with `main-merge` only.
- **`hub start --stage S --session ID`** registers the first hub of a new stage (stage directory, `hub-1`, start
  line, first `jwait`). `hub takeover` and `hub handoff` derive the shift number from `roles.json` and the latest
  handoff; `--n` is an override. The `jlog` "no tag" error says how the first hub registers.
- **`roles set`** infers the session kind from the id (`local_…` or a uuid Claude Desktop knows = desktop, any other
  uuid = cli) instead of defaulting to desktop.
- **`agent spawn --worktree [BRANCH]`** (default `agent/<role>`): an existing worktree of the branch is reused,
  otherwise `<repo>/.worktrees/<branch>` of the main repository, excluded in `.git/info/exclude`; `agent status` and
  `agent stop` name it.
- **Hook scope.** `handoff_size` and the SessionStart owner-questions line act only in the hub home, in repositories
  with `.agent-hub/`, under the new hub-wide `AGENT_HUB_SCOPE_DIRS`, and (questions) for hub agents. `board_locks`
  stays machine-wide: it acts only on protected-branch merges and pushes and on configured commands.
- **Hub skill**: "Starting a stage" first; a stated minimal mode (`agent` + `jlog` + `jwait`); the author's rules kept
  as recommended defaults with the reason for each, overridable in `hub-rules.md` (hub home → repository → stage,
  later wins; `templates/hub-rules-example.md`); the handoff threshold stated relative to the context window; night
  queue, night nudge and send budget marked as optional macOS + Claude Desktop modules; status words defined.
- A linked worktree without its own `.agent-hub/` uses the main checkout's (lock rules, config, brief footer, hub
  rules): an agent's `--worktree` no longer silently loses the repository's guards. `lock rules init` from a worktree
  configures the main checkout; `lock rules add` extends a file without `resources` by declaring the names its rules
  use; a relative `AGENT_HUB_SCOPE_DIRS` entry is ignored with a warning.
- **Templates**: a short `brief-executor-template.md`; the previous one is `brief-executor-advanced.md`. The handoff
  draft marks the night-queue section optional and points at worktrees to clean up.

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
