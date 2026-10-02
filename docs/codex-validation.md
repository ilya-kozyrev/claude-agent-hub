# Codex port validation

Runtime controls were run on macOS with Codex CLI 0.155.1 on 2026-10-02.
They used scratch directories and an explicitly available authenticated model.
No production repository, remote push, deployment or global configuration was changed.

| Control | Evidence |
| --- | --- |
| Full-access spawn | Native rollout records `danger-full-access` and `approval_policy=never`; shell creates the control file outside the checkout. |
| Full-access resume | Same assigned thread ID, second run; rollout retains both settings and creates a second control file. |
| Guard under full access | Native tool outputs contain `Command blocked by PreToolUse hook` from `board_locks` on spawn and resume, before Git executes. |
| Read-only spawn and resume | Both native turn contexts retain `read-only` and `never`; both writes fail with `operation not permitted`, and neither target exists. |
| Plugin installation | Actual installed CLI adds the local marketplace and installs its skills, hooks and helpers in an isolated plugin home. |
| Provider startup error | The initially configured model was rejected by the authenticated CLI. Status reports the failure and journals EXIT; no success is fabricated. |

The runtime checker requires native rollout evidence, not an agent's claim about a
command or a fake-CLI argument assertion. To repeat these opt-in controls:

```sh
python3 tests/codex_live.py --model <AVAILABLE_CODEX_MODEL>
```

This consumes model usage and requires CLI login. It prints the scratch directory;
`--verify <directory>` rechecks it without another model call. It is deliberately
excluded from CI. The regular suite runs lifecycle, policy, monitoring, hook and
installation controls using isolated fixtures, including the existing Claude tests.

Native desktop sessions without a known per-thread PID use labeled activity
inference for unfinished work. Supported sandbox fields are preserved; an unknown
restricted policy is refused rather than flattened into full access. Claude's phone
Remote Control and Desktop scheduled nudge remain platform-specific.
