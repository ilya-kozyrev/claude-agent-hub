#!/bin/bash
# `hub start` / `hub takeover` and the main-merge lock: AGENT_HUB_TAKE_MAIN_MERGE=true takes only a free lock or one held
# by an earlier hub of the SAME stage (takeover); a lock held by a hub of another stage, and any held lock on `start`,
# is left alone with the hint; an explicit --take-main-merge takes it and names the holder's stage and the age of its
# latest journal line; --skip-lock works on `start`. Positive and negative controls for each.
. "$(dirname "$0")/lib.sh"
P=$(mktemp -d); REPO=$P/webapp
mkdir -p $REPO/.git $REPO/.agent-hub
printf '{"AGENT_HUB_DEFAULT_REPO": "webapp", "AGENT_HUB_TAKE_MAIN_MERGE": "true"}\n' > $REPO/.agent-hub/config.json
export CLAUDE_SESSIONS_DIR=$P/sessions; mkdir -p $CLAUDE_SESSIONS_DIR
PREV=34343434-3434-4343-8343-343434343434      # stage-a's current hub
OLDER=cccccccc-6666-4666-8666-666666666666     # an earlier hub of stage-a (retired)
OTHER=99999999-9999-4999-8999-999999999999     # hub of stage-b, the live merger
STRANGER=55555555-5555-4555-8555-555555555555  # registered nowhere
NEW=eeeeeeee-7777-4777-8777-777777777777
roles(){ python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, sys
path, sid, tag, retired = sys.argv[1:]
rec = {"session": sid, "cli_session_id": sid, "kind": "cli", "tag": tag, "title": tag}
data = {"version": 1, "roles": {"hub": rec} if sid else {}, "retired": [], "sends": []}
if retired:
    data["retired"].append(dict(rec, session=retired, cli_session_id=retired, role="hub", tag="hub-3", retired_at="2026-09-01T10:00:00+00:00", retired_why="replaced"))
json.dump(data, open(path, "w"))
PY
}
# setup <holder session|none> [until]: a home with stage-a (hub PREV, retired hub OLDER) and stage-b (hub OTHER, which
# wrote a journal line 7 minutes ago); the webapp main-merge held by <holder>
setup(){
  new_home; R=$AGENT_HUB_HOME; mkdir -p $R/stage-a/coordinator/work $R/stage-b/coordinator/work
  roles $R/stage-a/roles.json $PREV hub-4 $OLDER; roles $R/stage-b/roles.json $OTHER hub-33 ""
  printf -- '- %s [hub-33] merging !703\n' "$(utc_hhmm -7)" > $(journal stage-b)
  python3 - "$R/board.md" "$1" "${2:-2099-12-31T23:59:00+00:00}" <<'PY'
import json, sys
path, holder, until = sys.argv[1:]
rows = [] if holder == "none" else [{"kind": "main-merge", "repo": "webapp", "owner_name": "Hub core-c #33", "session_id": holder,
        "until": until, "why": "merge queue", "taken_at": "2026-09-29T14:00:00+00:00"}]
open(path, "w").write("# b\n\n```locks\n" + "\n".join(json.dumps(r) for r in rows) + "\n```\n")
PY
}
holder(){ python3 - "$R/board.md" <<'PY'
import json, re, sys
t = open(sys.argv[1]).read()
rows = [json.loads(l) for l in re.search(r"```locks\n(.*?)```", t, re.S).group(1).splitlines() if l.strip()]
print(next((r["session_id"] for r in rows if r["kind"] == "main-merge" and r["repo"] == "webapp"), "-"))
PY
}
start(){ (cd $REPO && $B/hub start --stage stage-c --session $NEW "$@"); }
takeover(){ (cd $REPO && $B/hub takeover --stage stage-a --n 5 --session $NEW "$@"); }

