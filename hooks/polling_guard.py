#!/usr/bin/env python3
"""Polling guard: a PreToolUse hook on Bash that refuses home-made waiting in the foreground.

A foreground wait holds the session for nothing: a `until …; do sleep 20; done` loop runs until the Bash timeout,
and every one-off "is CI done yet?" read is a full turn that re-reads the whole context. The harness already
wakes a session when a background command ends; agent-hub's `jwait` wakes it on journal lines, file output and
alarms. This hook denies:

* a loop (`until` / `while` / `for`) with `sleep` inside that has no upper bound, or one above
  AGENT_HUB_POLL_MAX_BOUNDED_WAIT seconds (iterations x longest sleep); if it waits on `pgrep -f <pattern>` without
  the bracket trick (`[p]ytest`), the reason says the pattern matches the waiting shell itself;
* a bare `sleep` longer than AGENT_HUB_POLL_MAX_SLEEP seconds;
* a one-off CI status read: a command segment matching AGENT_HUB_CI_STATUS_DENY and none of
  AGENT_HUB_CI_STATUS_ALLOW (defaults for `gh` and `glab` below: status, list, view and watch are denied; logs,
  traces, actions, write methods and a pipeline lookup by commit sha are allowed).

Not touched: `run_in_background: true` commands; short bounded retries; text inside `echo` / `printf` / `cat` and
heredoc bodies (that is writing a waiter, not running it); commands carrying the escape marker
`# poll-ok: <reason>` (AGENT_HUB_POLL_ESCAPE), which leaves the reason in the transcript.

Settings (environment, the repository's .agent-hub/config.json, or the hub home's config.json):
  AGENT_HUB_POLL_GUARD              on | off (default on)
  AGENT_HUB_POLL_MAX_SLEEP          30      AGENT_HUB_POLL_MAX_BOUNDED_WAIT  90
  AGENT_HUB_POLL_ESCAPE             poll-ok
  AGENT_HUB_CI_STATUS_DENY          JSON list of regexes (replaces the defaults; `polling_guard.py --defaults`)
  AGENT_HUB_CI_STATUS_ALLOW         JSON list of regexes (replaces the defaults)
  AGENT_HUB_WAIT_HINT               one more line for the deny message, e.g. the project's own CI wait command
Fail-open: an error of its own never blocks a command.
"""
from __future__ import annotations

import json
import os
import re
import sys

DEFAULTS = {"max_sleep": 30, "max_bounded_wait": 90, "escape": "poll-ok"}

# One-off CI status reads, searched in each command segment (case-insensitive).
DEFAULT_CI_DENY = [
    r"\bglab\s+ci\s+(?:status|view|get|list)\b",
    r"\bglab\s+api\b.*?(?:^|[\s'\"/])(?:pipelines|jobs)(?:[/?\s'\"]|$)",
    r"\bgh\s+run\s+(?:view|list|watch)\b",
    r"\bgh\s+pr\s+checks\b",
    r"\bgh\s+api\b.*?/actions/(?:runs|jobs)\b",
    r"\bgh\s+api\b.*?/commits/[^/\s]+/(?:status|statuses|check-runs|check-suites)\b",
]
# A denied segment that also matches one of these passes: logs, actions, writes, a lookup by commit.
DEFAULT_CI_ALLOW = [
    r"/(?:trace|retry|play|cancel|erase|artifacts|logs|rerun|rerun-failed-jobs)\b",
    r"[?&](?:head_)?sha=[^&\s'\"]+",
    r"(?:-X|--method)[\s=]*['\"]?(?:POST|PUT|DELETE|PATCH)\b",
    r"\bgh\s+run\s+view\b.*\s--log(?:-failed)?\b",
]

