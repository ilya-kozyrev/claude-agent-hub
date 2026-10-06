#!/bin/bash
# After a Claude Desktop session's CLI restarted (a new $CLAUDE_CODE_SESSION_ID under the same `local_…` id) the tools
# still know the caller (WP9): jlog, jwait and `agent send` resolve it to the registered hub's tag through the Desktop id
# in $CLAUDE_CODE_HOST_SESSION_ID — verified against Desktop's own record of that session — and refresh the registry's
# CLI id. So the hub's `agent send` echo is signed with its tag (not `[cli]`) and its own jwait ignores it, even when
# the message holds a status word. Negatives: the variable alone proves nothing (a daemon's stale one, a child's).
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME; P=$(mktemp -d); export HUB_STAGE=stage-a
export CLAUDE_SESSIONS_DIR=$P/s; mkdir -p $CLAUDE_SESSIONS_DIR/a/b
mk(){ printf '{"sessionId":"%s","cliSessionId":"%s","title":"%s"}' "$1" "$2" "$3" > $CLAUDE_SESSIONS_DIR/a/b/$1.json; }
LOCAL=local_d637d7e1-4d6c-4366-b32f-bc735e7c56d6
OLD=87f63f42-86a7-4fb2-9031-5e74de6308c4; NEW=6e15f2da-e17f-48aa-b11c-dbf2778d9021   # the CLI before and after the restart
OTHER=99999999-9999-4999-8999-999999999999; OTHER_LOCAL=local_aaaaaaaa-0000-4000-8000-000000000001
export CLAUDE_BIN=$T/fake_claude.py
W=$P/w; mkdir -p $W; echo "brief" > $W/b.md
J(){ cat "$(journal stage-a)"; }
mk $LOCAL $OLD "Hub hub-09 #1"
$B/hub start --stage stage-a --session $LOCAL > $R/start.out 2>&1; check $? 0 "setup: the hub is registered under its local_ id and CLI id"
cli_in_registry(){ python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["roles"]["hub"]["cli_session_id"])' $R/stage-a/roles.json; }
check "$(cli_in_registry)" $OLD "setup: the registry holds the old CLI id"
mk $LOCAL $NEW "Hub hub-09 #1"   # Desktop restarted the CLI: its record names the new session
restarted(){ CLAUDE_CODE_SESSION_ID=$NEW CLAUDE_CODE_HOST_SESSION_ID=$LOCAL "$@"; }
PAT=$(python3 -c "import sys; sys.path.insert(0, '$B'); import hubcore as hc; print(hc.status_pattern())")

# 1. negatives first: the registry is not touched and no tag is found
CLAUDE_CODE_SESSION_ID=$NEW $B/jlog --stage stage-a "no host id" > $P/n1.out 2>&1; check $? 2 "no host id: the restarted session is unknown (jlog: no tag)"
CLAUDE_CODE_SESSION_ID=$OTHER CLAUDE_CODE_HOST_SESSION_ID=$LOCAL $B/jlog --stage stage-a "stale host id" > $P/n2.out 2>&1; check $? 2 "a stale host id (Desktop's record names another CLI session — a daemon's, a child's): not the hub"
CLAUDE_CODE_SESSION_ID=$NEW CLAUDE_CODE_HOST_SESSION_ID=$OTHER_LOCAL $B/jlog --stage stage-a "unregistered" > $P/n3.out 2>&1; check $? 2 "a Desktop id nobody registered: unknown"
CLAUDE_CODE_SESSION_ID=$NEW CLAUDE_CODE_HOST_SESSION_ID=not-a-local-id $B/jlog --stage stage-a "not local" > $P/n4.out 2>&1; check $? 2 "a host id that is not a local_… id: ignored"
CLAUDE_SESSIONS_DIR=$P/none CLAUDE_CODE_SESSION_ID=$NEW CLAUDE_CODE_HOST_SESSION_ID=$LOCAL $B/jlog --stage stage-a "no record" > $P/n5.out 2>&1; check $? 2 "no Desktop record to verify against: unknown"
AGENT_SESSION_ID=$NEW CLAUDE_CODE_HOST_SESSION_ID=$LOCAL $B/jlog --stage stage-a "headless" > $P/n6.out 2>&1; check $? 2 "a headless agent (AGENT_SESSION_ID only) inheriting the host id: unknown"
check "$(cli_in_registry)" $OLD "none of them touched the registry"

# 2. the restarted hub is resolved by jlog and the registry follows
restarted $B/jlog --stage stage-a "after restart" > $P/p1.out 2>&1; check $? 0 "restarted: jlog finds the hub"
grep -q '\[hub-1\] after restart' $P/p1.out; check $? 0 "…and signs [hub-1]"
check "$(cli_in_registry)" $NEW "…the registry's cli_session_id is refreshed"
CLAUDE_CODE_SESSION_ID=$NEW $B/jlog --stage stage-a "first rule now" > $P/p2.out 2>&1; check $? 0 "afterwards the CLI id alone is enough (first rule)"

