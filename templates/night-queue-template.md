# Night queue — <stage>
coordinator: <session id of the coordinator: a Claude Desktop local_… id, or a CLI session uuid>
night: <YYYY-MM-DD→DD>
updated: <YYYY-MM-DDTHH:MM> <who>

Check: `nightq check --stage <stage>` (exit 0 = format intact). The optional night-nudge task (see
night-nudge-task.md) wakes the coordinator named in `coordinator:` when it has been silent for > 30 min and this file
has an open `- [ ]` item. First action of the night: keep the machine awake (`caffeinate -dims -t 36000` in the
background on macOS).

## Permission matrix
| Class | What is allowed without the owner |
|---|---|
| `local` | the laptop: worktrees, tests, a PR without merging, reviews |
| `dev` | <what the owner allowed on the dev environment> |
| `stage` | everything, unless another session holds the `stage` lock (`lock list`) |
| `main` | merging into main — only the holder of the `main-merge` lock, and not inside someone else's `deploy-window` |
| `prod` | only an action the owner already said yes to: `yes:` with a date and a quote or link is mandatory |
| other | not queued: `ask add … --default "…" --due …`, then move on |

## Queue
Line: `- [ ] action | stop: stop condition | class: local|dev|stage|main|prod [| yes: 2026-09-24 "…"]`.
Done — `- [x] … | result: one line`; aborted — `- [x] … | result: STOP — reason` and a line in `night-log.md`.