_SLEEP = re.compile(r"(?:^|[\s;&|(])(?:command\s+)?sleep\s+(\d+(?:\.\d+)?)")
_LOOP = re.compile(r"(?:^|[\s;&|(])(?:until|while|for)\s")
_SEQ = re.compile(r"seq\s+(?:-?\w+\s+)?(\d+)\s+(\d+)")
_BRACE_RANGE = re.compile(r"\{(\d+)\.\.(\d+)\}")
_FOR_LIST = re.compile(r"\bfor\s+\w+\s+in\s+([^;$({\n]+?)(?:;|\s+do\b)")
_PGREP_F = re.compile(r"pgrep\s+(?:-\w+\s+)*-\w*f\w*\s+(?:'([^']*)'|\"([^\"]*)\"|(\S+))")
# A heredoc body is a file being written, not commands being run.
_HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?.*?^\s*\1\s*$", re.DOTALL | re.MULTILINE)
# Segments that print rather than run: `echo 'until …; do sleep 20; done'`.
_PRINTING = re.compile(r"^\s*(?:\w+=\S+\s+)*(?:echo|printf|cat)\b")
_SEGMENT_SEP = re.compile(r"(?:\|\||&&|[;|\n])")

INSTEAD = """Instead:
  • a long command (tests, a build, a deploy) — the same command with Bash `run_in_background: true`; the harness
    wakes you when it ends and hands you its exit code, there is nothing to poll;
  • journal lines, a script's output, a deadline — one `jwait` with `run_in_background: true` (see the hub skill);
{hint}  • external state the harness does not track — the Monitor tool.

If the wait is deliberate, add the comment `# {escape}: <reason>` to the command; the reason stays in the
transcript."""

DEFAULT_HINT = ("  • CI — your CI's own blocking wait in the background (e.g. `gh run watch <id> --exit-status`);\n"
                "    a pipeline lookup by commit sha and job logs are allowed in the foreground;\n")


def hubcore():
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, os.path.join(root, "bin"))
    import hubcore as hc  # noqa: E402

    return hc


class Config:
    def __init__(self, cwd=None, hc=None):
        def num(name, default):
            try:
                return float(hc.setting(name, cwd=cwd) or default) if hc else default
            except ValueError:
                return default

        def patterns(name, default):
            raw = hc.setting_json(name, None, cwd=cwd) if hc else None
            src = default if raw is None else ([raw] if isinstance(raw, str) else list(raw))
            out = []
            for p in src:
                try:
                    out.append(re.compile(str(p), re.IGNORECASE))
                except re.error as e:
                    print(f"agent-hub: {name}: bad regex {p!r} ({e}); skipped", file=sys.stderr)
            return out

        self.enabled = (hc.setting("AGENT_HUB_POLL_GUARD", cwd=cwd) if hc else None) or "on"
        self.enabled = self.enabled.strip().lower() not in ("off", "0", "false", "no")
        self.max_sleep = num("AGENT_HUB_POLL_MAX_SLEEP", DEFAULTS["max_sleep"])
        self.max_bounded = num("AGENT_HUB_POLL_MAX_BOUNDED_WAIT", DEFAULTS["max_bounded_wait"])
        self.escape_word = ((hc.setting("AGENT_HUB_POLL_ESCAPE", cwd=cwd) if hc else None) or DEFAULTS["escape"]).strip()
        self.escape = re.compile(r"#\s*" + re.escape(self.escape_word) + r"\b")
        self.ci_deny = patterns("AGENT_HUB_CI_STATUS_DENY", DEFAULT_CI_DENY)
        self.ci_allow = patterns("AGENT_HUB_CI_STATUS_ALLOW", DEFAULT_CI_ALLOW)
        hint = hc.setting("AGENT_HUB_WAIT_HINT", cwd=cwd) if hc else None
        self.hint = f"  • {hint.strip()}\n" if hint else DEFAULT_HINT


def executable_part(cmd: str) -> str:
    """The command without what it only prints or writes to a file."""
    cmd = _HEREDOC.sub(" ", cmd)
    return ";".join(seg for seg in _SEGMENT_SEP.split(cmd) if not _PRINTING.match(seg))