# 3. jwait: the hub's own lines do not wake it; another writer's do
rm -f $R/.jwait-state/*
restarted $B/jwait --journal --stage stage-a --settle 1 --for 8s --match "$PAT" --tag hub-1 --tag hub > $P/jw1.out 2>&1 & JW=$!
armed $P/jw1.out; check $? 0 "jwait armed (restarted session)"
grep -q '^jwait \[hub-1\]:' $P/jw1.out; check $? 0 "…as the caller hub-1 (not an anonymous session id)"
restarted $B/jlog --stage stage-a "hub's own line: report DONE" > /dev/null
wait $JW; check $? 3 "the hub's own DONE line does not wake it (deadline)"
restarted $B/jwait --journal --stage stage-a --settle 1 --for 20s --match "$PAT" --tag hub-1 --tag hub > $P/jw2.out 2>&1 & JW=$!
armed $P/jw2.out
$B/jlog --tag worker "DONE report at work/x.md" > /dev/null
wait $JW; check $? 0 "positive control: a worker's DONE line wakes it"
grep -q 'worker\] DONE' $P/jw2.out; check $? 0 "…on that line"

# 3b. the same jwait without the fix's input (no host id): the hub's own line wakes it — the 16:10 symptom
CLAUDE_CODE_SESSION_ID=$OTHER $B/jwait --journal --stage stage-a --caller anon --settle 1 --for 20s --match "$PAT" > $P/jw3.out 2>&1 & JW=$!
armed $P/jw3.out
$B/jlog --tag hub-1 "hub's own line: report DONE (unknown caller)" > /dev/null
wait $JW; check $? 0 "an unresolved caller is woken by the hub's own line (what the host id prevents)"

# 4. agent send from the restarted hub: the echo is signed with the hub's tag, so its own jwait ignores it
FAKE_HOLD=30 restarted $B/agent spawn --role w1 --cwd $W --model haiku --brief $W/b.md > $P/sp.out 2>&1; check $? 0 "spawn from the restarted hub"
grep -q '^- [0-9:]* \[hub-1\] started headless agent w1' "$(journal stage-a)"; check $? 0 "…the start line is the hub's too"
restarted $B/jwait --journal --stage stage-a --settle 1 --for 8s --match "$PAT" --tag hub-1 --tag hub > $P/jw4.out 2>&1 & JW=$!
armed $P/jw4.out
restarted $B/agent send w1 "when finished report DONE and BLOCKED" > $P/send.out 2>&1; check $? 0 "agent send from the restarted hub"
wait $JW; check $? 3 "the echo holding DONE and BLOCKED does not wake the hub's own jwait"
grep -q '^- [0-9:]* \[hub-1\] @w1 .*report DONE and BLOCKED' "$(journal stage-a)"; check $? 0 "…it is signed [hub-1]"
grep -q '\[cli\] @w1' "$(journal stage-a)"; check $? 1 "…and nowhere signed [cli]"
$B/agent stop w1 > /dev/null 2>&1
# 4b. positive control: from a shell that the registry does not know, the echo is [cli] and the hub's jwait wakes on it
FAKE_HOLD=20 $B/agent spawn --role w2 --cwd $W --model haiku --brief $W/b.md > /dev/null 2>&1
restarted $B/jwait --journal --stage stage-a --settle 1 --for 20s --match "$PAT" --tag hub-1 --tag hub > $P/jw5.out 2>&1 & JW=$!
armed $P/jw5.out
$B/agent send w2 "when finished report DONE" > /dev/null 2>&1
wait $JW; check $? 0 "positive control: an unknown caller's echo ([cli]) holding DONE wakes the hub's jwait"
grep -q '\[cli\] @w2 when finished report DONE' $P/jw5.out; check $? 0 "…it is the [cli] line"
$B/agent stop w2 > /dev/null 2>&1

# 5. a read-only registry still gives the tag (only the refresh is skipped)
if [ "$(id -u)" != 0 ]; then
  python3 - $R/stage-a/roles.json $OLD <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["roles"]["hub"]["cli_session_id"] = sys.argv[2]; open(sys.argv[1], "w").write(json.dumps(d))
PY
  chmod 555 $R/stage-a
  restarted $B/jlog --tag probe "ro" > /dev/null 2>&1
  restarted python3 -c "import sys; sys.path.insert(0, '$B'); import hubcore as hc; print(hc.caller_tag('stage-a'))" > $P/ro.out 2>&1
  chmod 755 $R/stage-a
  check "$(cat $P/ro.out)" hub-1 "a read-only stage directory: the tag is found, the refresh is skipped"
  check "$(cli_in_registry)" $OLD "…and the registry is unchanged"
fi
exit $fail
