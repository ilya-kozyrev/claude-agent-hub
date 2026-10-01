#!/usr/bin/env python3
"""Context budget: nudge a session toward a handoff when its context grows large, and stop it from starting new
work past a hard threshold.

Size of the context = usage of the last real assistant turn of the transcript:
    input_tokens + cache_read_input_tokens + cache_creation_input_tokens
If a compact_boundary record comes after that turn, its compactMetadata.postTokens wins.

Which transcript: the main thread reads `transcript_path` and skips sidechain records; inside a subagent (the hook
input carries `agent_id`) the subagent's own transcript (`agent_transcript_path`, else
<dir(transcript_path)>/<session_id>/subagents/agent-<agent_id>.jsonl) — if it cannot be found the hook stays silent.

Events:
  UserPromptSubmit, PostToolUse  additionalContext once on crossing AGENT_HUB_CONTEXT_WARN and again every
                                 AGENT_HUB_CONTEXT_WARN_STEP tokens above it
  PreToolUse                     deny the tools in AGENT_HUB_CONTEXT_BLOCK_TOOLS at AGENT_HUB_CONTEXT_BLOCK and above,
                                 unless the tool input matches AGENT_HUB_CONTEXT_ESCAPE (a HANDOFF-*.md path or the
                                 marker `handoff-ok`): handing the work over must stay possible

Settings (hub home config.json or environment; README "Agent discipline"):
  AGENT_HUB_CONTEXT_BUDGET       on | off (default on)
  AGENT_HUB_CONTEXT_WARN         300000      AGENT_HUB_CONTEXT_WARN_STEP  50000
  AGENT_HUB_CONTEXT_BLOCK        500000      AGENT_HUB_CONTEXT_BLOCK_TOOLS ["Agent", "Task", "SendMessage"]
  AGENT_HUB_CONTEXT_ESCAPE       regex, default HANDOFF-<name>.md or handoff-ok
  AGENT_HUB_CONTEXT_TODO         the "what to do" sentence of both messages
  AGENT_HUB_STATE_DIR            state directory (default <hub home>/.state); this hook uses <state>/context-budget/
Fail-open: any error of its own -> exit 0, no output.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

CHUNK = 1 << 20
MAX_SCAN = 64 << 20  # give up (silently) after reading this much from the tail
PRUNE_AFTER_DAYS = 14
DEFAULTS = {"warn": 300_000, "step": 50_000, "block": 500_000}
DEFAULT_TOOLS = ["Agent", "Task", "SendMessage"]
DEFAULT_ESCAPE = r"HANDOFF-[^\s/\\'\"`]*\.md|handoff-ok"
DEFAULT_TODO = ("What to do: write a handoff with the agent-hub:handoff skill (the plugin's "
                "templates/HANDOFF-template.md, at most 12 KB; the chronology goes to the journal) and continue in a "
                "new session from it.")


def hubcore():
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, os.path.join(root, "bin"))
    import hubcore as hc  # noqa: E402

    return hc


def fmt(n: int) -> str:
    return f"{n // 1000}k"


def classify(line: bytes, skip_sidechain: bool):
    """('usage', n) | ('compact', n) | None for one JSONL line."""
    if b'"assistant"' not in line and b"compact_boundary" not in line:
        return None
    try:
        o = json.loads(line)
    except ValueError:
        return None
    if not isinstance(o, dict):
        return None
    if o.get("type") == "system" and o.get("subtype") == "compact_boundary":
        post = (o.get("compactMetadata") or {}).get("postTokens")
        return ("compact", int(post)) if isinstance(post, (int, float)) else ("compact", 0)
    if o.get("type") != "assistant":
        return None
    if skip_sidechain and o.get("isSidechain") is True:
        return None
    msg = o.get("message") or {}
    if msg.get("model") == "<synthetic>":
        return None
    u = msg.get("usage") or {}
    n = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return ("usage", n) if n > 0 else None


def context_tokens(path: Path, skip_sidechain: bool):
    """Scan the JSONL backwards; the first qualifying record from the end decides."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        tail = b""
        scanned = 0
        while pos > 0 and scanned < MAX_SCAN:
            step = min(CHUNK, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + tail
            scanned += step
            lines = buf.split(b"\n")
            tail = lines[0] if pos > 0 else b""
            body = lines[1:] if pos > 0 else lines
            for line in reversed(body):
                if not line.strip():
                    continue
                r = classify(line, skip_sidechain)
                if r:
                    return r[1]
    return None


def resolve_transcript(data: dict):
    sid = str(data.get("session_id") or "unknown")
    agent_id = data.get("agent_id")
    tp = data.get("transcript_path")
    if agent_id:
        key = f"{sid}__{agent_id}"
        atp = data.get("agent_transcript_path")
        if atp:
            return Path(atp), False, key
        if tp:
            cand = Path(tp).parent / sid / "subagents" / f"agent-{agent_id}.jsonl"
            return (cand if cand.is_file() else None), False, key
        return None, False, key
    return (Path(tp) if tp else None), True, sid


def mentions(obj, rx) -> bool:
    if isinstance(obj, str):
        return bool(rx.search(obj))
    if isinstance(obj, dict):
        return any(mentions(v, rx) for v in obj.values())
    if isinstance(obj, list):
        return any(mentions(v, rx) for v in obj)
    return False


def load_state(state_dir: Path, key: str) -> dict:
    try:
        return json.loads((state_dir / f"{key}.json").read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_state(state_dir: Path, key: str, state: dict) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / f"{key}.json").write_text(json.dumps(state))
        if time.time() % 50 < 1:  # cheap occasional prune
            cutoff = time.time() - PRUNE_AFTER_DAYS * 86400
            for p in state_dir.glob("*.json"):
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def emit(event: str, **fields) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}}, ensure_ascii=False))


