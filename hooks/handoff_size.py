#!/usr/bin/env python3
"""PreToolUse hook on Write|Edit: a HANDOFF-*.md file must stay <= 15 KiB (15360 bytes UTF-8).

A handoff is read by a fresh session as its entry point; a long one burns the successor's context
before any work starts. Write: size of tool_input.content. Edit: read the current file, apply
old_string -> new_string (all occurrences when replace_all), measure the result. The limit is
overridable by $AGENT_HUB_HANDOFF_MAX_BYTES or the hub home's config.json. Fail-open: any error of its own (bad input, unreadable
file, old_string not found) -> exit 0, no output.
"""
from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path

REASON = (
    "Handoff is {size} bytes > {limit}. Shorten it: follow the agent-hub handoff template "
    "(templates/HANDOFF-template.md in the plugin; ≤ 12 KB, chronology goes to journal-<date>.md) and continue "
    "in a new session from it."
)


def hub_setting(name: str):
    """$NAME, else the hub home's config.json (hubcore.setting from the plugin's bin/)."""
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, os.path.join(root, "bin"))
    import hubcore  # noqa: E402

    return hubcore.setting(name)


def main() -> None:
    data = json.loads(sys.stdin.read() or "{}")
    if not isinstance(data, dict) or data.get("hook_event_name", "PreToolUse") != "PreToolUse":
        return
    tool = data.get("tool_name")
    ti = data.get("tool_input") or {}
    fp = ti.get("file_path")
    if tool not in ("Write", "Edit") or not isinstance(fp, str):
        return
    if not fnmatch.fnmatchcase(os.path.basename(fp), "HANDOFF-*.md"):
        return
    try:
        limit = int(hub_setting("AGENT_HUB_HANDOFF_MAX_BYTES") or 15360)
    except ValueError:
        print("handoff_size: AGENT_HUB_HANDOFF_MAX_BYTES is not a whole number; using 15360", file=sys.stderr)
        limit = 15360

    if tool == "Write":
        content = ti.get("content")
        if not isinstance(content, str):
            return
    else:
        old, new = ti.get("old_string"), ti.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return
        cur = Path(fp).read_text(encoding="utf-8")
        if old == "":
            content = new if cur == "" else None
        elif old not in cur:
            content = None  # the Edit itself will fail; not our business
        else:
            content = cur.replace(old, new) if ti.get("replace_all") else cur.replace(old, new, 1)
        if content is None:
            return

    size = len(content.encode("utf-8"))
    if size <= limit:
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": REASON.format(size=size, limit=limit),
    }}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
