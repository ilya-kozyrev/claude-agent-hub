#!/usr/bin/env python3
"""Stand-in for `claude -p` in the agent-* tests (CLAUDE_BIN=<this>).

FAKE_CLAUDE=ok (default): init event, FAKE_HOLD seconds of work, one assistant line, result.
FAKE_CLAUDE=die: no init, exits 1 after 2 s (a CLI that rejects its flags slowly).
FAKE_CLAUDE=hang: alive for 60 s without an init event.
FAKE_READ_INBOX=1: a Bash tool call on inbox.md after the hold; FAKE_FINAL=<text>: the last answer.
FAKE_TURNS=<n>: n extra assistant messages (distinct ids) before the last answer.
`--version` prints FAKE_VERSION (default 2.1.285) like the real CLI and exits, leaving no log: FAKE_VERSION_BANNER
is printed on a line before it (a version manager's shim), FAKE_VERSION_LOG is a file that gets one line per call.
The init event carries
`model`: FAKE_MODEL, else the --model value with an alias resolved the way a current CLI does (sonnet -> claude-sonnet-5-5).
Every prompt is appended to ./prompts.log, every argv (minus the prompt) to ./argv.log and the environment the
plugin sets for the CLI (the first PATH entry, HUB_BIN, the background-wait ceiling and the hub home) to ./env.log, so a test can see what the
agent was told, with which flags and settings.
"""
import json, os, sys, time

argv = sys.argv[1:]
if argv == ["--version"]:
    if os.environ.get("FAKE_VERSION_LOG"):
        with open(os.environ["FAKE_VERSION_LOG"], "a", encoding="utf-8") as fh:
            fh.write("called\n")
    if os.environ.get("FAKE_VERSION_BANNER"):
        print(os.environ["FAKE_VERSION_BANNER"])
    print(os.environ.get("FAKE_VERSION", "2.1.285") + " (Claude Code)")
    sys.exit(0)
def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None

sid = opt("--session-id") or opt("--resume")
prompt = opt("-p") or ""
with open("prompts.log", "a", encoding="utf-8") as fh:
    fh.write(prompt + "\n=====\n")
with open("argv.log", "a", encoding="utf-8") as fh:
    fh.write(" ".join(a for a in argv if a != prompt) + "\n")
with open("env.log", "a", encoding="utf-8") as fh:
    fh.write(f"PATH_FIRST={os.environ.get('PATH', '').split(os.pathsep)[0]}\n")
    fh.write(f"HUB_BIN={os.environ.get('HUB_BIN', '<unset>')}\n")
    fh.write(f"AGENT_HUB_HOME={os.environ.get('AGENT_HUB_HOME', '<unset>')}\n")
    fh.write(f"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS={os.environ.get('CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS', '<unset>')}\n")  # last: tests read it with tail -1
if os.environ.get("FAKE_CLAUDE") == "hang":  # alive, never sends init (a slow MCP server, a stuck start)
    time.sleep(60)
    sys.exit(0)
if os.environ.get("FAKE_CLAUDE") == "die":
    time.sleep(2)
    sys.stderr.write("error: unknown option '--effort'\n")
    sys.exit(1)
def emit(ev):
    sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n"); sys.stdout.flush()
ALIASES = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-4-5-20251001",
           "fable": "claude-fable-5-1"}
model = os.environ.get("FAKE_MODEL") or ALIASES.get(opt("--model") or "", opt("--model"))
emit({"type": "system", "subtype": "init", "session_id": sid, "model": model})
time.sleep(float(os.environ.get("FAKE_HOLD", "0")))
if os.environ.get("FAKE_READ_INBOX"):
    emit({"type": "assistant", "message": {"id": "mr", "content": [{"type": "tool_use", "name": "Bash",
          "input": {"command": "cat /x/agents/r/inbox.md"}}]}, "session_id": sid})
for i in range(int(os.environ.get("FAKE_TURNS", "0"))):
    emit({"type": "assistant", "message": {"id": f"t{i}-{time.time()}", "content": [{"type": "text", "text": f"step {i}"}]},
          "session_id": sid})
last = [l for l in prompt.splitlines() if l.strip()][-1] if prompt.strip() else ""
final = os.environ.get("FAKE_FINAL") or ("echo: " + last[:80])
emit({"type": "assistant", "message": {"id": f"m{time.time()}", "content": [{"type": "text", "text": final}]}, "session_id": sid})
emit({"type": "result", "subtype": "success", "num_turns": 1, "session_id": sid, "is_error": False, "result": final})
