---
name: setup
description: Set up agent-hub for a repository — ask which shared resources the project has (protected branches, environments, deploys, migrations, anything else), which commands touch each, write <repo>/.agent-hub/lock-rules.json and config.json, and prove the lock hook with positive and negative checks. Use right after installing the plugin, when a repository has no .agent-hub/ yet, or when the project gains a new shared resource.
argument-hint: "[repository path] [--defaults]"
---

# agent-hub setup for a repository

The lock hook refuses a command that touches a shared resource while another session holds that resource's lock.
It knows one resource by itself — `main-merge`: merges into, and pushes to, the protected branches. Everything else
(a production deploy, a staging environment, a migration chain, a shared test database) exists only if this setup
names it. A project with no deployment at all ends with `main-merge` only, and that is a complete setup.

Work in the repository's main checkout (or the path the user gave). Tools: `lock rules`, `lock rules init`,
`lock rules add`, `lock rules check`, `hub home` (all on PATH with the plugin; `--help` on each).

## 1. Look before you ask

Gather what the repository already says, so every question comes with a recommended answer:
- `lock rules` — what applies here now (an existing `.agent-hub/lock-rules.json` is extended, never replaced);
- `hub home` — where the hub keeps its files for this repository now and why (the legacy `~/.claude/agent-hub` is
  reported there, with the grant lines for a session started elsewhere);
- the default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, else `main`/`master`) and other long-lived
  branches (`release/*`, `production`);
- how the project deploys and migrates: CI files (`.github/workflows/`, `.gitlab-ci.yml`), `Makefile` targets, `scripts/`,
  Helm charts / Terraform / `fly.toml` / `Procfile`, migration directories (`migrations/`, `alembic/`, `prisma/`).
  Note the exact commands (`make deploy-prod`, `gh workflow run deploy.yml`, `helm upgrade … -n staging`,
  `alembic upgrade head`, `glab ci play deploy:prod`).

## 2. Grill the user, one round

Ask in one message, every question numbered, each with your recommended answer and the evidence behind it; the user
replies "ok" or corrects by number. Use the `grilling` skill if it is installed; the format is the same either way.
1. Protected branches — merges and pushes to them need `main-merge`. *Recommended:* the default branch (+ any release
   branch you found).
2. Environments other agents or people share (staging, preview, production) — one resource per environment that two
   sessions must not change at once. *Recommended:* from what you found, or "none".
3. For each resource: the commands that touch it, as you would type them. You turn each into a Python regex matched
   against the command's words joined by single spaces (anchor with `^` or `\b`; allow a path prefix like
   `^(?:\S*/)?glab …` when the tool may be called by full path).
4. Migrations — a resource for the migration chain? *Recommended:* yes if two branches can add migrations at once, as
   an informational resource (`migration-head`, no commands: the holder records the expected head with `--value`).
5. Anything else shared and single-user: a test database, a rate-limited API key, a release window. *Recommended:* none
   unless you saw one.
6. Should the hub hold `main-merge` by default (`AGENT_HUB_TAKE_MAIN_MERGE=true` in `config.json`)? *Recommended:* yes
   when more than one agent may merge; no for a solo repository.
7. Where should the hub keep its files? One folder for all your projects, `~/agent-hub` (recommended: hubs of different
   projects can talk and share locks) / inside this project (nothing outside the repository; projects do not see each
   other, and `git clean -fdx` deletes that folder). *Recommended:* the shared folder, unless the user wants nothing
   outside the repository; say what `hub home` showed.
8. Autopilot — should a stage hub hand its shift to a background successor by itself when its context grows large, so
   the stage runs while you are away (`AGENT_HUB_AUTO_HANDOFF=on`, in the hub home's `config.json`, not the
   repository's)? Check first: `claude auth status` shows `"loggedIn": true`, and `claude` has been run once in this
   directory with its trust prompt accepted. *Recommended:* on if the user wants to leave stages running and both
   checks pass; off otherwise (say which check failed and the command that fixes it).

`--defaults` (or a headless run with nobody to answer): take the recommended answers, say so in the report, and list
what the user should confirm. Autopilot stays off in that case: nobody asked for background sessions, and the user's
settings are not edited (question 7): list the edit for the user to confirm.

## 3. Write

```bash
lock rules init [--protected main release]             # .agent-hub/lock-rules.json + config.json (repo name)
lock rules add deploy-window --about "a production rollout is in progress" \
    --match '^make deploy-prod\b' --action "production deploy"
lock rules add staging --about "the shared staging environment" \
    --match '^helm upgrade\b.* -n staging\b' --action "staging rollout"
lock rules add migration-head --about "expected head of the migration chain"    # informational
```
Resource names are lowercase letters, digits and hyphens; pick names the team will say aloud. `add` refuses a bad
regex and leaves the file as it was. For question 6, add `"AGENT_HUB_TAKE_MAIN_MERGE": "true"` to
`.agent-hub/config.json` by hand. For question 7:
- *inside this project:* add `"AGENT_HUB_HOME": "project"` to `.agent-hub/config.json` (the home becomes
  `<main checkout>/.agent-hub/local/`, kept out of git by the tools; a session in the repository needs no grant);
- *one shared folder:* nothing to write in the repository, `~/agent-hub` is the default. A session started outside it
  needs the folder granted, so OFFER to add it to the user settings: run `hub home`, show the exact edit — the path
  `hub home` prints added to `permissions.additionalDirectories` in `~/.claude/settings.json`, other keys and entries
  kept — and ask first. Never edit settings silently. With `--defaults` or headless, do not edit them: list the edit.
- if `hub home` showed the legacy `~/.claude/agent-hub`, say so and mention `hub home migrate` (a dry run first, then
  `--apply`).

For question 8, add `"AGENT_HUB_AUTO_HANDOFF": "on"` to the hub home's `config.json` (the hub home is where `hub home`
points; create the file as `{}` first, keep its other keys) — a repository's `config.json` cannot turn it on.

## 4. Prove it

For every resource, one command that must be guarded and one look-alike that must not:
```bash
lock rules check "git push origin main" --expect main-merge
lock rules check "make deploy-prod" --expect deploy-window
lock rules check "make deploy-preview" --expect-none
lock rules check "git push origin feature/x" --expect-none
```
`check` runs the plugin's real hook against a scratch board where every resource is held by someone else; it never
touches the real board. Every line must exit 0. A failed positive means the regex misses the real command; a failed
negative means it catches too much — fix the rule (`lock rules add` the corrected `--match`, then remove the wrong one
from the file by hand) and re-run all checks.

## 5. Report

A short table: resource — what it guards — the checks that passed — and the answers you took by default that the
user should confirm. Then suggest committing `.agent-hub/` (it is the team's shared convention); commit only if the
user asked you to. Other files there are optional: `brief-footer.md`, `hub-rules.md`, `HUB-NOTES.md`,
`handoff-facts.sh`, `takeover.sh` — see the README. Locks themselves live on the board, not in the repository:
`lock take <resource> --until … --why …` when work starts.
