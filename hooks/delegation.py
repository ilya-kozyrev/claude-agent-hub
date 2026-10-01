#!/usr/bin/env python3
"""Delegation dial (levels 0-5) and subagent rules.

Hook subcommands (hook JSON on stdin):
  session-start  SessionStart: inject the policy text of the session's level           (only when the dial is on)
  prompt         UserPromptSubmit: re-inject it when the level changed since the last injection (dial on)
  pre-tool       PreToolUse on Agent|Task|Workflow: AGENT_HUB_DELEGATION_RULES (dial on; may test the level),
                 then AGENT_HUB_EFFORT_RULES (always, Agent/Task only) — the first deny wins

CLI subcommands (the /delegation skill, through bin/delegation):
  show                print the level, where it comes from, and its policy
  set N [--global]    this session's override (needs $CLAUDE_CODE_SESSION_ID), or the default for all sessions
  clear               drop this session's override
  try [TYPE [MODEL]] [--tool T] [--type NAME] [--model M]   evaluate the rules for a hypothetical Agent call

Settings (hub home config.json or environment; see README "Agent discipline"):
  AGENT_HUB_DELEGATION          on | off (default off)
  AGENT_HUB_DELEGATION_DEFAULT  level when nothing else is set (default 3)
  AGENT_HUB_DELEGATION_LEVEL    environment only: the level for every session started with it
  AGENT_HUB_DELEGATION_LEVELS   {"0": {"name": "OFF", "policy": "…"}, …} — replaces the built-in texts per level
  AGENT_HUB_DELEGATION_COMMON   text appended to every level's policy
  AGENT_HUB_DELEGATION_RULES    rule list (bin/subagent_rules.py); default: level 0 denies Agent, Task, Workflow
  AGENT_HUB_EFFORT_RULES        rule list (or shorthand) for every subagent launch, also applied by `agent spawn`;
                                the user's and the repository's sets both apply, any deny wins (default none)
  AGENT_HUB_STATE_DIR           state directory (default <hub home>/.state); levels live in <state>/delegation/

Resolution of the level: this session's override > $AGENT_HUB_DELEGATION_LEVEL > the global level (set --global)
> AGENT_HUB_DELEGATION_DEFAULT > 3. Fail-open: an error of its own never blocks a tool call.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "bin"))
try:
    import hubcore as hc  # noqa: E402
    import subagent_rules as sr  # noqa: E402
except Exception:  # noqa: BLE001 — fail-open: as a hook, never block a session over an import error
    if len(sys.argv) > 1 and sys.argv[1] in ("session-start", "prompt", "pre-tool"):
        sys.exit(0)
    raise

PRUNE_AFTER_DAYS = 30
LEVELS = range(0, 6)
BUILTIN_LEVELS = {
    0: ("OFF", "Do everything yourself. No subagents (the Agent and Workflow tools are blocked by a hook) and no "
               "background sessions for your own work; parallelise with background Bash if needed."),
    1: ("MINIMAL", "Work yourself by default. Delegate only when the user asks for it explicitly, or when a piece "
                   "must run isolated (for example an executor in its own worktree). Searches, file reading and "
                   "probes: yourself."),
    2: ("ECONOMICAL", "Delegate only large independent pieces: an executor for a specified change, a review by a "
                      "model other than the author, reading another repository. Anything under about ten tool "
                      "calls you do yourself; do not start a subagent for a single search."),
    3: ("BALANCED", "Delegate mechanical work with a checkable answer (searches, log reading, test runs) to a "
                    "small fast model and bounded work from a finished design to a mid-size one; keep framing, "
                    "decisions and the final synthesis. Delegate when a third search pass comes up or another "
                    "repository needs reading whole."),
    4: ("DELEGATION-FIRST", "Read only what you need to decide. Exploration beyond about three files and every "
                            "code change go to a subagent; independent pieces run in parallel and in the "
                            "background. You keep decisions, communication with the user, merges and the "
                            "synthesis."),
    5: ("ORCHESTRATOR", "Hands-off. You read subagent reports, decide, talk to the user and run git operations; "
                        "everything else, including a single search or a one-line edit, goes to a subagent with a "
                        "full brief. Keep your own context small: a fresh agent per stage over resuming a long one."),
}
BUILTIN_COMMON = ("The level sets how much you delegate, not which model or effort; the subagent rules still "
                  "apply. Name the level when you report what you delegated.")
DEFAULT_DELEGATION_RULES = [
    {"when": {"level": "0", "tool": ["Agent", "Task", "Workflow"]}, "decision": "deny",
     "reason": "Delegation level is 0 ({source}): do this yourself. The user can raise it with /delegation."},
]


def enabled() -> bool:
    return hc.truthy(hc.setting("AGENT_HUB_DELEGATION"))


def state_root() -> Path:
    raw = hc.setting("AGENT_HUB_STATE_DIR")
    return (Path(raw).expanduser() if raw else hc.root() / ".state") / "delegation"


def parse_level(raw) -> int | None:
    try:
        n = int(str(raw).strip())
    except (ValueError, TypeError):
        return None
    return n if n in LEVELS else None


def read_level(path: Path) -> int | None:
    try:
        return parse_level(path.read_text())
    except OSError:
        return None


def resolve(session_id: str | None) -> tuple:
    root = state_root()
    if session_id:
        n = read_level(root / "sessions" / session_id)
        if n is not None:
            return n, "session override"
    n = parse_level(os.environ.get("AGENT_HUB_DELEGATION_LEVEL", ""))
    if n is not None:
        return n, "env AGENT_HUB_DELEGATION_LEVEL"
    n = read_level(root / "level")
    if n is not None:
        return n, "global (set --global)"
    n = parse_level(hc.setting("AGENT_HUB_DELEGATION_DEFAULT") or "")
    if n is not None:
        return n, "AGENT_HUB_DELEGATION_DEFAULT"
    return 3, "built-in default"


def policy(level: int) -> str:
    name, text = BUILTIN_LEVELS[level]
    custom = hc.setting_json("AGENT_HUB_DELEGATION_LEVELS", {}) or {}
    entry = custom.get(str(level)) if isinstance(custom, dict) else None
    if isinstance(entry, dict):
        name, text = str(entry.get("name") or name), str(entry.get("policy") or text)
    elif isinstance(entry, str):
        text = entry
    common = hc.setting("AGENT_HUB_DELEGATION_COMMON")
    common = BUILTIN_COMMON if common is None else common
    return f"Delegation level {level}/5 ({name}). {text} {common}".strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def prune() -> None:
    cutoff = time.time() - PRUNE_AFTER_DAYS * 86400
    for d in (state_root() / "sessions", state_root() / "injected"):
        if not d.is_dir():
            continue
        for f in d.iterdir():
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


def emit(event: str, **fields) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}}, ensure_ascii=False))


def decide(tool: str, tool_input: dict, cwd, session_id) -> str | None:
    """The deny reason for one Agent/Task/Workflow call, or None."""
    level, source = resolve(session_id) if enabled() else (None, "dial off")
    call = sr.agent_call(tool, tool_input, cwd, level)
    call["source"] = source
    if level is not None:
        rules = hc.setting_json("AGENT_HUB_DELEGATION_RULES", None)
        label = "AGENT_HUB_DELEGATION_RULES"
        res = sr.evaluate(DEFAULT_DELEGATION_RULES if rules is None else rules, call, label)
        if res and res[0] == "deny":
            return sr.deny_reason(res, label)
    if tool in ("Agent", "Task"):
        return sr.check_effort(call, cwd)
    return None


def hook_input() -> dict:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def main(argv: list) -> int:
    cmd = argv[1] if len(argv) > 1 else "show"

    if cmd in ("session-start", "prompt"):
        try:
            data = hook_input()
            hc.use_cwd(data.get("cwd"))  # the hub home (its .state, its config.json) of the session's directory
            if not enabled():
                return 0
            sid = data.get("session_id")
            level, _ = resolve(sid)
            marker = state_root() / "injected" / sid if sid else None
            if cmd == "session-start":
                if marker:
                    write(marker, str(level))
                prune()
                emit("SessionStart", additionalContext=policy(level))
            elif (read_level(marker) if marker else None) != level:
                if marker:
                    write(marker, str(level))
                emit("UserPromptSubmit", additionalContext=f"Delegation level changed to {level}. " + policy(level))
        except Exception:  # noqa: BLE001 — fail-open
            pass
        return 0

    if cmd == "pre-tool":
        try:
            data = hook_input()
            hc.use_cwd(data.get("cwd"))
            tool = data.get("tool_name")
            if tool in ("Agent", "Task", "Workflow"):
                reason = decide(tool, data.get("tool_input") or {}, data.get("cwd"), data.get("session_id"))
                if reason:
                    emit("PreToolUse", permissionDecision="deny", permissionDecisionReason=reason)
        except Exception:  # noqa: BLE001 — fail-open: a broken hook must not block every session
            pass
        return 0

    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    off_note = "" if enabled() else ("\n(the delegation dial is off: no policy is injected and level rules do not "
                                     "apply; set AGENT_HUB_DELEGATION to on in the hub home's config.json)")

    if cmd == "show":
        level, source = resolve(sid)
        print(f"level={level} source={source}\n{policy(level)}{off_note}")
        return 0

    if cmd == "set":
        n = parse_level(argv[2]) if len(argv) > 2 else None
        if n is None:
            print("usage: delegation set N [--global]   (N = 0..5)", file=sys.stderr)
            return 2
        if "--global" in argv[3:]:
            write(state_root() / "level", f"{n}\n")
            scope = "global default"
        else:
            if not sid:
                print("CLAUDE_CODE_SESSION_ID is not set; use --global", file=sys.stderr)
                return 2
            write(state_root() / "sessions" / sid, f"{n}\n")
            scope = f"session {sid}"
        level, source = resolve(sid)
        if sid:
            write(state_root() / "injected" / sid, str(level))
        print(f"set {n} for {scope}; effective level={level} ({source})\n{policy(level)}{off_note}")
        return 0

    if cmd == "clear":
        if sid:
            try:
                (state_root() / "sessions" / sid).unlink()
            except FileNotFoundError:
                pass
        level, source = resolve(sid)
        if sid:
            write(state_root() / "injected" / sid, str(level))
        print(f"session override cleared; effective level={level} ({source})\n{policy(level)}{off_note}")
        return 0

    if cmd == "try":
        import argparse

        p = argparse.ArgumentParser(prog="delegation try")
        p.add_argument("--tool", default="Agent")
        p.add_argument("--type", default="", dest="subagent_type")
        p.add_argument("--model", default="")
        p.add_argument("--cwd", default=os.getcwd())
        p.add_argument("positional", nargs="*", metavar="TYPE [MODEL]")
        a = p.parse_args(argv[2:])
        if a.positional:
            a.subagent_type = a.positional[0]
            if len(a.positional) > 1:
                a.model = a.positional[1]
        ti = {k: v for k, v in (("subagent_type", a.subagent_type), ("model", a.model)) if v}
        level = resolve(sid)[0] if enabled() else None
        print(json.dumps(sr.agent_call(a.tool, ti, a.cwd, level), ensure_ascii=False))
        reason = decide(a.tool, ti, a.cwd, sid)
        print(f"deny: {reason}" if reason else "allow")
        return 1 if reason else 0

    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
