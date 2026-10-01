"""Lock board shared by agent sessions: <hub home>/board.md.

The board is Markdown for humans with one machine-readable part: a fenced block
tagged ``locks`` holding one JSON object per line. Everything outside that block
is regenerated on every write; edit locks through ``lock``, not by hand.

A lock record:
  kind        the resource: main-merge (built in) or a name from lock-rules.json (bin/lockrules.py)
  repo        repository name the lock guards; "*" (the default) = every repo
  owner_name  human name of the session (its sidebar title)
  session_id  $CLAUDE_CODE_SESSION_ID of the holder; "" = nobody's session yet
  until       ISO 8601 with offset; a lock past it is void
  why         reason, free text
  value       optional payload (e.g. the expected head of a migration chain)
  taken_at    ISO 8601
  took_over_from  owner_name of the previous holder when taken with --force

Board path: $AGENT_BOARD_FILE, else <hub home>/board.md (`hub home` shows the hub home).
Python 3.10+ stdlib only: the PreToolUse hook imports this module and must stay fast.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import hubcore as hc  # noqa: E402

BOARD = Path(os.environ.get("AGENT_BOARD_FILE") or (hc.root() / "board.md"))
TZ = hc.TZ
DEFAULT_REPO = "*"

_BLOCK = re.compile(r"^```locks[ \t]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)

HEADER = """# Agent lock board

Who holds a shared resource right now. The `board_locks` hook of the agent-hub plugin refuses a
command that touches a resource under **another session's active** lock; your own lock, an expired
lock or no lock passes. Escape hatch: `# lock-ok: <reason>` in the command itself (it stays in the
transcript).

Resources: `main-merge` is built in — the standing role "who merges main"; merges into, and pushes to,
the protected branches are refused to everyone but the holder. A successor takes the role with
`lock take main-merge --force --until … --why …`. Every other resource (a deploy window, a shared environment,
a migration head, …) is named by the project in `lock-rules.json`, next to this file or in the repository's
`.agent-hub/`; `lock rules` lists them with the commands each one guards. A resource with no rule is
informational: the hook refuses nothing for it.

Commands: `lock list`, `lock rules`, `lock take <resource> --until 2026-09-25T18:00 --why "…" [--owner-name "…"]
[--value …] [--repo NAME] [--force]`, `lock release <resource> [--force]`.

The machine part below (one JSON line per lock) is written by `lock`, atomically. Do not edit by hand.

"""


class BoardError(Exception):
    """The board exists but cannot be parsed."""


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def parse_time(raw: str, base: Optional[dt.datetime] = None) -> dt.datetime:
    """ISO datetime (naive = hub time zone), 'HH:MM' today, a date (end of that day), or '+2h' / '+90m' / '+3d'."""
    base = base or now()
    raw = raw.strip()
    m = re.fullmatch(r"\+(\d+)([mhd])", raw)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"m": dt.timedelta(minutes=n), "h": dt.timedelta(hours=n), "d": dt.timedelta(days=n)}[unit]
        return (base + delta).replace(microsecond=0)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if m:
        return base.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raw += "T23:59:00"
    t = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=TZ)
    return t.astimezone(TZ)


def fmt(t: dt.datetime) -> str:
    return t.astimezone(TZ).replace(microsecond=0).isoformat()


def read_text() -> Optional[str]:
    try:
        return BOARD.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def parse(text: Optional[str]) -> list:
    """Lock records from board text. No board = no locks; a broken one raises."""
    if text is None:
        return []
    m = _BLOCK.search(text)
    if not m:
        raise BoardError("no ```locks block")
    locks = []
    for n, line in enumerate(m.group(1).splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError as e:
            raise BoardError(f"line {n}: {e}") from None
        # any resource name parses: the set of resources is the project's, and a record outlives a config change
        if not isinstance(rec, dict) or not isinstance(rec.get("kind"), str) or not rec["kind"] \
                or not isinstance(rec.get("until"), str):
            raise BoardError(f"line {n}: bad record")
        parse_time(rec["until"])  # raises ValueError on garbage
        locks.append(rec)
    return locks


def load() -> list:
    return parse(read_text())


def is_active(rec: dict, at: Optional[dt.datetime] = None) -> bool:
    return parse_time(rec["until"]) > (at or now())


def repo_matches(rec: dict, repo: Optional[str]) -> bool:
    r = rec.get("repo") or DEFAULT_REPO
    return r == "*" or repo is None or r == repo


def render(locks: list) -> str:
    at = now()
    lines = [HEADER, "```locks"]
    lines += [json.dumps(r, ensure_ascii=False, sort_keys=False) for r in locks]
    lines += ["```", "", f"## Summary (redrawn {fmt(at)})", ""]
    if not locks:
        lines.append("No locks.")
    else:
        lines.append("| kind | repo | holder | until | state | reason |")
        lines.append("|---|---|---|---|---|---|")
        for r in locks:
            state = "active" if is_active(r, at) else "expired"
            holder = r.get("owner_name") or "?"
            if r.get("session_id"):
                holder += f" (`{r['session_id']}`)"
            why = (r.get("why") or "").replace("|", "/")
            if r.get("value"):
                why += f" [value: {r['value']}]"
            lines.append(f"| {r['kind']} | {r.get('repo') or DEFAULT_REPO} | {holder} | {r['until']} | {state} | {why} |")
    return "\n".join(lines) + "\n"


class Locked:
    """Exclusive flock around a read-modify-write of the board."""

    def __enter__(self):
        BOARD.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(BOARD.parent / ".board.lock", "w")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def write(locks: list) -> None:
    """Atomic replace: temp file in the same directory, fsync, rename."""
    data = render(locks)
    BOARD.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".board.", suffix=".tmp", dir=str(BOARD.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, BOARD)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
