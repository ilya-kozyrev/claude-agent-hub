# Claude and Codex engines

The owner approved full support for both engines on 2026-10-02, including unattended
full-access sessions. Keep the existing file protocol and Claude behavior. Add an
explicit engine to agent metadata; old metadata without one means Claude.

Codex workers use detached `codex exec --json`, record the real ID from
`thread.started`, and resume that ID. A separate launch token protects process
identity before the ID exists. Raw logs stay on disk; readers normalize events.
Model aliases and effort are validated for the selected engine. Never report
cumulative Codex usage as the current context size or invent a dollar cost.

`bypassPermissions` maps to bypassing both Codex approvals and sandboxing.
Restricted Codex sessions use an explicit sandbox and `approval_policy=never`:
denied tools fail rather than waiting for an absent human. Resume reapplies the
same policy. Hook trust is separate; detached runs explicitly load the bundled
guards. Their trust behavior is configurable and documented, including its
invocation-wide effect on other enabled hooks. Full access must not disable guards.

Skills and plugin packaging support both hosts. Native worker definitions are
host-specific. Codex autopilot starts another detached Codex coordinator and
retains chain limits, journal takeover and lock transfer. Desktop-specific remote
control and UI nudge behavior must be labeled by host rather than emulated.

Verification includes fake-CLI lifecycle/error tests, real installed Codex
launch/resume/permissions/hook-denial controls, the existing Claude suite, and a
separate read-only review. Deliver an open PR with green checks; merging remains
the owner's decision.
