# Brief: review <branch or PR> in <repository>

<!-- Self-contained brief for a reviewer — an `agent` reviewer (`hub reviewer` prints its `agent spawn` line) or a
reviewer skill; docs/reviewers.md has the contract. The reviewer has not seen the conversation: everything it needs
is here. Fill every <…>; delete the "Round N" section for a first review. -->

## What changed and why
<The problem in two or three lines, with a source (an issue, a journal line, a report). Then what the change does,
one line per file or area that matters. Name the decisions the owner already took that the change relies on —
"do not reopen" for the reviewer too.>

## The change
- Repository: `<absolute path of a checkout that has the head commit>`
- Base: `<base sha>`   Head: `<head ref or sha>`
- Diff: `git diff <base sha>..<head sha>`; the commits: `git log --oneline <base sha>..<head sha>`
- Tests and how to run them: `<command>`; what a green run proves, and what it does not.

## Look hardest at
<The two to five places where a mistake costs the most or the author is least sure: a migration, a permission check,
money arithmetic, a retry loop, a rename that missed a caller. For a change of class `risky` (money, migrations,
production, permissions) say here which risk the review is narrowed to, and leave style out.>

## How to review
- **Read-only.** Do not edit, commit, push, merge or run anything that changes state outside your own report. You may
  run the tests and read anything in the repository.
- Check the change against the intent above, not only the diff in isolation: read the callers and the tests of what it
  touches.
- Findings, ranked **high** (wrong result, data loss, security, breaks the build), **medium** (a real defect with a
  narrower trigger, a missing test for new behaviour) and **low** (style, naming — only if cheap). For each:
  `file:line` — the defect in one sentence — a concrete failing scenario (inputs or state, and the wrong output or
  crash) — the fix in one sentence. A finding without a scenario is an opinion: say so, or leave it out.
- No praise and no summary of the diff. If nothing is wrong, say "no findings" and what you checked.
- Say whether you ran the tests, which, and the result. "Not run" is an acceptable answer; a guess is not.

## Answer
Write the review to `<review file>` (an `agent` reviewer: the report file its footer names), findings first, then one
verdict line:

`VERDICT: merge` | `VERDICT: merge after fixes` (every high and medium finding is fixable without a redesign) |
`VERDICT: changes requested`

Then report the path of the file in one line. At most <N> tool calls: if you are not done by then, stop and return what
you have and what is left.

## Round N (delete for a first review)
<!-- From the second round on. -->
This is round <N>. The previous round's findings, verbatim:

```
<paste the previous review's findings here, unedited>
```

- Review only the fix commits: `git diff <previous head sha>..<new head sha>`. Do not re-review what the earlier round
  already covered.
- For each earlier finding say **fixed** (and where), **not fixed**, or **disagree** with the author's reason, quoted.
- A new finding inside the fix commits is in scope. One outside them counts only if it is **high** and has a concrete
  failing scenario; from round three on, that holds for every new finding.
