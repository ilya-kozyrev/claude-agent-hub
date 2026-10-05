# Monitoring agents

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

### agent-top inside Claude Code: a live pane

Claude Code (mods are on by default) runs the plugin's mod, `hooks/agent-top.tsx`, in the terminal and in the
Desktop Code tab:

- **`/agent-top [role] [--stage S] [--all]` opens a pane**, and so does the `agents ● 4 ✓ 9 ✗ 0` button in the prompt
  footer next to the model picker; a second `/agent-top` or a second press closes it. The mod registers `/agent-top`
  itself and also answers `/agent-hub:agent-top`. It never opens by itself. Views: **Agents** (`a`; ↑/↓ move
  the `❯` cursor, Enter or the row's digit `1`–`9` opens the agent card), the **agent card** (state, model, turns, a
  context bar against the model's window, cost, result; a live feed of the last 30 events; `b` goes back), **Journal**
  (`j`) and **Summary** (`s`: plan-limit bars including Codex, owner questions, locks). Each agent is two lines with a
  coloured state badge (LIVE, QUIET, DONE, FAIL, DIED); a long list is a window around the cursor. Docked beside a
  fullscreen transcript the pane is framed and the card takes its state's colour; above the prompt and when narrow it
  drops the frames. It refreshes every 3 s while open; a role opens that agent's card; Esc closes it. Claude and Codex
  agents are listed alike, as in the console.
- **A status line and toasts.** The status line reads `agents ● 2 ✓ 5 ✗ 1` (nothing when there are no agents). A toast
  appears when an agent finishes, fails or dies and when a new owner question opens; what was already there when the
  session started is never announced. With the pane closed the mod looks every 15 s.
- **Read-only.** No send, stop or message button. The mod writes nothing: it runs `bin/agent-top --json` and draws the
  result. Messaging and stopping stay in the console (`m` / `x`) and in `agent send` / `agent stop`.
- **Where mods do not draw there is no `/agent-top`:** Codex, VS Code chat, `claude -p`, Remote Control and
  `claude --bg` views, Claude Code older than 2.1.287. Use the console in a shell: `agent-top` (live), `agent-top --once`
  (text picture), `agent-top --json` (scripts). If `bin/agent-top` is missing the mod goes quiet instead of failing.

