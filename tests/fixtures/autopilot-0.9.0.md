**Autopilot** (`AGENT_HUB_AUTO_HANDOFF=on`; `<plugin-root>/docs/reference.md`, "Autopilot"): the context budget message tells you when, and gives
the `hub succeed` command with your model, effort, mode and directory filled in. At a quiet point — no agent waiting for your
reply, no merge or lock operation in flight: `hub handoff`, fill the TODOs, run that `hub succeed … --handoff <draft>`,
start the `jwait` it prints using the host wait procedure below. Its start line → tell the owner one line (the successor's
name and any link returned by the launcher) and stop: no more tool calls, no lock released. ALARM → `hub succeed --stage <S> --fallback` (a
headless successor's ALARM: `--again`, if `agent status` says it is not running). A refusal that prints a `jwait` →
run that `jwait`, then retry. Exit 3 (chain limit), exit 2, or any other exit 1 → tell the owner the handoff path and
why, and wait for them ("cannot determine the effort" means your own effort is unreadable here: never pass a guessed
`--effort`; `hub effort` lists what was tried). A successor that took over but has to be swapped (a wrong launch): `hub succeed --stage <S>
--replace` — it stops that successor (not while it is busy, unless `--force`) and starts a new one from the same handoff
with the same number and chain position; never launch a replacement by hand with a bare `claude --bg`. Run `hub succeed`
yourself, never from a sub-agent.
