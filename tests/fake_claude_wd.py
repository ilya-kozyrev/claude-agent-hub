#!/usr/bin/env python3
"""Stand-in for the `claude` CLI in the watchdog tests (CLAUDE_BIN=<this>): `--version`, `agents --json`, `stop`,
`--bg --resume`; a `-p` run (the headless hub that `agent send` resumes) is handed to fake_claude.py.
Never starts anything: every call is appended as one JSON line to $FAKE_WD_LOG (argv, cwd).

$FAKE_WD_ROWS (a JSON file, default none)  the rows `agents --json` prints; `stop` removes a row, a resume adds one
FAKE_WD_AGENTS=fail                        `agents --json` exits 1
FAKE_WD_STOP=fail                          `stop` exits 1
FAKE_WD_RESUME=fail                        `--bg --resume` exits 1 ("Error: resume failed")
FAKE_WD_RESUME=copy                        `--bg --resume` always starts a copy (a new row, a different session id)
default                                    behaves like the real CLI (2.1.289, probed): a session that is still listed, or
                                           a call with any flag besides the prompt, starts a copy; otherwise the same id
                                           continues and a row for it appears
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
argv = sys.argv[1:]
if argv == ["--version"]:
    print("2.1.289 (Claude Code)")
    sys.exit(0)
if "-p" in argv:
    os.execv(sys.executable, [sys.executable, os.path.join(HERE, "fake_claude.py")] + argv)
with open(os.environ.get("FAKE_WD_LOG", "wd-claude.log"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv, "cwd": os.path.realpath(os.getcwd())}) + "\n")
rows_file = os.environ.get("FAKE_WD_ROWS")


def rows():
    try:
        return json.load(open(rows_file))
    except (OSError, TypeError, ValueError):
        return []


def save(r):
    if rows_file:
        json.dump(r, open(rows_file, "w"))


cmd = argv[0] if argv else ""
if cmd == "agents":
    if os.environ.get("FAKE_WD_AGENTS") == "fail":
        sys.stderr.write("fake claude: agents failed\n")
        sys.exit(1)
    print(json.dumps(rows()))
elif cmd == "stop":
    if os.environ.get("FAKE_WD_STOP") == "fail":
        sys.stderr.write("fake claude: stop failed\n")
        sys.exit(1)
    target = argv[1] if len(argv) > 1 else ""
    save([r for r in rows() if target not in (r.get("id"), r.get("sessionId"))])
    print(f"stopped {target}")
elif cmd == "--bg" and "--resume" in argv:
    sid = argv[argv.index("--resume") + 1]
    rest = [a for a in argv[1:] if a not in ("--resume", sid)]
    flags = [a for a in rest if a.startswith("-")]
    listed = any(sid in (r.get("sessionId"), r.get("id")) for r in rows())
    mode = os.environ.get("FAKE_WD_RESUME", "")
    if mode == "fail":
        sys.stderr.write("Error: resume failed\n")
        sys.exit(1)
    if mode == "copy" or listed or flags:
        new = "cc" + sid[2:8]
        why = (f"session {sid[:8]} is already running in the background, so this started a copy as {new}." if listed
               else f"background session {sid[:8]} keeps its own saved options, so the flags you passed started a copy as {new}.")
        save(rows() + [{"id": new, "sessionId": new + "-0000-4000-8000-000000000000", "kind": "background",
                        "status": "idle", "state": "done", "pid": 1, "cwd": os.getcwd(), "name": "copy"}])
        print(f"note: {why}\nbackgrounded · {new}")
    else:
        save(rows() + [{"id": sid[:8], "sessionId": sid, "kind": "background", "status": "idle", "state": "done",
                        "pid": 1, "cwd": os.getcwd(), "name": "hub"}])
        print(f"note: woke session {sid[:8]} with its saved options (--remote-control, --model, --permission-mode).\n"
              f"backgrounded · {sid[:8]}")
else:
    sys.stderr.write(f"fake claude: unexpected call {argv}\n")
    sys.exit(1)
