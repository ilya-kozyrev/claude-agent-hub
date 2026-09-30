#!/usr/bin/env python3
"""Builds a synthetic hub home for the README screenshots (docs/render_demo.sh). Nothing here is real data.

  make_demo_home.py ROOT LIVE_PID SID_BUILDER SID_REVIEWER

LIVE_PID is a sleeper whose command line holds both session ids, so `agent-top` sees those two agents as alive.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

root, live_pid, sid_b, sid_r = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
os.environ["AGENT_HUB_HOME"] = str(root)
os.environ.pop("AGENT_BOARD_FILE", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin"))
import hubcore as hc  # noqa: E402

NOW = time.time()
p = subprocess.Popen(["true"])
p.wait()
DEAD = p.pid
STAGE = "stage-a"


def iso(off):
    return dt.datetime.fromtimestamp(NOW + off, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ev(e):
    return json.dumps(e, separators=(",", ":")) + "\n"


def init(sid):
    return ev({"type": "system", "subtype": "init", "session_id": sid})


def say(mid, msg, off, sid, ctx=60000):
    return ev({"type": "assistant", "message": {"id": mid, "content": [{"type": "text", "text": msg}],
               "usage": {"input_tokens": 3, "cache_read_input_tokens": ctx, "cache_creation_input_tokens": 1500}},
               "parent_tool_use_id": None, "session_id": sid, "timestamp": iso(off)})


def tool(mid, tid, name, inp, off, sid):
    return ev({"type": "assistant", "message": {"id": mid, "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]},
               "parent_tool_use_id": None, "session_id": sid, "timestamp": iso(off)})


def done_tool(tid, out, sid):
    return ev({"type": "user", "message": {"role": "user", "content": [{"tool_use_id": tid, "type": "tool_result", "content": out}]},
               "parent_tool_use_id": None, "session_id": sid})


def result(sid, cost, msg, err=False, subtype="success", turns=12):
    return ev({"type": "result", "subtype": subtype, "is_error": err, "num_turns": turns, "result": msg,
               "total_cost_usd": cost, "session_id": sid})


def agent(name, log, *, sid, pid=DEAD, model, mtime_off=0, title, unread=None):
    d = root / STAGE / "agents" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "log.jsonl").write_text(log, encoding="utf-8")
    os.utime(d / "log.jsonl", (NOW + mtime_off, NOW + mtime_off))
    (d / "brief.md").write_text(f"# Brief: {title}\n\nSee the task in the title. Finish with DONE and a report path.\n", encoding="utf-8")
    (d / "inbox.md").write_text(f"# Inbox of agent {name}\n\n", encoding="utf-8")
    meta = {"role": name, "tag": f"hub-3-{name}", "stage": STAGE, "session_id": sid, "model": model, "effort": "high",
            "cwd": "/work/webapp", "dir": str(d), "brief": str(d / "brief.md"), "title": title,
            "report": str(root / STAGE / "coordinator" / "work" / f"hub-3-{name}-REPORT.md"),
            "started_at": dt.datetime.fromtimestamp(NOW - 3000, hc.TZ).isoformat(timespec="seconds"),
            "runs": [{"pid": pid, "at": dt.datetime.fromtimestamp(NOW - 3000, hc.TZ).isoformat(timespec="seconds"), "kind": "spawn"}],
            "pid": pid}
    if unread:
        meta["inbox_unread"] = unread
    (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


limits = ev({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {
    "five_hour": {"utilization": 0.34, "resetsAt": NOW + 7200}, "seven_day": {"utilization": 0.52, "resetsAt": NOW + 3 * 86400}}}})
b_head = (init(sid_b) + say("b1", "Reading the brief: rebase the payments branch and get CI green", -2900, sid_b)
          + tool("b2", "t1", "Bash", {"command": "git rebase origin/main", "description": "rebase on main"}, -2800, sid_b)
          + done_tool("t1", "Successfully rebased and updated refs/heads/payments.", sid_b)
          + say("b3", "Rebased cleanly; two tests fail on the new currency rounding, fixing them", -1500, sid_b)
          + tool("b4", "t2", "Edit", {"file_path": "/work/webapp/src/payments/rounding.py"}, -1400, sid_b)
          + done_tool("t2", "ok", sid_b))
b_log = (b_head + say("b5", "Rounding fixed; running the full suite before pushing", -60, sid_b, ctx=92000)
         + tool("b6", "t3", "Bash", {"command": "make test", "description": "run the full test suite"}, -42, sid_b) + limits)
agent("builder", b_log, sid=sid_b, pid=live_pid, model="claude-opus-5-5", title="Rebase payments and get CI green",
      unread=[{"at": dt.datetime.fromtimestamp(NOW - 30, hc.TZ).isoformat(timespec="seconds"),
               "msg": "after the suite, push and open the PR", "log_offset": len(b_log.encode())}])
r_log = (init(sid_r) + say("r1", "Reviewing PR #41 against the brief's criteria", -600, sid_r)
         + tool("r2", "t1", "Read", {"file_path": "/work/webapp/src/export/parquet.py"}, -20, sid_r))
agent("reviewer", r_log, sid=sid_r, pid=live_pid, model="claude-sonnet-5-5", title="Review PR #41 (export to Parquet)")
agent("docs", init("sid-docs") + say("d1", "DONE docs updated, report at work/hub-3-docs-REPORT.md", -900, "sid-docs")
      + result("sid-docs", 0.84, "DONE docs updated, report at work/hub-3-docs-REPORT.md"), sid="sid-docs",
      model="claude-sonnet-5-5", mtime_off=-880, title="Update the API docs for the export")
agent("migrator", init("sid-mig") + say("m1", "Dry-running the migration on a copy of the schema", -1300, "sid-mig")
      + result("sid-mig", 1.92, "turn limit reached", err=True, subtype="error_max_turns", turns=80), sid="sid-mig",
      model="claude-opus-5-5", mtime_off=-1200, title="Rehearse migration 0042 on a schema copy")

(root / STAGE / "roles.json").write_text(json.dumps({"version": 1, "retired": [], "sends": [], "roles": {
    "hub": {"session": "hub-session", "cli_session_id": "", "kind": "desktop", "tag": "hub-3", "title": "Hub stage-a #3"},
    "builder": {"session": sid_b, "cli_session_id": sid_b, "kind": "headless", "tag": "hub-3-builder", "pid": live_pid},
    "reviewer": {"session": sid_r, "cli_session_id": sid_r, "kind": "headless", "tag": "hub-3-reviewer", "pid": live_pid},
    "migrator": {"session": "sid-mig", "cli_session_id": "sid-mig", "kind": "headless", "tag": "hub-3-migrator", "pid": DEAD},
}}, indent=1), encoding="utf-8")
work = root / STAGE / "coordinator" / "work"
work.mkdir(parents=True, exist_ok=True)
t = dt.datetime.now(hc.TZ)
hm = lambda m: (t - dt.timedelta(minutes=m)).strftime("%H:%M")  # noqa: E731
(work / f"journal-{t.date().isoformat()}.md").write_text(
    f"- {hm(52)} [hub-3] start: \"Hub stage-a #3\" took over from \"Hub stage-a #2\"; locks: main-merge\n"
    f"- {hm(50)} [hub-3-builder] started headless agent builder (claude-opus-5-5/high)\n"
    f"- {hm(20)} [hub-3-migrator] EXIT migrator: error_max_turns, error; code 1, turns 80 — agent status migrator\n"
    f"- {hm(15)} [hub-3-docs] DONE docs updated, report at work/hub-3-docs-REPORT.md\n"
    f"- {hm(1)} [hub] @hub-3-builder after the suite, push and open the PR\n", encoding="utf-8")
subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "bin" / "ask"), "add", "--stage", STAGE,
                "--blocks", "the release", "--default", "ship with the flag off", "--due", "2000-01-01T10:00", "--by", "hub-3",
                "Turn the new export on by default?"], check=True, capture_output=True, env=dict(os.environ))
import board  # noqa: E402
board.write([{"kind": "main-merge", "repo": "webapp", "owner_name": "Hub stage-a #3", "session_id": "hub-session",
              "until": board.fmt(board.now() + dt.timedelta(days=2)), "why": "stage hub merges main", "taken_at": board.fmt(board.now())}])
print(root)
