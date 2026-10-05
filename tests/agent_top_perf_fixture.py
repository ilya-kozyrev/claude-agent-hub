#!/usr/bin/env python3
"""A large fake hub home for t_agent_top_perf.sh: the shape of a busy machine, not its exact size.

  agent_top_perf_fixture.py HUB_HOME CLAUDE_CONFIG_DIR CODEX_HOME

  10 stages x 6 headless agents, each log ~1.5 MB of assistant turns, tool calls and results (90 MB), all finished within
  the last hour (none is filtered out by age); the first agent of stage 0 is "grow1", whose log the test appends to.
  Each stage's roles.json names 4 interactive sessions; each session has a 1 MB parent transcript in
  <claude config>/projects/<proj>/<session>.jsonl with completion notices, and 4 sub-agents written in the last 20 min.
  300 more project folders with a few sessions each (what a real ~/.claude/projects holds).
  600 Codex rollouts under <codex home>/sessions/YYYY/MM/DD, each with a 20 KB session_meta header.
Prints the expected turn count of grow1 so the test can check that an appended run is counted exactly once.
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

hub, claude, codex = (Path(p) for p in sys.argv[1:4])
NOW = time.time()
STAGES, AGENTS, TURNS, SESSIONS, SUBS = 10, 6, 1500, 4, 4
PAD = "x" * 600


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def line(ev):
    return json.dumps(ev, separators=(",", ":")) + "\n"


def headless_log(sid, turns, t0, prefix):
    out = [line({"type": "system", "subtype": "init", "session_id": sid, "model": "claude-opus-5-5"})]
    for i in range(turns):
        mid, tid = f"{prefix}m{i}", f"{prefix}t{i}"
        out.append(line({"type": "assistant", "message": {"id": mid, "content": [{"type": "text", "text": f"step {i} {PAD}"}],
                                                          "usage": {"input_tokens": 3, "cache_read_input_tokens": 40000 + i}},
                         "parent_tool_use_id": None, "session_id": sid, "timestamp": iso(t0 + i)}))
        if i % 3 == 0:
            out.append(line({"type": "assistant", "message": {"id": mid, "content": [
                {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": f"echo {i}", "description": "step"}}]},
                "parent_tool_use_id": None, "session_id": sid, "timestamp": iso(t0 + i)}))
            out.append(line({"type": "user", "message": {"role": "user", "content": [
                {"tool_use_id": tid, "type": "tool_result", "content": f"ok {i} {PAD}", "is_error": False}]},
                "parent_tool_use_id": None, "session_id": sid}))
    out.append(line({"duration_api_ms": 1, "type": "result", "subtype": "success", "is_error": False, "num_turns": turns,
                     "result": "DONE", "total_cost_usd": 1.5, "session_id": sid}))
    return "".join(out)


def transcript_line(kind, sid, t, **kw):
    return json.dumps({"parentUuid": None, "type": kind, "sessionId": sid, "timestamp": iso(t), **kw}, separators=(",", ":")) + "\n"


# ---- the hub home: stages, headless agents, registries with interactive sessions
proj_root = claude / "projects"
for s in range(STAGES):
    stage = f"perf-{s:02d}"
    roles = {}
    for a in range(AGENTS):
        name = "grow1" if (s, a) == (0, 0) else f"w{a}"
        d = hub / stage / "agents" / name
        d.mkdir(parents=True, exist_ok=True)
        sid = str(uuid.uuid4())
        (d / "log.jsonl").write_text(headless_log(sid, TURNS, NOW - 3000, f"{s}{a}"), encoding="utf-8")
        os.utime(d / "log.jsonl", (NOW - 600, NOW - 600))
        (d / "meta.json").write_text(json.dumps({"role": name, "tag": f"{name}-{s}", "stage": stage, "session_id": sid,
                                                 "model": "opus", "effort": "high", "pid": 0, "runs": [{"pid": 0}],
                                                 "title": f"perf agent {name}"}), encoding="utf-8")
        roles[name] = {"session": sid, "kind": "headless", "tag": f"{name}-{s}", "pid": 0}
    proj = proj_root / f"-work-{stage}"
    for k in range(SESSIONS):
        sid = str(uuid.uuid4())
        roles[f"chat{k}"] = {"session": sid, "cli_session_id": sid, "kind": "desktop", "tag": f"chat{k}-{s}"}
        sub_dir = proj / sid / "subagents"
        sub_dir.mkdir(parents=True, exist_ok=True)
        parent = []
        for j in range(1400):
            parent.append(transcript_line("assistant", sid, NOW - 4000 + j, message={"id": f"p{j}", "role": "assistant",
                                          "content": [{"type": "text", "text": f"parent turn {j} {PAD}"}]}))
        for j in range(SUBS):
            aid = f"a{s}{k}{j}" + "0" * 12
            (sub_dir / f"agent-{aid}.meta.json").write_text(json.dumps({"agentType": "general-purpose", "description": f"sub {j}",
                                                                        "toolUseId": f"toolu_{aid}", "requestShape": "background"}))
            log = "".join(transcript_line("assistant", sid, NOW - 1200 + i, message={"id": f"s{aid}{i}", "role": "assistant",
                                          "content": [{"type": "text", "text": f"sub step {i} {PAD}"}]}) for i in range(150))
            (sub_dir / f"agent-{aid}.jsonl").write_text(log, encoding="utf-8")
            if j % 2 == 0:
                note = f"<task-notification><task-id>{aid}</task-id><status>completed</status></task-notification>"
                parent.append(transcript_line("queue-operation", sid, NOW - 1000, operation="enqueue", content=note))
        (proj / f"{sid}.jsonl").write_text("".join(parent), encoding="utf-8")
    (hub / stage / "roles.json").write_text(json.dumps({"version": 1, "roles": roles}), encoding="utf-8")

for p in range(300):
    d = proj_root / f"-elsewhere-{p:03d}"
    d.mkdir(parents=True, exist_ok=True)
    for k in range(4):
        sid = str(uuid.uuid4())
        (d / f"{sid}.jsonl").write_text(transcript_line("user", sid, NOW - 86400, message={"role": "user", "content": "hi"}))
        (d / sid).mkdir()

# ---- the Codex home: rollouts with a large session_meta header (base instructions), none of them a hub session's
instructions = {"text": "You are Codex. " * 1400}
for r in range(600):
    day = codex / "sessions" / "2026" / "10" / f"{1 + r % 5:02d}"
    day.mkdir(parents=True, exist_ok=True)
    rid = str(uuid.uuid4())
    head = {"type": "session_meta", "timestamp": iso(NOW - 86400), "payload": {
        "id": rid, "timestamp": iso(NOW - 86400), "cwd": "/work", "originator": "codex_exec", "cli_version": "0.1",
        "source": "exec", "base_instructions": instructions}}
    body = "".join(line({"type": "event_msg", "timestamp": iso(NOW - 86000), "payload": {"type": "agent_message", "message": f"m{i}"}})
                   for i in range(20))
    (day / f"rollout-2026-10-0{1 + r % 5}T00-00-00-{rid}.jsonl").write_text(line(head) + body, encoding="utf-8")

print(TURNS)