def bounded_iterations(cmd: str):
    """Upper bound of the loop's iterations, or None when there is none."""
    if re.search(r"(?:^|[\s;&|(])(?:until|while)\s", cmd):
        return None  # a counter inside the body cannot be proven from the text
    m = _SEQ.search(cmd)
    if m:
        return int(m.group(2)) - int(m.group(1)) + 1
    m = _BRACE_RANGE.search(cmd)
    if m:
        return int(m.group(2)) - int(m.group(1)) + 1
    m = _FOR_LIST.search(cmd)
    if m:
        items = m.group(1).split()
        if items and all(not any(ch in it for ch in "*?[]`") for it in items):  # `for f in *.txt` is no bound
            return len(items)
    return None


def self_matching_pgrep(cmd: str):
    for m in _PGREP_F.finditer(cmd):
        pattern = next(g for g in m.groups() if g is not None)
        if "[" in pattern:  # bracket trick: "[p]ytest" does not match itself
            continue
        return pattern
    return None


def wait_reason(command: str, cfg: Config):
    """Why a (printing-stripped) command is a foreground wait, or None."""
    sleeps = [float(x) for x in _SLEEP.findall(command)]
    if not sleeps:
        return None
    longest = max(sleeps)
    if _LOOP.search(command):
        iterations = bounded_iterations(command)
        if iterations is None:
            budget = "a loop without an upper bound"
        else:
            total = iterations * longest
            if total <= cfg.max_bounded:
                return None
            budget = f"a loop of up to {iterations} iterations of {longest:g} s, up to {total:.0f} s"
        pattern = self_matching_pgrep(command)
        if pattern is not None:
            return (f"This is polling in a loop ({budget}) on `pgrep -f {pattern}` — the pattern matches the waiting "
                    "shell's own command line, so the loop never ends.")
        return f"This is polling in a loop ({budget}); Bash cuts it off at its timeout, not at the event."
    if longest > cfg.max_sleep:
        return f"This is `sleep {longest:g}` in the foreground — {longest:.0f} s of a held session without an event."
    return None


def ci_reason(command: str, cfg: Config):
    """Why a (printing-stripped) command is a one-off CI status read, or None."""
    for seg in _SEGMENT_SEP.split(command):
        if any(p.search(seg) for p in cfg.ci_deny) and not any(p.search(seg) for p in cfg.ci_allow):
            return f"This is `{seg.strip()}` — reading CI status by hand."
    return None


def check(command: str, background: bool, cfg: Config):
    """(kind, reason) of a denial, or None. kind: wait | ci."""
    if background or not cfg.enabled or cfg.escape.search(command):
        return None
    cmd = executable_part(command)
    r = wait_reason(cmd, cfg)
    if r:
        return "wait", r
    try:
        r = ci_reason(cmd, cfg)
    except Exception:  # noqa: BLE001 — fail-open
        r = None
    return ("ci", r) if r else None


def message(kind: str, reason: str, cfg: Config) -> str:
    head = ("Waiting in the foreground is not run (agent-hub polling guard)." if kind == "wait" else
            "Reading CI status by hand in the foreground is not run (agent-hub polling guard): every such read is "
            "a turn that re-reads the whole context.")
    return f"{head}\n\n{reason}\n\n" + INSTEAD.format(hint=cfg.hint, escape=cfg.escape_word)


def main() -> int:
    if sys.argv[1:] == ["--defaults"]:
        print(json.dumps({"AGENT_HUB_CI_STATUS_DENY": DEFAULT_CI_DENY, "AGENT_HUB_CI_STATUS_ALLOW": DEFAULT_CI_ALLOW},
                         indent=1))
        return 0
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict) or event.get("tool_name") != "Bash":
        return 0
    ti = event.get("tool_input") or {}
    command = ti.get("command")
    if not isinstance(command, str):
        return 0
    background = bool(ti.get("run_in_background"))
    if background:
        return 0
    try:
        hc = hubcore()
    except Exception:  # noqa: BLE001 — without the plugin's bin/ the built-in defaults still apply
        hc = None
    cfg = Config(cwd=event.get("cwd"), hc=hc)
    res = check(command, background, cfg)
    if res:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message(res[0], res[1], cfg),
        }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:  # noqa: BLE001 — fail-open
        code = 0
    sys.exit(code)
