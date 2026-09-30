#!/usr/bin/env python3
"""SessionStart hook: one line about unanswered owner questions per stage of the hub home.

Reads <hub home>/<stage>/questions.md through the `ask` tool's own parser (<plugin>/bin/ask), so the
format has one home. Prints nothing when no stage has an unresolved entry. Fail-open: any error of
its own -> exit 0 with no output.
"""
from __future__ import annotations

import json
import os
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path


def ask_path() -> Path:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return Path(root) / "bin" / "ask"


def load_ask():
    loader = SourceFileLoader("ask_register", str(ask_path()))
    spec = spec_from_loader("ask_register", loader)
    mod = module_from_spec(spec)
    sys.modules["ask_register"] = mod  # dataclasses look the module up while the class is built
    loader.exec_module(mod)
    return mod


def build_line() -> str:
    ask = load_ask()
    now = ask.now_local()
    parts = []
    for stage in ask.all_stages():
        try:
            _, entries = ask.load(stage)
        except BaseException:  # a broken file must not hide the other stages
            parts.append(f"{stage} — questions.md is unreadable (ask list --stage {stage})")
            continue
        c = ask.counts(entries, now)
        if c["open"] or c["default_taken"] or c["decided"]:
            parts.append(f"{ask.summary_line(stage, c)} (ask list --stage {stage})")
    if not parts:
        return ""
    return ("Owner questions: " + "; ".join(parts) +
            ". Work that no question blocks goes ahead; reports and handoffs link the register instead of copying it.")


def main(argv: list[str]) -> int:
    try:
        sys.stdin.read()  # hook JSON; not needed, drained so the harness never blocks on the pipe
    except Exception:
        pass
    line = build_line()
    if line:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": line}},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        main(sys.argv)
    except BaseException:
        pass
    sys.exit(0)
