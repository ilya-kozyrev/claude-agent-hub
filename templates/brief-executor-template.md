# Brief: <what to do, one sentence> (<hub>, <date time>)

<!-- Template for a hub executor's brief. Every section is facts and paths, not a retelling of the conversation. ≤ 6 KB.
The hub fills "Owner decisions" from `ask search <topic words>` before sending; if nothing is found, write
"no decisions on this topic (ask search <words>)". -->

Executor — <model> (<effort>), journal tag `<hub-N-role>`. Production — <read-only | what is allowed and on which word (ask id)>.
`WK` = `<hub home>/<stage>/coordinator/work`. Repo / branch / worktree: <…>.

## Why
<The problem and its cost in one paragraph, with numbers and a source (journal, report, request).>

## Owner decisions — do not reopen
<id — the decision in ≤ 1 line, one per decision; from `ask search <words>`.>
The executor applies these as given. Data that disagrees with them is a fact for the report (a number, a query), not a
proposal to reopen them and not a question to the owner; the hub decides.

## What to do
1. <Step> — <a "done" criterion checkable by a number or a command>.

## Verification
<A positive and a negative control of the same query; targeted tests; what to show in the report / PR.>

## Answer and stop
Report `$WK/<tag>-REPORT.md` (≤ <N> KB, the outcome in the first line). Last action — `jlog --tag <tag> "DONE …"` or
`BLOCKED …`. At most <N> turns. A negative claim only with a positive control. <What not to do: writes, merges, nearby code.>
