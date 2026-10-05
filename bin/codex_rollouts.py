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

import topcache

TTL = 30.0
HEADER_MAX = 256_000
META_VALUE_MAX = 4000             # a meta value larger than this (base_instructions) is not kept in the disk cache


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
    """Cache metadata-only discovery, reading at most one bounded header per file. With a `store` (agent-top's disk
    cache) a header already read by an earlier process is not read again: a rollout only grows, so it is kept by path
    while the inode is the same and the file is not shorter; the meta's large values (base instructions) are not kept."""

    def __init__(self):
        self.checked, self.records = None, {}
        self.store = None
        self.kids = None

    def update(self):
        now = time.monotonic()
        if self.checked is not None and now - self.checked < TTL:
            return self
        root = home() / "sessions"
        heads = (self.store.get("rollout-heads", str(root)) if self.store else None) or {}
        fresh, changed = {}, False
        records = {}
        for path in sorted(root.glob("**/rollout-*.jsonl")):
            try:
                st = path.stat()
                hit = heads.get(str(path))
                # a header read before holds while the file is the same one, not shorter, and its first line's ends
                # are the bytes read (topcache.anchor: two 256-byte reads, not the line); "no header" holds only while
                # the file is untouched (a first line fixed or rewritten in place is read again)
                if hit and len(hit) == 5 and hit[0] == st.st_ino and (
                        st.st_size >= hit[1] and topcache.anchor(path, hit[4][0]) == hit[4][1] if hit[3] is not None
                        else st.st_mtime_ns == hit[2]):
                    head, mark = hit[3], hit[4]
                else:
                    got, changed = self._head(path), True
                    if got is False:
                        continue  # a first line still being written: read it again next time
                    head, mark = (None, None) if got is None else (got[:2], [got[2], topcache.anchor(path, got[2])])
                fresh[str(path)] = [st.st_ino, st.st_size, st.st_mtime_ns, head, mark]
                if head is None:
                    continue
                # A resumed session may have more than one file. Use its newest
                # file instead of showing duplicate sessions or duplicate children.
                sid, meta, mtime = head[0], head[1], st.st_mtime
                if sid not in records or mtime > records[sid][2]:
                    records[sid] = (path, meta, mtime)
            except OSError:
                continue
        if self.store and (changed or len(fresh) != len(heads)):
            self.store.put("rollout-heads", str(root), fresh)
        self.checked, self.records = now, records
        return self

    def _head(self, path):
        """[session id, meta, length of the line] of a rollout's session_meta line; None when it has none; False when
        the line is not complete yet."""
        try:
            with path.open("rb") as f:
                raw = f.readline(HEADER_MAX + 1)
        except OSError:
            return False
        if len(raw) > HEADER_MAX:
            return None
        if not raw.endswith(b"\n"):
            return False
        try:
            ev = json.loads(raw)
            meta = ev.get("payload")
            if ev.get("type") != "session_meta" or not isinstance(meta, dict) or not meta.get("id"):
                return None
        except (ValueError, AttributeError):
            return None
        if self.store:
            meta = {k: v for k, v in meta.items() if len(json.dumps(v, default=str)) <= META_VALUE_MAX}
        return [str(meta["id"]), meta, len(raw)]

    def session(self, sid):
        return self.update().records.get(sid)

    def children(self, sid):
        self.update()
        if self.kids is None or self.kids[0] is not self.records:
            kids = {}
            for aid, rec in self.records.items():
                parent = (spawn_source(rec[1]) or {}).get("parent_thread_id")
                if parent:
                    kids.setdefault(parent, []).append((aid, *rec))
            self.kids = (self.records, kids)   # by parent, built once per discovery (a hundred sessions ask)
        return list(self.kids[1].get(sid, ()))


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
                last = info.get("last_token_usage")
                last = last if isinstance(last, dict) else {}
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
