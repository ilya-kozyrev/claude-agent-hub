"""Codex watchdog boundary: queue only a confirmed, idle app hub's own thread.

`hub start`/`takeover` record host: codex-app only from the current app session.
Terminal and legacy/unknown hosts remain notify-only, regardless of rollout source.

The 0.160.0 scratch control proved that queue starts an idle app-server turn.
A notLoaded reply is local to one server, not a global writer lock. Never use
exec resume here. A final task_complete.error can carry codex_error_info, but
has no retry-eligibility field (ErrorNotification.willRetry is not persisted).
R4 stays Claude-only; bare task_complete and turn_aborted do not establish an API failure.
"""
from __future__ import annotations

from datetime import datetime, timezone
import shlex
import subprocess
from uuid import UUID

import codex_rollouts
import codex_sessions
import engines
import hubcore as hc


def _session(rec: dict) -> str | None:
    """Use the recorded thread UUID, never a name, --last, or another thread."""
    sid = rec.get("cli_session_id") or rec.get("session")
    try:
        return sid if isinstance(sid, str) and str(UUID(sid)) == sid.lower() else None
    except ValueError:
        return None


def state(stage: str, rec: dict, now: datetime) -> dict:
    """Unknown liveness or host means notify. The core handles detached agents."""
    result = {"busy": None, "last_activity": None, "dead_turn": None,
              "transport": "notify", "why": "no recorded Codex thread UUID"}
    sid = _session(rec)
    if sid is None:
        return result
    rollout = codex_rollouts.INDEX.session(sid)
    if rollout:
        result["last_activity"] = datetime.fromtimestamp(rollout[2], timezone.utc)
    status = codex_sessions.runtime_status(sid, rec.get("cwd"))
    status = status if isinstance(status, str) else None
    result["busy"] = {"active": True, "idle": False}.get(status)
    if status != "idle":
        result["why"] = ("Codex thread is active" if status == "active" else
                         "notLoaded does not exclude another rollout writer; resume disabled" if status == "notLoaded" else
                         "Codex runtime status is unknown or in error")
    elif rec.get("kind") == "desktop" or str(rec.get("session", "")).startswith("local_"):
        result["why"] = "Desktop hubs are notify-only"
    elif codex_sessions.detached(stage, rec):
        result["why"] = "detached hubs use the core's agent-send path"
    elif rec.get("host") != "codex-app":
        # Rollout source is creation provenance, not the current host: a TUI can
        # resume a vscode thread. Legacy records must not guess app vs terminal.
        result["why"] = "terminal or unconfirmed Codex host; require host=codex-app"
    elif rollout is None:
        result["why"] = "no rollout activity evidence for the recorded thread"
    else:
        result["transport"] = "codex-queue"
        result["why"] = "confirmed app hub is idle; queue starts a turn on Codex 0.160.0"
    return result


def wake(stage: str, rec: dict, text: str, dry_run: bool) -> dict:
    """Recheck liveness and host immediately before a same-thread queue; no fallback."""
    current = state(stage, rec, datetime.now(timezone.utc))
    if current["busy"] is not False or current["transport"] != "codex-queue":
        return {"ok": False, "how": "notify", "detail": current["why"]}
    sid = _session(rec)
    try:
        argv = [engines.codex_bin(rec.get("cwd")), "queue", "--thread", sid, "--message", text]
        how = shlex.join([*argv[:3], sid[:8], *argv[4:]])
        if dry_run:
            return {"ok": True, "how": how, "detail": "dry run; no message queued"}
        proc = subprocess.run(argv, cwd=rec.get("cwd") or None, env=hc.child_env(),
                              capture_output=True, text=True, errors="replace", timeout=20)
    except subprocess.TimeoutExpired:
        return {"ok": False, "how": how, "detail": "queue outcome unknown: TimeoutExpired"}
    except (hc.Failure, hc.UsageError, OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "how": locals().get("how", "codex queue"),
                "detail": f"queue failed: {type(exc).__name__}"}
    output = (proc.stderr if proc.returncode else proc.stdout).strip().splitlines()
    detail = output[0][:500] if output else f"queue exit {proc.returncode}"
    # Keep the local action summary's IDs abbreviated too.
    detail = detail.replace(sid, sid[:8])
    return {"ok": proc.returncode == 0, "how": how, "detail": detail}
