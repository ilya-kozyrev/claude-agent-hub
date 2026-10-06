#!/usr/bin/env python3
"""Fixtures for tests/t_watchdog.sh: journal lines, transcripts, jobs and rows, stamped relative to a reference time.

The reference is $FX_NOW (an ISO time in the hub time zone, UTC in the tests) or the real clock; "N minutes ago" is
counted from it, so a test that injects the watchdog's clock (AGENT_HUB_WATCHDOG_NOW) builds the same world.

  jline STAGE MINUTES "[tag] text"        append `- HH:MM [tag] text` to the journal of that day, stamped MINUTES ago
  transcript SID MINUTES ok|error|error-user   a Claude transcript whose last turn record is a normal answer, an API
                                          error, or an API error followed by a user record; file mtime MINUTES ago
  job SID CWD                             ~/.claude/jobs/<sid8>/state.json (the daemon's saved options of a bg session)
  rows FILE [ID SID KIND STATUS CWD]      the rows `claude agents --json` prints (none when only FILE is given)
  age PATH MINUTES                        set the mtime of PATH MINUTES ago
  backdate STAGE MINUTES                  roles.json: the hub record's set_at MINUTES ago
  hubfield STAGE KEY VALUE                roles.json: a field of the hub record
  consume STAGE CALLER                    mark every journal line of the stage as seen in CALLER's jwait state
  claude-calls LOGFILE                    one line per call of the fake claude: `agents`, `stop <id>`, `resume <sid> <n args>`
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import hubcore as hc  # noqa: E402


def ref() -> dt.datetime:
    raw = os.environ.get("FX_NOW", "").strip()
    if raw:
        t = dt.datetime.fromisoformat(raw)
        return t.replace(tzinfo=hc.TZ) if t.tzinfo is None else t
    return hc.now()


def ago(minutes: float) -> dt.datetime:
    return ref() - dt.timedelta(minutes=float(minutes))


def touch_ago(path, minutes) -> None:
    t = ago(minutes).timestamp()
    os.utime(path, (t, t))


def claude_home() -> Path:
    return Path(os.environ["CLAUDE_CONFIG_DIR"])


def main(argv: list) -> int:
    cmd, args = argv[0], argv[1:]
    if cmd == "jline":
        stage, minutes, text = args
        t = ago(minutes)
        path = hc.journal_path(stage, t.date())
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"- {t:%H:%M} {text}\n")
    elif cmd == "transcript":
        sid, minutes, last = args
        path = claude_home() / "projects" / "p" / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        base = {"isSidechain": False, "cwd": os.environ.get("FX_CWD", "/tmp"), "sessionId": sid}
        stamp = lambda m: ago(m).strftime("%Y-%m-%dT%H:%M:%S.000Z")  # noqa: E731
        recs = [dict(base, type="user", timestamp=stamp(float(minutes) + 3), message={"role": "user", "content": "go"}),
                dict(base, type="assistant", timestamp=stamp(float(minutes) + 2),
                     message={"role": "assistant", "model": "claude-opus-5-5", "content": [{"type": "text", "text": "on it"}]},
                     effort="high")]
        if last in ("error", "error-user"):
            recs.append(dict(base, type="assistant", timestamp=stamp(minutes), error="rate_limit", isApiErrorMessage=True,
                             apiErrorStatus=429, message={"role": "assistant", "model": "<synthetic>",
                                                          "content": [{"type": "text", "text": "API Error"}]}))
        if last == "error-user":
            recs.append(dict(base, type="user", timestamp=stamp(float(minutes) - 1), message={"role": "user", "content": "retry"}))
        path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        touch_ago(path, float(minutes) - (1 if last == "error-user" else 0))
    elif cmd == "job":
        sid, cwd = args
        d = claude_home() / "jobs" / sid[:8]
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps({"sessionId": sid, "resumeSessionId": sid, "cwd": cwd, "state": "done",
                                                  "respawnFlags": ["--model", "opus", "--permission-mode", "auto"]}))
    elif cmd == "rows":
        rows = []
        if len(args) > 1:
            rid, sid, kind, status, cwd = args[1:]
            rows.append({"id": rid, "sessionId": sid, "kind": kind, "status": status,
                         "state": "working" if status == "busy" else "done", "pid": 4242, "cwd": cwd, "name": "hub"})
        Path(args[0]).write_text(json.dumps(rows))
    elif cmd == "age":
        touch_ago(args[0], args[1])
    elif cmd in ("backdate", "hubfield"):
        stage = args[0]
        path = hc.roles_path(stage)
        data = json.loads(path.read_text())
        if cmd == "backdate":
            data["roles"]["hub"]["set_at"] = ago(args[1]).isoformat(timespec="seconds")
        else:
            data["roles"]["hub"][args[1]] = args[2]
        path.write_text(json.dumps(data))
    elif cmd == "consume":
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("jwait_fx", str(hc.BIN / "jwait"))
        jw = importlib.util.module_from_spec(importlib.util.spec_from_loader("jwait_fx", loader))
        loader.exec_module(jw)
        stage, caller = args
        updates = {}
        for back in (0, 1):
            day = (ref() - dt.timedelta(days=back)).date()
            src = jw.Source(f"journal:{stage}:{day.isoformat()}", hc.journal_path(stage, day), "j", True)
            keys = {k for k, _ in src.poll()}
            if keys:
                updates[src.sid] = (keys, keys)
        jw.save_state(caller, updates)
    elif cmd == "claude-calls":
        for line in Path(args[0]).read_text().splitlines():
            a = json.loads(line)["argv"]
            if a[:1] == ["agents"]:
                print("agents")
            elif a[:1] == ["stop"]:
                print("stop " + a[1])
            elif "--resume" in a:
                print(f"resume {a[a.index('--resume') + 1]} {len(a) - 3} " + " ".join(a[: a.index('--resume')]))
            else:
                print("other " + " ".join(a))
    else:
        print(f"unknown fixture command {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
