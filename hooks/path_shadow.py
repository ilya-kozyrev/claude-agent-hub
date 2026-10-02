#!/usr/bin/env python3
"""SessionStart hook: one line when a command of the same name as one of the plugin's tools (any executable of its bin/:
hub, jlog, jwait, agent, ask, roles, lock, …) comes before the plugin's bin/ on PATH — GitHub CLI `hub` from Homebrew is
the usual one. The agent-hub commands then run the other program, and an agent's `jlog` writes to a journal the hub never
reads.

Reads PATH as this hook process sees it; nothing is run. Does nothing, and writes nothing, until a hub home exists
(<hub home>: `hub start` creates it): a machine that never ran a hub is left alone.
Scope as in questions.py: a session that starts in the hub home, in a repository with `.agent-hub/`, under
AGENT_HUB_SCOPE_DIRS, or as a hub agent (HUB_TAG) hears it every time; a session elsewhere (a first project that has no `.agent-hub/` yet) hears it once per distinct set of shadowing
paths, remembered in <state dir>/path-shadow/seen (AGENT_HUB_STATE_DIR, default <hub home>/.state). Fail-open: any
error of its own -> exit 0 with no output.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def bin_dir() -> Path:
    root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return Path(root) / "bin"


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")  # drained so the harness never blocks on the pipe
    except Exception:
        event = {}
    event = event if isinstance(event, dict) else {}
    sys.path.insert(0, str(bin_dir()))
    import hubcore as hc  # noqa: E402

    hc.use_cwd(event.get("cwd"))
    if not hc.root().is_dir():
        return 0
    shadowed = hc.shadowed_tools()
    if not shadowed:
        return 0
    seen = None
    if not (os.environ.get("HUB_TAG") or hc.in_scope(event.get("cwd") or os.getcwd())):
        seen = hc.state_dir() / "path-shadow" / "seen"
        signature = "\n".join(sorted(f"{n}={p}" for n, p in shadowed))
        try:
            if seen.read_text(encoding="utf-8") == signature:
                return 0
        except OSError:
            pass
        hc.atomic_write(seen, signature)
    line = "agent-hub: " + hc.shadow_warning(shadowed) + ". Tell the user about it in one line."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": line}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    sys.exit(0)
