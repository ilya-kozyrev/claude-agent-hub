# Night queue — <stage>
coordinator: <session id of the coordinator: a Claude Desktop local_… id, or a CLI session uuid>
night: <YYYY-MM-DD→DD>
updated: <YYYY-MM-DDTHH:MM> <who>

Check: `nightq check --stage <stage>` (exit 0 = format intact). The optional night-nudge task (see
night-nudge-task.md) wakes the coordinator named in `coordinator:` when it has been silent for > 30 min and this file
has an open `- [ ]` item. First action of the night: keep the machine awake — the Claude Desktop tool
`request_keep_awake` (`until: "session_idle"`) when the session has it, otherwise `caffeinate -dims -t 36000` in the
background (macOS).

## Business DoD
<Source of the agreed result in the plan/brief/register; see skills/hub/SKILL.md, "Planning a stage".>
Queue items inherit it. Record delivered results against it, with technical evidence separately.

## Permission matrix
| Class | What is allowed without the owner |
|---|---|
| `local` | the laptop: worktrees, tests, a PR without merging, reviews |
| `dev` | <what the owner allowed on the dev environment> |
| `stage` | everything, unless another session holds the `stage` lock (`lock list`) |
| `main` | merging into main — only the holder of the `main-merge` lock |
| `prod` | only an action the owner already said yes to: `yes:` with a date and a quote or link is mandatory |
| other | not queued: `ask add … --default "…" --due …`, then move on |

## Queue
Line: `- [ ] action | stop: stop condition | class: local|dev|stage|main|prod [| yes: 2026-09-24 "…"]`.
Done — `- [x] … | result: one line`; aborted — `- [x] … | result: STOP — reason` and a line in `night-log.md`.
