"""Read-only discovery and normalization of Codex's local rollout JSONL files.

The persisted format is distinct from ``codex exec --json``. Unknown records are
ignored. No process registry is inferred from files; recent activity is only a
fallback when the parent's process cannot be identified. Forked rollouts can
include the parent's history: only tasks started after the child was created
belong to the child.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

TTL = 30.0
HEADER_MAX = 256_000


def epoch(raw):
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() if isinstance(raw, str) else None
    except ValueError:
        return None


def spawn_source(meta):
    source = meta.get("source")
    sub = source.get("subagent") if isinstance(source, dict) else None
    if not isinstance(sub, dict):
        return None
    spawn = sub.get("thread_spawn") or sub.get("spawn")
    return spawn if isinstance(spawn, dict) else None


def home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


class Index:
    """Cache metadata-only discovery, reading at most one bounded header per file."""

    def __init__(self):
        self.checked, self.records = None, {}

    def update(self):
        now = time.monotonic()
        if self.checked is not None and now - self.checked < TTL:
            return self
        records = {}
        for path in sorted((home() / "sessions").glob("**/rollout-*.jsonl")):
            try:
                with path.open("rb") as f:
                    raw = f.readline(HEADER_MAX + 1)
                if len(raw) > HEADER_MAX or not raw.endswith(b"\n"):
                    continue
                ev = json.loads(raw)
                meta = ev.get("payload")
                if ev.get("type") != "session_meta" or not isinstance(meta, dict) or not meta.get("id"):
                    continue
                # A resumed session may have more than one file. Use its newest
                # file instead of showing duplicate sessions or duplicate children.
                sid, mtime = str(meta["id"]), path.stat().st_mtime
                if sid not in records or mtime > records[sid][2]:
                    records[sid] = (path, meta, mtime)
            except (OSError, ValueError, AttributeError):
                continue
        self.checked, self.records = now, records
        return self

    def session(self, sid):
        return self.update().records.get(sid)

    def children(self, sid):
        return [(aid, *rec) for aid, rec in self.update().records.items()
                if (spawn_source(rec[1]) or {}).get("parent_thread_id") == sid]


class Normalizer:
    """Stateful persisted-event adapter, including fork-history filtering."""

    def __init__(self):
        self.sid = None
        self.birth = None
        self.own_task = True
        self.turn = None

    def events(self, ev):
        typ, payload = ev.get("type"), ev.get("payload")
        if not isinstance(payload, dict):
            return []
        ts = ev.get("timestamp")

        def record(kind, **fields):
            return {"type": kind, "timestamp": ts, "_engine": "codex", **fields}

        if typ == "session_meta":
            if self.sid is not None:
                return []  # inherited metadata must not reset the child's identity
            self.sid, self.birth = payload.get("id"), epoch(ts)
            self.own_task = not bool(spawn_source(payload))
            return [record("system", subtype="init", session_id=self.sid)]
        if typ == "event_msg" and payload.get("type") == "task_started":
            started = payload.get("started_at")
            if not self.own_task:
                if not isinstance(started, (int, float)) or self.birth is None or started < int(self.birth):
                    return []
                self.own_task = True
            self.turn = payload.get("turn_id")
            return [record("codex_turn_start", turn_id=self.turn)]
        if not self.own_task:
            return []
        if typ == "turn_context":
            return [record("codex_context", model=payload.get("model"), effort=payload.get("effort"))]
        if typ == "event_msg":
            ptype = payload.get("type")
            if ptype == "token_count":
                info = payload.get("info")
                if not isinstance(info, dict):
                    return []
                last = info.get("last_token_usage") or {}
                return [record("codex_usage", codex_usage=info.get("total_token_usage"),
                               context_tokens=last.get("input_tokens"), context_window=info.get("model_context_window"),
                               codex_usage_scope="session", codex_rate_limits=payload.get("rate_limits"))]
            if ptype in ("task_complete", "turn_aborted"):
                failed = ptype != "task_complete"
                return [record("result", subtype="error" if failed else "success", is_error=failed,
                               result=payload.get("last_agent_message") or payload.get("message") or payload.get("reason") or "")]
            return []  # item_completed duplicates the response_item stream
        if typ != "response_item":
            return []
        ptype = payload.get("type")
        if ptype == "message" and payload.get("role") in ("assistant", "user"):
            content = [{"type": "text", "text": b.get("text") or ""} for b in payload.get("content") or []
                       if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")]
            return [record(payload["role"], _count_turn=False, message={"content": content})]
        if ptype == "reasoning":
            # Encrypted reasoning is never displayed or reconstructed.
            content = [{"type": "thinking", "thinking": b.get("text") or ""}
                       for b in payload.get("summary") or [] if isinstance(b, dict) and b.get("text")]
            return [record("assistant", _count_turn=False, message={"content": content})] if content else []
        if ptype in ("function_call", "custom_tool_call"):
            inp = payload.get("arguments") if ptype == "function_call" else payload.get("input")
            if isinstance(inp, str) and ptype == "function_call":
                try:
                    inp = json.loads(inp)
                except ValueError:
                    pass
            if not isinstance(inp, dict):
                inp = {"input": inp}
            block = {"type": "tool_use", "id": payload.get("call_id"), "name": payload.get("name"), "input": inp}
            return [record("assistant", _count_turn=False, message={"content": [block]})]
        if ptype in ("function_call_output", "custom_tool_call_output"):
            block = {"type": "tool_result", "tool_use_id": payload.get("call_id"), "content": payload.get("output")}
            return [record("user", message={"content": [block]})]
        return []


INDEX = Index()


class State:
    """Incremental completion evidence for Finder, independent of the UI reader."""

    def __init__(self, path):
        self.path = path
        self.ino, self.offset = None, 0
        self.normalizer = Normalizer()
        self.status = None
        self.model = self.effort = None

    def update(self):
        try:
            st = self.path.stat()
            if self.ino != st.st_ino or st.st_size < self.offset:
                self.ino, self.offset = st.st_ino, 0
                self.normalizer = Normalizer()
                self.status = self.model = self.effort = None
            with self.path.open("rb") as f:
                f.seek(self.offset)
                while True:
                    raw = f.readline()
                    if not raw or not raw.endswith(b"\n"):
                        break
                    self.offset += len(raw)
                    try:
                        ev = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    for norm in self.normalizer.events(ev):
                        if norm["type"] == "codex_turn_start":
                            self.status = None
                        elif norm["type"] == "result":
                            self.status = "failed" if norm.get("is_error") else "completed"
                        elif norm["type"] == "codex_context":
                            self.model, self.effort = norm.get("model"), norm.get("effort")
        except OSError:
            pass
        return self
