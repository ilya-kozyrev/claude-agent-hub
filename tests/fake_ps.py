#!/usr/bin/env python3
"""Stand-in for ps(1) in the effort tests (tests/lib.sh fake_ps). The process table is $FAKE_PS_TABLE, one process per
line: "pid ppid command…". `ps -o ppid=,command= -p PID` prints "<ppid> <command>"; a pid that is not in the table
answers with the row of `*`, the first hop up from the caller. `ps -axo pid=,command=` prints "<pid> <command>"."""
import os
import sys

rows = []
try:
    for line in open(os.environ.get("FAKE_PS_TABLE", "")):
        parts = line.rstrip("\n").split(None, 2)
        if len(parts) >= 2:
            rows.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
except OSError:
    pass
argv = sys.argv[1:]
if "-p" in argv:
    pid = argv[argv.index("-p") + 1]
    by_pid = {r[0]: r for r in rows}
    row = by_pid.get(pid) or by_pid.get("*")
    if row:
        print(f"{row[1]} {row[2]}")
else:
    for pid, _, cmd in rows:
        if pid != "*":
            print(f"{pid} {cmd}")
