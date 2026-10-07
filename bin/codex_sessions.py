"""Read-only Codex registry addressing and bounded runtime detection."""
from __future__ import annotations

import json
import os
import selectors
import shlex
import subprocess
import time

import engines
import hubcore as hc
import subagents


def detached(stage: str, rec: dict):
    """Find a current Codex worker by registered identity, including a worker promoted to hub."""
    return hc.detached(stage, rec, engine="codex")


def runtime_status(sid: str, cwd=None):
    """Query an existing daemon only; never start a server or load/resume a thread. Unknown is None."""
    proc = None
    try:
        proc = subprocess.Popen([engines.codex_bin(cwd), "app-server", "proxy"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=hc.child_env())
        with selectors.DefaultSelector() as ready:
            ready.register(proc.stdout, selectors.EVENT_READ)
            def send(message):
                proc.stdin.write(json.dumps(message).encode() + b"\n")
                proc.stdin.flush()
            send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "agent_hub", "version": "1"}}})
            deadline, pending, total = time.monotonic() + 5, b"", 0
            while time.monotonic() < deadline and total < 256_000:
                if not ready.select(max(0, deadline - time.monotonic())):
                    break
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                pending += chunk
                total += len(chunk)
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        return None
                    if message.get("id") == 1:
                        if "result" not in message:
                            return None
                        send({"method": "initialized"})
                        send({"id": 2, "method": "thread/read", "params": {
                            "threadId": sid, "includeTurns": False}})
                    elif message.get("id") == 2:
                        thread = message.get("result", {}).get("thread", {})
                        return thread.get("status", {}).get("type") if thread.get("id") == sid else None
    except (hc.Failure, hc.UsageError, OSError, subprocess.SubprocessError, ValueError, AttributeError, TypeError):
        return None
    finally:
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()  # only our proxy connection, never the daemon/thread
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
            except (OSError, subprocess.SubprocessError):
                pass
            for pipe in (proc.stdin, proc.stdout):
                try:
                    pipe.close()
                except OSError:
                    pass
    return None


def previous_warning(stage: str, rec: dict) -> str:
    """Warn only on positive runtime evidence. Failures remain silent; nothing is stopped."""
    meta = detached(stage, rec)
    sid = rec.get("cli_session_id") or rec.get("session") or ""
    pid = None
    if meta:
        table = subagents.process_table()
        # Without command identity, PID existence alone cannot exclude reuse.
        if table is None or not subagents.is_alive(meta, table):
            return ""
        pid = meta["pid"]
        stop = f"`agent stop --stage {shlex.quote(stage)} {shlex.quote(meta['role'])}`"
    elif rec.get("engine") == "codex":
        if runtime_status(sid, rec.get("cwd")) not in ("active", "idle", "systemError"):
            return ""
        stop = "close its Codex terminal/app session"
    else:
        return ""
    who = f"\"{rec.get('title') or rec.get('tag') or '?'}\" ({rec.get('tag') or 'hub'}, sid {sid[:8]}"
    who += f", pid {pid})" if pid else ")"
    return (f"the previous hub {who} still runs: other hubs can still message it and it answers — "
            f"stop it: {stop}. Nothing was stopped.")