# ---- start: the config flag never takes a held lock
setup $OTHER; start > $P/s1.out 2>&1; check $? 0 "start with the config flag, main-merge held by another stage's hub"
check "$(holder)" $OTHER "…the lock stays with its holder"
grep -q 'main-merge (webapp) is held by Hub core-c #33.*left alone; take it with --take-main-merge' $P/s1.out; check $? 0 "…and the hint says how to take it"
setup $STRANGER; start > $P/s1b.out 2>&1
check "$(holder)" $STRANGER "…a holder registered nowhere is left alone too"
setup none; start > $P/s2.out 2>&1
check "$(holder)" $NEW "start with the config flag, free lock: taken (positive control)"
setup $OTHER 2020-01-01T00:00:00+00:00; start > $P/s2b.out 2>&1
check "$(holder)" $NEW "start with the config flag, expired lock: taken"
setup none; start --skip-lock main-merge > $P/s3.out 2>&1; check $? 0 "start --skip-lock main-merge is accepted"
check "$(holder)" "-" "…and leaves main-merge alone"
# ---- start: an explicit flag takes it and says whose it was
setup $OTHER; start --take-main-merge > $P/s4.out 2>&1
check "$(holder)" $NEW "start --take-main-merge takes the lock"
grep -q 'ATTENTION: main-merge (webapp) is taken from Hub core-c #33 .* of stage stage-b: its latest journal line is 7 min old' $P/s4.out; check $? 0 "…with an ATTENTION naming the holder's stage and the age of its latest journal line"
setup $STRANGER; start --take-main-merge > $P/s5.out 2>&1
grep -q 'ATTENTION: main-merge (webapp) is taken from .* of stage unknown: no journal line' $P/s5.out; check $? 0 "…a holder of no stage: stage unknown, no journal line"
setup $OTHER; rm $(journal stage-b); start --take-main-merge > $P/s5b.out 2>&1
grep -q 'of stage stage-b: no journal line' $P/s5b.out; check $? 0 "…a stage with no journal line says so"

# ---- takeover: the config flag takes only what an earlier hub of this stage holds
setup $OLDER; takeover > $P/t1.out 2>&1; check $? 0 "takeover with the config flag, main-merge held by an earlier hub of the stage"
check "$(holder)" $NEW "…is taken"
setup $PREV; takeover > $P/t1b.out 2>&1
check "$(holder)" $NEW "…the previous hub's own lock is taken as before"
setup $OTHER; takeover > $P/t2.out 2>&1; check $? 0 "takeover with the config flag, main-merge held by another stage's hub"
check "$(holder)" $OTHER "…is left alone"
grep -q 'main-merge (webapp) is held by Hub core-c #33.*left alone; take it with --take-main-merge' $P/t2.out; check $? 0 "…with the hint"
setup $STRANGER; takeover > $P/t2b.out 2>&1
check "$(holder)" $STRANGER "…a holder registered nowhere is left alone"
setup none; takeover > $P/t3.out 2>&1
check "$(holder)" $NEW "takeover with the config flag, free lock: taken"
setup $OTHER 2020-01-01T00:00:00+00:00; takeover > $P/t3b.out 2>&1
check "$(holder)" $NEW "takeover with the config flag, expired lock: taken"
setup $OTHER; takeover --take-main-merge > $P/t4.out 2>&1
check "$(holder)" $NEW "takeover --take-main-merge takes it from another stage's hub"
grep -q 'ATTENTION: main-merge (webapp) is taken from Hub core-c #33 .* of stage stage-b: its latest journal line is 7 min old' $P/t4.out; check $? 0 "…with the ATTENTION line"
setup $OTHER; takeover --skip-lock main-merge > $P/t5.out 2>&1
check "$(holder)" $OTHER "takeover --skip-lock main-merge leaves it"

