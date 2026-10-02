---
name: delegation
description: Show or change the delegation level 0-5 (0 - do everything yourself, subagents blocked by a hook; 3 - the default; 5 - orchestrator). Invoked as /delegation, /delegation 3, /delegation global 4, /delegation clear. Needs the delegation dial switched on in the hub home's config.json.
argument-hint: "[N | global N | clear | try TYPE MODEL]"
---

# Delegation level

Run bundled commands with the host's shell tool. Resolve the plugin root from `PLUGIN_ROOT`,
`CLAUDE_PLUGIN_ROOT`, or this skill's installed path; use `<plugin-root>/bin/<tool>` when PATH is missing
or shadowed. Session identity comes from the current host; use `self` where supported.

The level sets how much work this session hands to subagents; which model and effort they run at is decided by
your subagent rules (`AGENT_HUB_EFFORT_RULES`). The plugin's hooks inject the level's policy into the context at
session start and whenever the level changes; at level 0 a trusted hook denies the host's subagent-spawn tools.

Parse the user's arguments and run exactly one command (the plugin's `bin/` is on PATH):

| Arguments | Command |
|---|---|
| none | `delegation show` |
| `N` (0-5) | `delegation set N` — this session only |
| `global N` | `delegation set N --global` — every session without its own level |
| `clear` | `delegation clear` — back to the global level |
| `try <type> [<model>]` | `delegation try <type> [<model>]` — what the rules would say about such a native subagent call (no model: the definition's or inherited) |

The output holds the effective level and its policy. Work by it from this turn on: the command prints it exactly so
that a change applies now, not from the next message.

Answer in one or two lines: the effective level, where it comes from (session / global / default), and what it means
in practice. If the output says the dial is off, say so and name the setting (`"AGENT_HUB_DELEGATION": "on"` in the
hub home's `config.json`). On a non-zero exit show the error and do not change the level any other way.
