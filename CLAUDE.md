# agent-hub plugin: pointers for agents (Codex reads this file too)

- Full test suite: `bash tests/run_all.sh "$(mktemp -d)"`, about 6 minutes: run it with Bash `timeout: 600000` or
  `run_in_background`. One script: `bash tests/t_<name>.sh`. Tests use throw-away homes; read exit codes from files, not pipes.
- Mod tests (`hooks/agent-top.test.tsx`): `claude plugin test .` from the repository root.
- Manifest: `claude plugin validate .claude-plugin/plugin.json --strict` (the root path validates only `marketplace.json` on some builds).
- The hub skill is `skills/hub/SKILL.md`; brief, handoff and queue templates are in `templates/`; tools in `bin/`, hooks in
  `hooks/`, documentation in `docs/`, user-visible changes in `CHANGELOG.md`.
- Code, docs and comments in English; commit messages and PRs follow the owner's repositories (Russian).
