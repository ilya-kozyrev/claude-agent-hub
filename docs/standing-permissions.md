# Standing permissions — design note

Read this when changing `ask allow` / `ask revoke`, the "covered" check of `ask add`, or the permissions block of
the `hub start` / `hub takeover` digest. For the commands, see [Reference](reference.md#standing-permissions).

**Problem.** Hubs parked finished work behind a per-item word of the owner although the owner had already allowed
that class of action, and invented gates (a "from 10:00") nobody set. A permission recorded in one stage's register
was invisible to the hub of another stage working on the same repository, which then asked again and duplicated the
work. A standing permission is the owner's word that a class of action needs no further question, recorded once and
seen by every stage whose action it covers.

**Record.** An `A-` entry in the stage's own register (`<hub home>/<stage>/questions.md`), next to the `Q-`/`D-`/`P-`
entries and with the stage's id prefix, written by `ask allow`:

```
## A-09-001 — merge a PR after green CI and one review
- kind: allow
- status: allowed            (allowed | revoked: <reason> (<date> <HH:MM>))
- scope: repo                (repo: the repository's actions, asked from any stage | stage: this stage only | all)
- repo: claude-agent-hub     (repository name as the lock board names it; "*" with scope all)
- class: merge, release      (optional keywords, comma-separated; the title is the class in free text)
- words: «можно накатывать»  (the owner's words, required: no words, no permission)
- asked: 2026-10-06 16:01    (given at)
- by: hub-09
- until: not set             (or YYYY-MM-DD[THH:MM]; after it the permission no longer applies)
- source: owner chat 06.10, Q-09-002
```

**Where it lives and why there.** In the stage registers, not in a shared file. Every reader of permissions scans
`<hub home>/*/questions.md`, as `ask search` already does, so a permission recorded in stage Y is seen by stage X.
The register already has the lock, the atomic write, the id prefix and the hand-editable format; a permission stays
next to the question its words answered; an older plugin skips the unknown `A-` heading instead of misreading it.
A shared file would add a second lock and a second format for the same kind of record.

**Applicability.** A permission applies to a question asked in stage S about repository R when it is `allowed`,
its `until` has not passed, and its scope is `all`, or `repo` with `repo` = R, or `stage` with the recording stage =
S. R is the question's `--repo` (the repository the action touches; a path is resolved to its repository name);
without it, the repository recorded for stage S (`stage.json`). So the DAY-03 case — stage X asks about a release
of repository R, the owner allowed it in stage Y for R — is covered once X names `--repo R`.

**"Covered".** `ask add` checks the applicable permissions before it writes:
- a confident match — the question's `--class` shares a keyword with a permission's `class` — refuses the question
  (exit 3) with `covered by A-… (<source>): <words>`; the agent acts under the permission instead of asking;
- a weak match — a permission keyword occurs in the question's text, or a `--class` keyword occurs in a
  permission's title or words — adds the question and prints `may be covered by A-…` on stderr;
- `--override "why"` adds the question despite a confident match and records `- override: A-… — why` in it.

Keywords compare case-insensitively (a confident match needs equal keywords, a weak one a substring); a refusal
is never inferred from free text alone, so it needs the asker to name the class.

**Revocation and expiry.** `ask revoke A-… --reason "…"` sets `revoked: <reason> (<stamp>)`; `--until` on `ask allow`
sets an end. No expiry by default (D-09-004). `ask allow --list [--repo R | --stage S] [--all]` shows the
permissions in force (`--all`: revoked and expired too). The `hub start` / `hub takeover` digest lists the ones that
apply to the stage's repository and stage, from every stage's register, or says in one line that there are none.

**Not covered by design.** Money and anything that leaves the company are not given a default class; a permission
for them exists only when the owner's words say so. The plugin ships no list of classes: `skills/setup` proposes
them after reading the project and the person (Q-09-004).
