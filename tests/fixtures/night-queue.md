# Night queue — stage-a
coordinator: PREV_ID
night: 2026-09-25→26
updated: 2026-09-25T22:30 Hub stage-a #16

Check: `nightq check --stage stage-a` (exit 0 = format intact).

## Queue
Line: `- [ ] action | stop: condition | class: local|dev|stage|main|prod [| yes: date "quote"]`.

- [x] Rebase the feature branch on main | stop: conflict — hand back to the builder | class: local | result: rebased, CI green
- [ ] Run the full test suite on the feature branch | stop: a red test — journal it and move on | class: local
- [ ] Refresh the staging database | stop: the stage lock is held by someone else | class: stage