def main() -> None:
    data = json.loads(sys.stdin.read() or "{}")
    if not isinstance(data, dict):
        return
    event = data.get("hook_event_name") or ""
    if event not in ("PreToolUse", "UserPromptSubmit", "PostToolUse"):
        return
    hc = hubcore()
    if (hc.setting("AGENT_HUB_CONTEXT_BUDGET") or "on").strip().lower() in ("off", "0", "false", "no"):
        return
    tools = hc.setting_json("AGENT_HUB_CONTEXT_BLOCK_TOOLS", DEFAULT_TOOLS)
    if isinstance(tools, str):  # "Agent,SendMessage"
        tools = [t.strip() for t in tools.split(",") if t.strip()]
    if event == "PreToolUse" and data.get("tool_name") not in (tools or []):
        return
    warn = hc.int_setting("AGENT_HUB_CONTEXT_WARN", DEFAULTS["warn"])
    block = hc.int_setting("AGENT_HUB_CONTEXT_BLOCK", DEFAULTS["block"])
    step = hc.int_setting("AGENT_HUB_CONTEXT_WARN_STEP", DEFAULTS["step"])

    path, skip_side, key = resolve_transcript(data)
    if path is None or not path.is_file():
        return
    tokens = context_tokens(path, skip_side)
    if tokens is None:
        return
    todo = hc.setting("AGENT_HUB_CONTEXT_TODO") or DEFAULT_TODO
    escape_src = hc.setting("AGENT_HUB_CONTEXT_ESCAPE") or DEFAULT_ESCAPE
    try:
        escape = re.compile(escape_src)
    except re.error:
        escape = re.compile(DEFAULT_ESCAPE)
    gated = "/".join(tools or [])

    if event == "PreToolUse":
        if tokens < block or mentions(data.get("tool_input"), escape):
            return
        emit("PreToolUse", permissionDecision="deny", permissionDecisionReason=(
            f"Session context is {fmt(tokens)} tokens, at or above the {fmt(block)} limit: {gated} are closed, every "
            f"turn here is expensive. {todo} Only handing the work over passes: a tool input that names a "
            f"HANDOFF-*.md file or carries the marker handoff-ok (pattern: {escape.pattern})."))
        return

    raw_state = hc.setting("AGENT_HUB_STATE_DIR")
    state_dir = (Path(raw_state).expanduser() if raw_state else hc.root() / ".state") / "context-budget"
    state = load_state(state_dir, key)
    if tokens < warn:
        if state.get("bucket", -1) >= 0:  # dropped below (compact / new chain): re-arm
            save_state(state_dir, key, {"bucket": -1, "tokens": tokens})
        return
    bucket = (tokens - warn) // step
    if bucket <= state.get("bucket", -1):
        return
    save_state(state_dir, key, {"bucket": bucket, "tokens": tokens})
    extra = (f" The {fmt(block)} limit is already passed: {gated} pass only with a HANDOFF-*.md path or the "
             "marker handoff-ok." if tokens >= block
             else f" At {fmt(block)} new {gated} calls will be denied (except a handoff).")
    emit(event, additionalContext=f"Context budget: {fmt(tokens)} tokens now, handoff threshold {fmt(warn)}. "
                                  f"{todo}{extra}")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — fail-open
        pass
    sys.exit(0)
