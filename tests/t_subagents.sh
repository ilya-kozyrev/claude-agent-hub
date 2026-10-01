#!/bin/bash
# agent-top lists the sub-agents of the sessions in a stage's role registry, read-only, from fake Claude Code
# transcripts (subagent_fixture.py): states from the parent's completion notices, a resumed one, a lost one,
# a headless parent alive or gone; negative controls — a session outside the registry, an old one without --all,
# nothing written; feed and card of a sub-agent.
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a PYTHONDONTWRITEBYTECODE=1
R=$AGENT_HUB_HOME; export CLAUDE_CONFIG_DIR=$R/cc
HUB=33333333-cccc-4ccc-8ccc-333333333333; EXE=44444444-dddd-4ddd-8ddd-444444444444; STR=55555555-eeee-4eee-8eee-555555555555
python3 $T/subagent_fixture.py $CLAUDE_CONFIG_DIR $HUB $EXE $STR > /dev/null; check $? 0 "fixture built"
# the headless parent is "alive" when its pid runs a command line holding its session id
python3 -c 'import time; time.sleep(600)' $EXE & SLEEPER=$!
trap 'kill $SLEEPER 2>/dev/null' EXIT
$B/roles set hub $HUB --kind cli --tag hub-7 > /dev/null; check $? 0 "registry: hub"
$B/roles set exec $EXE --kind headless --tag hub-7-exec --pid $SLEEPER > /dev/null; check $? 0 "registry: headless exec"
fp(){ python3 - "$R" <<'PY'
import hashlib, os, sys
out = []
for d, _, files in os.walk(sys.argv[1]):
    for f in files:
        p = os.path.join(d, f)
        if f.endswith(".lock") or f.startswith(("fp-", "st-")):
            continue
        st = os.stat(p)
        out.append(f"{p} {st.st_mtime_ns} {hashlib.sha1(open(p, 'rb').read()).hexdigest()}")
print("\n".join(sorted(out)))
PY
}
fp > $R/fp-before.txt

states(){ python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
for a in d["agents"]:
    if a.get("kind") == "subagent":
        print(a["role"], a["state"], a["effort"] or "-", (a["result"] or {}).get("subtype") or "-", a["background"])
' "$1"; }
$B/agent-top --json > $R/st-json.out 2> $R/st-json.err; check $? 0 "--json exit 0"
states $R/st-json.out > $R/st-states.txt
st(){ awk -v r="$1" '$1==r {print $2}' $R/st-states.txt; }
check "$(st hub/alive1)" live "live: written just now, no notice"
check "$(awk '$1=="hub/alive1" {print $3}' $R/st-states.txt)" high "effort read from the transcript"
check "$(st hub/done1)" done "done: completion notice after the last write"
check "$(awk '$1=="hub/done1" {print $4}' $R/st-states.txt)" completed "…result subtype is the notice status"
check "$(st hub/resumed)" live "resumed: written after its completion notice -> live again"
check "$(st hub/fail1)" error "error: notice status failed"
check "$(st hub/killed1)" dead "dead: notice status killed"
check "$(st hub/lost1)" dead "dead: no notice and silent 40 min (its parent session ended)"
check "$(st exec/orphan1)" live "headless parent alive -> its fresh sub-agent is live"
check "$(st hub/old1)" "" "negative: a finished sub-agent older than 1 h is hidden"
grep -q ghost $R/st-json.out; check $? 1 "negative: a session outside the registry is never scanned"
python3 -c '
import json, sys
a = next(a for a in json.load(open(sys.argv[1]))["agents"] if a["role"] == "hub/alive1")
assert a["action"]["tool"] == "Bash" and a["title"] == "run the tests" and a["model"] == "haiku", a
assert a["pid"] is None and a["unread"] == [] and a["ctx_tokens"] == 15903, a
d = next(a for a in json.load(open(sys.argv[1]))["agents"] if a["role"] == "hub/done1")
assert d["result"]["text"].startswith("DONE: 3 errors"), d
' $R/st-json.out; check $? 0 "fields: current action, description as task, model, context, result text"
$B/agent-top --json --all | grep -q '"role": "hub/old1"'; check $? 0 "--all shows the old one"

# the headless parent is gone: its sub-agent is dead even though the transcript is fresh
kill $SLEEPER; wait $SLEEPER 2>/dev/null
$B/agent-top --json > $R/st-json2.out; states $R/st-json2.out > $R/st-states.txt
check "$(st exec/orphan1)" dead "headless parent gone -> its sub-agent is dead"

# text views: the list row and the card with the read-only note, the feed from the transcript
$B/agent-top --once --width 140 --agent hub/done1 --lines 10 > $R/st-once.out 2>&1; check $? 0 "--once --agent on a sub-agent exit 0"
grep -q 'hub/ali.*run the tests.*live.*Bash: Run the tests' $R/st-once.out; check $? 0 "list row: role, task, state, action"
grep -q 'read-only here — only its parent' $R/st-once.out; check $? 0 "card: read-only note with the address"
grep -q 'brief of scan the logs' $R/st-once.out && grep -q '✎ DONE: 3 errors' $R/st-once.out; check $? 0 "feed: brief and last text from the transcript"
fp > $R/fp-after.txt
diff -q $R/fp-before.txt $R/fp-after.txt > /dev/null; check $? 0 "agent-top wrote nothing (hub home and transcripts)"
exit $fail
