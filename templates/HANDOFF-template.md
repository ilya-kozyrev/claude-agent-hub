# Handoff <role> — <stage> — <YYYY-MM-DD HH:MM> — ENTRY POINT

<!-- ≤ 12 KB (the handoff_size hook refuses a HANDOFF-*.md over 15 KB). Delete the role's older handoffs.
     Chronology and measurements go to journal-<date>.md next to it. Delete this file when the work it hands over is closed.
     `hub handoff --stage <stage>` writes a pre-filled draft of this shape. -->

Shift journal: `journal-<YYYY-MM-DD>.md`. Written by session "<title>" (<model>).

## Business DoD
<Agreed result/source from the plan, brief or register; see skills/hub/SKILL.md, "Planning a stage".>
Carry this result and owner-supplied constraints forward; choose implementation details independently.
Report progress against it with technical evidence separately.

## 0. First steps for the successor
<!-- 3–6 steps, each a command or a file: `ask list --stage <stage>`, `lock list`, the expected version of each
     environment, which background waits are running and where their output goes. -->
1.

## 1. Where things stand
<!-- Environments (versions, build ids), open PRs (number, head, CI), what was merged during the shift.
     Facts with their source. -->
| What | State | Where it shows |
|---|---|---|

## 2. Queue — by dependency, with a stop condition
<!-- Item = action | "done" check | stop: when and what then | who (model). Blocked items carry the question id
     (Q-A-00N); unblocked ones first. -->
1.

## 3. Night queue (optional module — delete this section if the stage has none)
<!-- Not a copy: `<hub home>/<stage>/night-queue.md` (format and permission matrix live there;
     `nightq check --stage <stage>` must exit 0). -->
`night-queue.md`: open <N>, next — <item>.

## 4. Owner questions
<!-- Not a copy: the register `<hub home>/<stage>/questions.md`, `ask summary` as one line here.
     A new question during the shift — `ask add` with --default and --due; your own decision on a matter the owner
     normally decides — `ask decided`. The owner's answer — `ask close`, and record it where decisions live the same day. -->
`ask summary`: <stage — open N, overdue M, …>. Overdue ones and what was done by default: <…>.

## 5. Risks and loose ends
<!-- What breaks when nobody watches and how it shows; bookings and windows (`lock list`); bugs found
     (issue or "none"); worktrees to clean up (`git worktree list`). -->
-
