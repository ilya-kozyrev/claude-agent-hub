"""Sub-agents (the Agent tool) of Claude Code sessions: where their transcripts are, whether their parent session
runs, how each one ended. Shared by `agent-top` (the console lists them) and `hub handoff` (refuses to hand over
while one still runs). Read-only: nothing here writes a file. Python 3.10+ stdlib only.

A sub-agent is found in its parent session's transcript folder (<claude config>/projects/*/<session>/subagents/).
It is done / error / dead from the parent's completion notice (a foreground one: the result of its Agent call);
without one it is live while the parent session runs (<claude config>/sessions/<pid>.json with a live claude pid)
and dead once it is gone — where that folder does not exist, dead after 30 min of silence.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import time
from pathlib import Path

import codex_rollouts

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TOOL_ID_RE = re.compile(rb'"tool_use_id"\s*:\s*"([^"]+)"')
NOTICE_RE = re.compile(rb"<task-id>([\w-]+)</task-id>.*?<status>(\w+)</status>", re.S)
SUB_RECENT_S = 3600               # finished sub-agents older than this are hidden unless asked for
SUB_LOST_S = 1800                 # no notice, silent this long, parent's liveness unknown: count it as died
SUB_DIRS_TTL = 30.0               # how long a session's sub-agent folders are cached before the next glob
SUB_STATE = {"completed": "done", "failed": "error"}   # any other notice status (killed, stopped) is "dead"
TAIL_BYTES = 1_000_000            # how much of a transcript's end tail_last_user_ts reads
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


# ---------------------------------------------------------------- small readers

def parse_ts(raw):
    if not isinstance(raw, str):
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def loads(line: bytes):
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    return ev if isinstance(ev, dict) else None


def line_ts(line: bytes):
    """Epoch of a transcript line's own top-level "timestamp", or None (a tool result may nest its own)."""
    ev = loads(line)
    return parse_ts(ev.get("timestamp")) if ev else None


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def tail_last_user_ts(path: Path):
    """Epoch of the newest user line (a prompt or a tool result) in the last TAIL_BYTES of a sub-agent's transcript,
    or None. The default answer to "was it written to after it ended" where nothing reads the log incrementally."""
    try:
        with open(path, "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            start = max(0, size - TAIL_BYTES)
            fh.seek(start)
            if start:
                fh.readline()                 # a partial line
            best = None
            for line in fh:
                if not line.endswith(b"\n") or not line.startswith(b'{"parentUuid"') or b'"user"' not in line:
                    continue
                ev = loads(line)
                ts = parse_ts(ev.get("timestamp")) if ev and ev.get("type") == "user" else None
                if ts is not None and (best is None or ts > best):
                    best = ts
            return best
    except OSError:
        return None


# ---------------------------------------------------------------- processes and sessions

def process_table():
    """{pid: command line} of every process, or None when `ps` is unusable."""
    try:
        r = subprocess.run(["ps", "-ww", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    table = {}
    for ln in r.stdout.splitlines():
        parts = ln.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            table[int(parts[0])] = parts[1]
    return table or None


def is_alive(meta: dict, table) -> bool:
    pid, sid = meta.get("pid"), meta.get("process_token") or meta.get("session_id") or ""
    if not isinstance(pid, int) or not pid:
        return False
    if table is None:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        return True
    return bool(sid) and sid in table.get(pid, "")   # a reused pid runs another command line


def live_sessions(table):
    """{session id: pid} of running Claude Code processes, from <claude config>/sessions/<pid>.json (the CLI writes
    one per process and removes it on exit); None when that folder does not exist (liveness unknown)."""
    d = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "sessions"
    if not d.is_dir():
        return None
    out = {}
    for f in d.glob("*.json"):
        rec = read_json(f)
        if not isinstance(rec, dict) or not isinstance(rec.get("pid"), int) or not rec.get("sessionId"):
            continue
        pid = rec["pid"]
        if table is not None:
            # the file is named by pid, so a new CLI on a reused pid overwrites it; a reuse by anything else is
            # caught here (an interactive session's command line holds no session id, only the binary)
            if "claude" not in table.get(pid, ""):
                continue
        else:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass
        out[str(rec["sessionId"])] = pid
    return out


def projects_root() -> Path:
    """Where Claude Code keeps session transcripts: $CLAUDE_CONFIG_DIR/projects, else ~/.claude/projects."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"


def parent_alive(rec: dict, sid: str, table, live):
    """Whether a session runs: True / False, or None when there is no session registry to ask (the caller then
    falls back to the silence rule). `rec` is the session's role record: a headless agent is judged by its pid."""
    pid = rec.get("pid")
    if rec.get("kind") == "headless" and isinstance(pid, int) and is_alive({**rec, "session_id": sid}, table):
        return True
    if rec.get("engine") == "codex" or codex_rollouts.INDEX.session(sid):
        # Native Codex has no Claude-style per-pid session registry. An unrelated
        # Claude registry must not turn an unknown Codex parent into a dead one.
        if isinstance(pid, int):
            return is_alive({**rec, "session_id": sid}, table)
        return None
    if live is not None:
        return sid in live
    return None


# ---------------------------------------------------------------- completion notices

class Notices:
    """How the sub-agents of one parent session ended, read incrementally from the parent's transcript.
    by_id: {agent id: (status, epoch)} from <task-notification> blocks — the last one wins (a resumed sub-agent
    notifies again); only notices the CLI queued count (a queue-operation, a queued_command attachment or a user
    message that is the notice itself), not text that quotes one. results: {tool_use_id: (is_error, epoch)} of every
    tool result — a foreground sub-agent gets no notice, its Agent call just returns. The whole file is read once
    (only lines holding a marker are parsed), then only what was appended."""

    def __init__(self, path: Path):
        self.path, self.ino, self.offset, self.by_id, self.results = path, None, 0, {}, {}

    def update(self) -> "Notices":
        try:
            st = os.stat(self.path)
        except OSError:
            return self
        if st.st_ino != self.ino or st.st_size < self.offset:
            self.ino, self.offset, self.by_id, self.results = st.st_ino, 0, {}, {}
        if st.st_size <= self.offset:
            return self
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                while True:
                    line = fh.readline()
                    if not line or not line.endswith(b"\n"):
                        break
                    self.offset += len(line)
                    if b"<task-notification>" in line:
                        self._notice(line)
                    if b'"tool_result"' in line and TOOL_ID_RE.search(line):
                        self._results(line)
        except OSError:
            pass
        return self

    def _results(self, line: bytes) -> None:
        ev = loads(line)
        if not ev or ev.get("type") != "user":
            return
        at = parse_ts(ev.get("timestamp"))
        content = (ev.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                self.results[str(b["tool_use_id"])] = (bool(b.get("is_error")), at)

    def _notice(self, line: bytes) -> None:
        ev = loads(line)
        if not ev:
            return
        typ = ev.get("type")
        if typ == "queue-operation" and ev.get("operation") == "enqueue":
            text = ev.get("content")
        elif typ == "attachment" and isinstance(ev.get("attachment"), dict) and ev["attachment"].get("type") == "queued_command":
            text = ev["attachment"].get("prompt")
        elif typ == "user":
            text = (ev.get("message") or {}).get("content")
        else:
            return
        if not isinstance(text, str) or not text.lstrip().startswith("<task-notification>"):
            return
        at = parse_ts(ev.get("timestamp"))
        for m in NOTICE_RE.finditer(text.encode("utf-8", "replace")):
            self.by_id[m.group(1).decode("utf-8", "replace")] = (m.group(2).decode("ascii", "replace"), at)


# ---------------------------------------------------------------- the sub-agents of a session

class Sub:
    """One sub-agent as found on disk: its state and the facts that decide it. state: live / done / error / dead."""
    __slots__ = ("aid", "log", "meta", "mtime", "status", "state", "background")

    def __init__(self, aid, log, meta, mtime, status, state, background):
        self.aid, self.log, self.meta, self.mtime = aid, log, meta, mtime
        self.status, self.state, self.background = status, state, background

    @property
    def alive(self) -> bool:
        return self.state == "live"

    @property
    def description(self) -> str:
        return " ".join(_CTRL_RE.sub(" ", str(self.meta.get("description") or "")).split())

    def age(self, now: float):
        return None if self.mtime is None else max(0, now - self.mtime)


class Finder:
    """Finds the sub-agents of sessions and decides their state; caches the folder globs, the metas and the parents'
    notices between calls. `last_user_ts(log path)` answers "was the transcript written to by a user line after the
    sub-agent ended" (a resumed sub-agent): agent-top passes its incremental log reader, the default reads the
    transcript's tail."""

    def __init__(self, last_user_ts=None):
        self.last_user_ts = last_user_ts or tail_last_user_ts
        self.notices, self.sub_dirs, self.metas = {}, {}, {}
        self.codex_states = {}

    def codex_session(self, sid, parent_is_alive, now, show_all=False):
        rec = codex_rollouts.INDEX.session(sid)
        return self._codex_sub(sid, *rec, parent_is_alive, now, show_all) if rec else None

    def _codex_sub(self, aid, log, meta, mtime, parent_is_alive, now, show_all):
        # File activity is not a process identity; preserve the existing silence
        # fallback only where the parent's process is unknown.
        old = now - mtime > SUB_RECENT_S
        if not show_all and old and parent_is_alive is not True:
            return None
        reader = self.codex_states.setdefault(log, codex_rollouts.State(log)).update()
        status = reader.status
        if status is not None:
            state = SUB_STATE.get(status, "dead")
        elif parent_is_alive is False or now - mtime > SUB_LOST_S and parent_is_alive is not True:
            state = "dead"
        else:
            state = "live"
        spawn = codex_rollouts.spawn_source(meta) or {}
        info = {**meta, "engine": "codex", "model": reader.model, "effort": reader.effort,
                "description": spawn.get("agent_path") or spawn.get("agent_nickname") or "",
                "agentType": spawn.get("agent_role") or "codex sub-agent"}
        return Sub(aid, log, info, mtime, status, state, True)

    def dirs(self, sid: str) -> list:
        hit = self.sub_dirs.get(sid)
        if hit and time.monotonic() - hit[0] < SUB_DIRS_TTL:
            return hit[1]
        try:
            dirs = sorted(projects_root().glob(f"*/{sid}/subagents"))
        except OSError:
            dirs = []
        self.sub_dirs[sid] = (time.monotonic(), dirs)
        return dirs

    def meta(self, path: Path) -> dict:
        try:
            key = (path, os.stat(path).st_mtime_ns)
        except OSError:
            return {}
        hit = self.metas.get(key)
        if hit is None:
            hit = read_json(path)
            hit = self.metas[key] = hit if isinstance(hit, dict) else {}
        return hit

    def of_session(self, sid: str, parent_is_alive, now: float, show_all: bool = False) -> list:
        """The sub-agents of one session (a full uuid). Finished or orphaned ones older than SUB_RECENT_S are left
        out unless `show_all`; those are not even read."""
        out = []
        for aid, log, meta, mtime in codex_rollouts.INDEX.children(sid):
            sub = self._codex_sub(aid, log, meta, mtime, parent_is_alive, now, show_all)
            if sub:
                out.append(sub)
        for sdir in self.dirs(sid):
            path = sdir.parent.parent / f"{sid}.jsonl"
            notes = self.notices.setdefault(path, Notices(path)).update()
            for mp in sorted(sdir.glob("agent-*.meta.json")):
                sub = self._sub(mp, notes, parent_is_alive, now, show_all)
                if sub:
                    out.append(sub)
        return out

    def _sub(self, meta_path: Path, notes: Notices, parent_is_alive, now: float, show_all: bool):
        aid = meta_path.name[len("agent-"):-len(".meta.json")]
        log = meta_path.with_name(f"agent-{aid}.jsonl")
        try:
            mtime = log.stat().st_mtime
        except OSError:
            mtime = None
        meta = self.meta(meta_path)
        status, at = notes.by_id.get(aid, (None, None))
        # a foreground call ends with its tool result; with no known shape only a notice counts (a background
        # call's tool result is just "launched")
        if status is None and meta.get("requestShape") == "foreground" and meta.get("toolUseId") in notes.results:
            err, at = notes.results[meta["toolUseId"]]
            status = "failed" if err else "completed"
        old = mtime is None or now - mtime > SUB_RECENT_S
        if not show_all and old and (status is not None or parent_is_alive is not True):
            return None                       # finished (or orphaned) long ago: not even its transcript is read
        # resumed (SendMessage) after it ended: its transcript got a new user line after the end; compared on the
        # CLI's own timestamps, not on file times
        last_user = self.last_user_ts(log) if status is not None and at is not None else None
        resumed = last_user is not None and last_user > at
        finished = status is not None and not resumed
        if finished:
            state = SUB_STATE.get(status, "dead")
        elif parent_is_alive is True:
            state = "live"
        elif parent_is_alive is False or mtime is None or now - mtime > SUB_LOST_S:
            state = "dead"
        else:
            state = "live"
        return Sub(aid, log, meta, mtime, status if finished else None, state, meta.get("requestShape") == "background")
