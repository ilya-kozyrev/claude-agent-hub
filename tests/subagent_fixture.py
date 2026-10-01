#!/usr/bin/env python3
"""Fake Claude Code session transcripts with sub-agents for t_subagents.sh.

  subagent_fixture.py <claude config dir> <hub session> <exec session> <stranger session>

Writes <config>/projects/-w-proj/<session>.jsonl (the parent transcript with completion notices) and
<config>/projects/-w-proj/<session>/subagents/agent-<id>.jsonl + .meta.json, in the shapes Claude Code 2.1 writes:
a transcript line starts with "parentUuid" and its own "type" key comes after the nested message.
Sub-agents of the hub session:
  alive1   background, written just now, a Bash call with no result yet, effort high  -> live, action shown
  done1    notice "completed" just after its last write                                -> done, result = last text
  resumed1 notice "completed" 10 min ago, written again just now                       -> live (resumed by SendMessage)
  fail1    notice "failed"                                                              -> error
  killed1  notice "killed"                                                              -> dead
  lost1    no notice, silent for 40 min                                                 -> dead (parent session ended)
  old1     notice "completed", 2 h ago                                                  -> hidden without --all
of the exec session (a headless agent): orphan1, no notice, written just now -> live if exec is alive, else dead;
of the stranger session (not in any registry): ghost1 -> never listed.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

root, hub, exe, stranger = sys.argv[1:5]
proj = os.path.join(root, "projects", "-w-proj")
now = time.time()


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(t * 1000) % 1000:03d}Z"


def line(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False) + "\n"


def subagent(session: str, aid: str, desc: str, at: float, pending_tool: bool = False, effort=None, text="all good"):
    d = os.path.join(proj, session, "subagents")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"agent-{aid}.meta.json"), "w") as fh:
        json.dump({"agentType": "general-purpose", "description": desc, "toolUseId": f"toolu_{aid}", "spawnDepth": 1,
                   "requestShape": "background", "model": "haiku"}, fh)
    rows = [line(parentUuid=None, isSidechain=True, agentId=aid, type="user",
                 message={"role": "user", "content": f"brief of {desc}"}, uuid="u1", timestamp=iso(at - 60)),
            line(parentUuid="u1", isSidechain=True, agentId=aid, type="attachment", attachment={"type": "date"},
                 uuid="a1", timestamp=iso(at - 59))]
    extra = {"effort": effort} if effort else {}
    if pending_tool:
        rows.append(line(parentUuid="a1", isSidechain=True, agentId=aid,
                         message={"id": f"m-{aid}-1", "role": "assistant", "model": "claude-haiku-4-5",
                                  "content": [{"type": "tool_use", "id": f"tu-{aid}", "name": "Bash",
                                               "input": {"command": "make test", "description": "Run the tests"}}],
                                  "usage": {"input_tokens": 3, "cache_read_input_tokens": 15000,
                                            "cache_creation_input_tokens": 900}},
                         type="assistant", uuid="as1", timestamp=iso(at), **extra))
    else:
        rows.append(line(parentUuid="a1", isSidechain=True, agentId=aid,
                         message={"id": f"m-{aid}-1", "role": "assistant", "model": "claude-haiku-4-5",
                                  "content": [{"type": "text", "text": text}],
                                  "usage": {"input_tokens": 3, "cache_read_input_tokens": 15000}},
                         type="assistant", uuid="as1", timestamp=iso(at), **extra))
    p = os.path.join(d, f"agent-{aid}.jsonl")
    with open(p, "w") as fh:
        fh.writelines(rows)
    os.utime(p, (at, at))


def notice(aid: str, status: str, at: float) -> str:
    body = (f"<task-notification>\n<task-id>{aid}</task-id>\n<tool-use-id>toolu_{aid}</tool-use-id>\n"
            f"<status>{status}</status>\n<summary>Agent finished</summary>\n</task-notification>")
    return line(parentUuid="p0", isSidechain=False, type="user", message={"role": "user", "content": body},
                uuid=f"n-{aid}-{int(at)}", timestamp=iso(at))


subagent(hub, "alive1", "run the tests", now - 5, pending_tool=True, effort="high")
subagent(hub, "done1", "scan the logs", now - 120, text="DONE: 3 errors found, report /tmp/r.md")
subagent(hub, "resumed1", "second pass", now - 3)
subagent(hub, "fail1", "broken probe", now - 300)
subagent(hub, "killed1", "stopped probe", now - 300)
subagent(hub, "lost1", "lost probe", now - 2400)
subagent(hub, "old1", "yesterday's probe", now - 7200)
with open(os.path.join(proj, f"{hub}.jsonl"), "w") as fh:
    fh.write(line(parentUuid=None, isSidechain=False, type="user", message={"role": "user", "content": "hello"},
                  uuid="p0", timestamp=iso(now - 9000)))
    fh.write(notice("old1", "completed", now - 7200 + 0.05))
    fh.write(notice("resumed1", "completed", now - 600))
    fh.write(notice("fail1", "failed", now - 300 + 0.05))
    fh.write(notice("killed1", "killed", now - 300 + 0.05))
    fh.write(notice("done1", "completed", now - 120 + 0.05))
subagent(exe, "orphan1", "exec helper", now - 5)
with open(os.path.join(proj, f"{exe}.jsonl"), "w") as fh:
    fh.write(line(parentUuid=None, isSidechain=False, type="user", message={"role": "user", "content": "go"},
                  uuid="e0", timestamp=iso(now - 100)))
subagent(stranger, "ghost1", "not ours", now - 5)
print("ok")
