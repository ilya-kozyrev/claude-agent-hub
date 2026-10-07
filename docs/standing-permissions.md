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
- repo: delamain     (the short name, for people; "*" with scope all)
- repo-id: github.com/ilya-kozyrev/delamain   (what matching uses; see below)
- class: merge, release      (comma-separated keywords; the title is the class in free text)
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

**Repository identity.** `repo-id` is the repository's `origin` URL normalized to `host[:port]/owner/repo` (scheme,
user, `.git` and the `git@host:` form dropped; an explicit port, the brackets of an IPv6 host and the leading `/` of an
absolute `git@host:/path` kept — distinct spellings stay distinct when unsure), else the absolute path of its main
clone; a linked worktree resolves through git's common directory to its main clone. Two checkouts named `shop` of different owners are two
repositories. `--repo` takes a path, a remote URL, or a short name that exactly one known repository has (the
repositories of every stage's `stage.json` and of every permission); an ambiguous or unknown short name is refused
with the candidates.

**Applicability.** A permission applies to a question asked in stage S about repository R when it is in force
(`allowed`, well-formed, `until` not passed) and its scope is `all`, or `repo` with `repo-id` = R's id, or `stage`
with the recording stage = S. R is each `--repo` of the question (the repositories the action touches); without
one, the repository recorded for stage S (`stage.json`), else the working directory's. So the DAY-03 case — stage X
asks about a release of repository R, the owner allowed it in stage Y for R — is covered once X names `--repo R`.

**"Covered".** `ask add` checks before it writes. Without `--class` nothing is covered. With it, the question is
covered only when, on **every** repository it touches, **every** requirement is named by a permission in force:
- each `--class` keyword is a requirement, as written: a permission covers it only with the same keyword
  (`rbac-read` does not cover `rbac-write`, nor `migration-schema` `migration-data`);
- on top of that, a sensitive class — money, migration, permissions/RBAC by default (`AGENT_HUB_SENSITIVE_CLASSES` in the hub home's
  `config.json`, `{"class": ["stem", …]}`) — is a requirement whenever one of its stems occurs in the question's text
  or class, and only a permission whose `class` names it (the class itself or a keyword starting with a stem) covers
  that class; never a weak match or another keyword.

A covered question is refused (exit 3) with `covered by A-… (<source>)` and the owner's words in full (a limit often comes last), and the agent acts
under the permission only where those words cover the case — its environment and scope ("deploy to staging" is not a
production deploy); otherwise it passes `--override "why"`, which adds the question and records `- override: A-… —
why`. A partly covered question is added with `not covered: <class> on <repository>` on stderr. A weak match — a
permission keyword in the question's text, or a `--class` keyword in a permission's title or words — only prints
`may be covered by A-…`.

**Invalid entries.** A hand-edited entry is checked on every read: no owner's words, an unknown scope, scope `repo`
without a `repo-id`, an `until` that is not exactly `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`, or an unknown status make
it invalid. An invalid entry covers nothing; `ask add` names it on stderr, `ask allow --list` shows it as `INVALID
(<why>)`, the digest names it — an entry that does not say where it applies (no `repo-id`, an unknown scope) under
every filter.

**Revocation and expiry.** `ask revoke A-… --reason "…"` sets `revoked: <reason> (<stamp>)`; `--until` on `ask allow`
sets an end. No expiry by default (D-09-004). `ask allow --list [--repo R | --stage S] [--all]` shows the
permissions in force and the invalid ones (`--all`: revoked and expired too). The `hub start` / `hub takeover`
digest lists the ones that apply to the stage's repository and stage, from every stage's register, after the
handoff's § 0 (which keeps its budget) and within about 520 bytes — what does not fit is `K more: ask allow --list
--stage S` — or says in one line that there are none.

**Not covered by design.** Money and anything that leaves the company are not given a default class; a permission
for them exists only when the owner's words say so. The plugin ships no list of classes: `skills/setup` proposes
them after reading the project and the person (Q-09-004).