# ---- review round 1: who a lock holder is, exactly
# addrole <stage> <live|retired> <role> <session> [tag]: one more record in a stage's registry
addrole(){ python3 - "$R/$1/roles.json" "$2" "$3" "$4" "${5:-x-1}" <<'PY'
import json, sys
path, how, role, sid, tag = sys.argv[1:]
d = json.load(open(path))
rec = {"session": sid, "cli_session_id": sid, "kind": "headless", "tag": tag, "title": tag}
if how == "live":
    d["roles"][role] = rec
elif role == "-":      # a retired record that lost its role name
    d["retired"].append(dict(rec, retired_at="2026-09-01T10:00:00+00:00"))
else:
    d["retired"].append(dict(rec, role=role, retired_at="2026-09-01T10:00:00+00:00"))
json.dump(d, open(path, "w"))
PY
}
STEWARD=77777777-aaaa-4aaa-8aaa-777777777777  # a headless agent of stage-a
# 1. a hub retired here and live elsewhere belongs to the other stage
setup $OLDER; addrole stage-b live hub $OLDER hub-40; takeover > $P/r1.out 2>&1; check $? 0 "takeover, holder retired in this stage and a live hub of another one"
check "$(holder)" $OLDER "…is left alone (a live role elsewhere beats a retired record here)"
grep -q 'left alone; take it with --take-main-merge' $P/r1.out; check $? 0 "…with the hint"
setup $OLDER; addrole stage-b retired hub $OLDER; takeover > $P/r1b.out 2>&1
check "$(holder)" $OLDER "a holder retired in two stages is ambiguous: left alone"
setup $PREV; addrole stage-b live hub $PREV hub-40; takeover > $P/r1c.out 2>&1; check $? 0 "takeover, the previous hub also lives in another stage"
check "$(holder)" $PREV "…its main-merge stays with it"
grep -q 'left alone; take it with --take-main-merge' $P/r1c.out; check $? 0 "…and is reported"
setup $PREV; addrole stage-b live hub $PREV hub-40; takeover --take-main-merge > $P/r1d.out 2>&1
check "$(holder)" $NEW "…the explicit flag still takes it"
grep -q 'of stage stage-b: its latest journal line is' $P/r1d.out; check $? 0 "…naming the stage it lives in"
# 2. only a hub's lock goes with the config flag: a steward of this stage merging is not touched
setup $STEWARD; addrole stage-a live merge-steward $STEWARD steward-1; takeover > $P/r2.out 2>&1; check $? 0 "takeover, main-merge held by a live agent of this stage"
check "$(holder)" $STEWARD "…the config flag leaves it"
setup $STEWARD; addrole stage-a retired merge-steward $STEWARD; takeover > $P/r2b.out 2>&1
check "$(holder)" $STEWARD "…also a retired agent record"
setup $STEWARD; addrole stage-a retired - $STEWARD; takeover > $P/r2c.out 2>&1
check "$(holder)" $STEWARD "…also a retired record without a role name (not a hub)"
setup $STEWARD; addrole stage-a live merge-steward $STEWARD steward-1; takeover --take-main-merge > $P/r2d.out 2>&1
check "$(holder)" $NEW "…the explicit flag takes it"
# 3. an unreadable registry of another stage never aborts, and nothing is taken on what cannot be told
setup $OLDER; printf '[]\n' > $R/stage-b/roles.json; takeover > $P/r3.out 2>&1; check $? 0 "takeover with another stage's roles.json of the wrong shape"
check "$(holder)" $OLDER "…the lock of a holder that cannot be placed is left alone"
setup $OLDER; printf '{"roles": [' > $R/stage-b/roles.json; takeover > $P/r3b.out 2>&1; check $? 0 "takeover with another stage's roles.json that is not JSON"
check "$(holder)" $OLDER "…the same"
setup $OLDER; printf '{"roles": [' > $R/stage-b/roles.json; takeover --take-main-merge > $P/r3c.out 2>&1; check $? 0 "…the explicit flag works"
grep -q 'of stage unknown: no journal line' $P/r3c.out; check $? 0 "…saying the stage is unknown"
setup none; printf '[]\n' > $R/stage-b/roles.json; start > $P/r3d.out 2>&1; check $? 0 "start with another stage's roles.json of the wrong shape"
check "$(holder)" $NEW "…takes a free lock"
if [ "$(id -u)" != 0 ]; then
  setup $OLDER; chmod 000 $R/stage-b/roles.json; takeover > $P/r3e.out 2>&1; rc=$?; chmod 600 $R/stage-b/roles.json
  check $rc 0 "takeover with an unreadable roles.json of another stage"; check "$(holder)" $OLDER "…left alone"
fi
# 4. a journal older than the window is said so
setup $OTHER; rm $(journal stage-b)
python3 -c 'import datetime as d,sys; print(d.datetime.now(d.timezone.utc).date()-d.timedelta(days=8))' > $P/old-day
printf -- '- 10:00 [hub-33] old line\n' > $R/stage-b/coordinator/work/journal-$(cat $P/old-day).md
takeover --take-main-merge > $P/r4.out 2>&1
grep -q 'of stage stage-b: no journal line in the last 7 days' $P/r4.out; check $? 0 "a last line older than 7 days: 'no journal line in the last 7 days'"

exit $fail
