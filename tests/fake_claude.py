#!/usr/bin/env python3
"""Stand-in for `claude -p` in the agent-* tests (CLAUDE_BIN=<this>).

FAKE_CLAUDE=ok (default): init event, FAKE_HOLD seconds of work, one assistant line, result.
FAKE_CLAUDE=die: no init, exits 1 after 2 s (a CLI that rejects its flags slowly).
FAKE_CLAUDE=hang: alive for 60 s without an init event.
FAKE_READ_INBOX=1: a Bash tool call on inbox.md after the hold; FAKE_FINAL=<text>: the last answer.
Every prompt is appended to ./prompts.log, every argv (minus the prompt) to ./argv.log and the environment the
plugin sets for the CLI to ./env.log, so a test can see what the agent was told, with which flags and settings.
"""
import json, os, sys, time

argv = sys.argv[1:]
def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None

sid = opt("--session-id") or opt("--resume")
prompt = opt("-p") or ""
with open("prompts.log", "a", encoding="utf-8") as fh:
    fh.write(prompt + "\n=====\n")
with open("argv.log", "a", encoding="utf-8") as fh:
    fh.write(" ".join(a for a in argv if a != prompt) + "\n")
with open("env.log", "a", encoding="utf-8") as fh:
    fh.write(f"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS={os.environ.get('CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS', '<unset>')}\n")
if os.environ.get("FAKE_CLAUDE") == "hang":  # alive, never sends init (a slow MCP server, a stuck start)
    time.sleep(60)
    sys.exit(0)
if os.environ.get("FAKE_CLAUDE") == "die":
    time.sleep(2)
    sys.stderr.write("error: unknown option '--effort'\n")
    sys.exit(1)
def emit(ev):
    sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n"); sys.stdout.flush()
emit({"type": "system", "subtype": "init", "session_id": sid})
time.sleep(float(os.environ.get("FAKE_HOLD", "0")))
if os.environ.get("FAKE_READ_INBOX"):
    emit({"type": "assistant", "message": {"id": "mr", "content": [{"type": "tool_use", "name": "Bash",
          "input": {"command": "cat /x/agents/r/inbox.md"}}]}, "session_id": sid})
last = [l for l in prompt.splitlines() if l.strip()][-1] if prompt.strip() else ""
final = os.environ.get("FAKE_FINAL") or ("echo: " + last[:80])
emit({"type": "assistant", "message": {"id": f"m{time.time()}", "content": [{"type": "text", "text": final}]}, "session_id": sid})
emit({"type": "result", "subtype": "success", "num_turns": 1, "session_id": sid, "is_error": False, "result": final})
