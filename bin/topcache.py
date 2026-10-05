"""Disk cache of agent-top's incremental readers, so a fresh `agent-top --json` (the mod runs one every few seconds)
reads only what the logs gained since the last run instead of every log from the start.

One SQLite file, <state dir>/agent-top/cache.sqlite (the hub-wide state dir: $AGENT_HUB_STATE_DIR, else
<hub home>/.state). A row is (generation, kind, key) -> the JSON state of one reader: a log's offset and what was
counted up to it, taken together at flush time, so two processes writing the same row in any order leave a valid
resume point. A reader resumes only where the file is still the one it read: same inode, not shorter than the offset
(the reader's own check), and the same first bytes and bytes before the offset (anchor()). The generation is a hash of
the reader modules and of the settings that change what is read (the scan cap): an update starts empty, and an older
process still running reads and writes only its own rows. Rows not written for PRUNE_S (another generation's: a day)
are deleted. The cache is never needed: any error here, an unwritable state dir or AGENT_TOP_CACHE=0 means agent-top
reads everything as before. Nothing under the agents' folders is ever written. Python 3.10+ stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

SCHEMA = 2
PRUNE_S = 30 * 86400
BUSY_MS = 1500
ANCHOR = 256                      # bytes before a reader's offset (and at the file's start) checked before it resumes


def _encode(v):
    if isinstance(v, (set, frozenset)):
        return {"$set": list(v)}
    if isinstance(v, Path):
        return str(v)
    if hasattr(v, "__dict__"):
        return {"$obj": type(v).__name__, "state": v.__dict__}
    raise TypeError(f"not cacheable: {type(v).__name__}")


def _decode(d):
    if "$set" in d and len(d) == 1:
        return set(d["$set"])
    return d


def dumps(state: dict) -> str:
    return json.dumps(state, default=_encode, separators=(",", ":"), ensure_ascii=False)


def loads(text: str):
    return json.loads(text, object_hook=_decode)


def restore(obj, state: dict, nested: dict = None) -> None:
    """Sets obj's attributes from a dumped __dict__; `nested` maps an attribute to the class of the object it holds
    (dumped as {"$obj": ..., "state": {...}})."""
    for k, v in state.items():
        cls = (nested or {}).get(k)
        if cls is not None and isinstance(v, dict) and "$obj" in v:
            inner = cls.__new__(cls)
            inner.__dict__.update(v["state"])
            v = inner
        setattr(obj, k, v)


def anchor(path, offset) -> str:
    """A hash of the file's first ANCHOR bytes and of the ANCHOR bytes before `offset`: an append-only log keeps it, a
    file rewritten in place (same inode, any size) almost never does."""
    if not isinstance(offset, int) or offset <= 0:
        return ""
    try:
        with open(path, "rb") as fh:
            head = fh.read(min(ANCHOR, offset))
            fh.seek(max(0, offset - ANCHOR))
            tail = fh.read(min(ANCHOR, offset))
    except OSError:
        return "?"
    return hashlib.sha1(head + b"|" + tail).hexdigest()


def state_of(obj) -> dict:
    """A reader's attributes less its `path` (the row's key), with the anchor of its offset (see anchor())."""
    out = {k: v for k, v in obj.__dict__.items() if k != "path"}
    if getattr(obj, "path", None) is not None and "offset" in out:
        out["$anchor"] = anchor(obj.path, out["offset"])
    return out


def load_into(obj, state, nested: dict = None) -> bool:
    """Restores a reader from a stored state; False (and the reader untouched) when the state does not fit, or when
    the file's bytes before the stored offset are no longer the ones read (rewritten in place)."""
    if not isinstance(state, dict):
        return False
    if "offset" in state and state.get("$anchor") != anchor(getattr(obj, "path", ""), state["offset"]):
        return False
    try:
        saved = dict(obj.__dict__)
        restore(obj, {k: v for k, v in state.items() if k not in ("path", "$anchor")}, nested)
        return True
    except (TypeError, ValueError, AttributeError):
        obj.__dict__.clear()
        obj.__dict__.update(saved)
        return False


def code_signature(*modules, extra: str = "") -> str:
    """A hash of the files that decide what a cached state means (any edit or update starts a new generation) and of
    `extra` (settings that change what is read, such as the scan cap)."""
    h = hashlib.sha1(f"{SCHEMA}|{extra}".encode())
    for m in modules:
        try:
            with open(m, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(f"{m}:?".encode())
    return h.hexdigest()[:20]


class Store:
    """get/put by (kind, key) within the code's generation (`signature`): every row carries the generation that wrote
    it and a reader sees only its own, so an older process still running beside an updated one never hands its states
    to the new code. Puts are buffered and written by flush() in one transaction."""

    def __init__(self, path, signature: str):
        self.path, self.signature = Path(path), signature
        self.db = None
        self.pending = {}
        self.enabled = os.environ.get("AGENT_TOP_CACHE", "1") != "0"
        self.opened = False

    def _open(self):
        if self.opened:
            return self.db
        self.opened = True
        if not self.enabled:
            return None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(self.path), timeout=BUSY_MS / 1000, isolation_level=None)
            db.execute(f"PRAGMA busy_timeout={BUSY_MS}")
            db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS reader (gen TEXT, kind TEXT, key TEXT, at REAL, state TEXT, "
                       "PRIMARY KEY (gen, kind, key))")
            self.db = db
        except (sqlite3.Error, OSError):
            self.db = None
        return self.db

    def get(self, kind: str, key: str):
        db = self._open()
        if db is None:
            return None
        try:
            row = db.execute("SELECT state FROM reader WHERE gen = ? AND kind = ? AND key = ?",
                             (self.signature, kind, key)).fetchone()
            return loads(row[0]) if row else None
        except (sqlite3.Error, ValueError):
            return None

    def put(self, kind: str, key: str, state) -> None:
        """`state`: a dict, or a reader object, dumped now (state_of): its offset, the facts read up to it and the
        anchor of the bytes just read are taken together, right after the read, whatever happens before the flush."""
        if self.enabled:
            self.pending[(kind, key)] = state if isinstance(state, dict) else dumps(state_of(state))

    def flush(self) -> None:
        if not self.pending:
            return
        db = self._open()
        pending, self.pending = self.pending, {}
        if db is None:
            return
        now = time.time()
        try:
            rows = [(self.signature, k, key, now, st if isinstance(st, str) else dumps(st)) for (k, key), st in pending.items()]
            db.execute("BEGIN IMMEDIATE")
            db.executemany("INSERT OR REPLACE INTO reader VALUES (?, ?, ?, ?, ?)", rows)
            last = db.execute("SELECT v FROM meta WHERE k = 'pruned'").fetchone()
            if not last or now - float(last[0]) > 86400:
                # rows not written for PRUNE_S, and those of other generations not written for a day
                db.execute("DELETE FROM reader WHERE at < ? OR (gen != ? AND at < ?)", (now - PRUNE_S, self.signature, now - 86400))
                db.execute("INSERT OR REPLACE INTO meta VALUES ('pruned', ?)", (str(now),))
            db.execute("COMMIT")
        except (sqlite3.Error, TypeError, ValueError):
            try:
                db.execute("ROLLBACK")
            except sqlite3.Error:
                pass

    def close(self) -> None:
        self.flush()
        if self.db is not None:
            try:
                self.db.close()
            except sqlite3.Error:
                pass
            self.db = None


class Null(Store):
    """A store that keeps nothing (the default of readers used outside agent-top)."""

    def __init__(self):
        super().__init__(os.devnull, "")
        self.enabled = False
