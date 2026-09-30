---
name: agent-top
description: Show what the headless agents are doing — a snapshot widget in chat with each agent's state, task, current action, plan limits and locks, or one agent's live feed. Use when the user asks what the agents are doing, invokes /agent-top, or names an agent to look at.
argument-hint: "[role] [--stage S] [--all]"
---

# agent-top — agents as a chat widget

`agent-top` (on PATH while the plugin is enabled) builds both the data and the markup. You only show what it made:
do not write or edit the HTML by hand, and do not repeat the table in prose.

## Without a role (`/agent-top`, `/agent-top --stage S`, `/agent-top --all`)

1. `agent-top --widget [--stage S ...] [--all] > "$TMPDIR/agent-top-widget.html"; echo "exit=$?"`, then read the file.
   Exit ≠ 0 — show the error in one line and stop.
2. If a widget tool is available (for example `show_widget` of the visualization tools; load its instructions first
   if it asks for that), show the file content **byte for byte** with the title `agent_top_snapshot`.
   Without a widget tool, run `agent-top --once [--stage S ...] [--all] --width 100` instead and show its output in a
   ```text``` block.
3. After it — one or two lines only if there is something to say: failed agents (`error`/`died`), `quiet` ones,
   overdue questions, a plan limit ≥ 90 %. Otherwise say nothing.

## With a role (`/agent-top <role> [--stage S]`)

1. `agent-top --once --agent <role> [--stage S] --width 100 --lines 30 > "$TMPDIR/agent-top-card.txt"; echo "exit=$?"`,
   read the file.
2. Answer: two to four lines — the task, what it is doing now, its last thought, the result or unread inbox messages;
   then only the card and the feed from the file (everything below the `───` rule; the agent list above it is not
   needed) in a ```text``` block.

## Do not

- Message or stop agents from here: this skill only looks. `agent send` / `agent stop` run only on the user's direct request.
- Poll in a loop: each `/agent-top` is one snapshot.
- Rely on buttons: `sendPrompt` from a widget does not reach the session in the Claude Code desktop tab, so the widget
  names the commands to type instead.
