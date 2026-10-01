#!/bin/bash
# Day one: `hub start` registers the first hub of a new stage; shift numbers are derived (roles.json, the latest
# handoff) with --n as an override; `roles set` infers the session kind from the id. Positive and negative controls.
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME; P=$(mktemp -d)/t
export CLAUDE_SESSIONS_DIR=$R/sessions
mk(){ mkdir -p $CLAUDE_SESSIONS_DIR/a/b; printf '{"sessionId":"local_%s","cliSessionId":"%s","title":"%s","isArchived":false}' "$1" "$2" "$3" > $CLAUDE_SESSIONS_DIR/a/b/local_$1.json; }
H1=11111111-1111-4111-8111-111111111111; H2=22222222-2222-4222-8222-222222222222; H3=33333333-3333-4333-8333-333333333333
DESK=44444444-4444-4444-8444-444444444444; DESK_CLI=55555555-5555-4555-8555-555555555555
mk $DESK $DESK_CLI "Hub desk"

# ---- before start: the errors point at hub start
CLAUDE_CODE_SESSION_ID=$H1 $B/jlog --stage web "hello" > /dev/null 2> $P.jlog.err; check $? 2 "negative: jlog of an unregistered session has no tag"
grep -q "hub start --stage S" $P.jlog.err; check $? 0 "…and the error says how the first hub registers"
$B/hub takeover --stage web --session $H1 > /dev/null 2> $P.tk.err; check $? 2 "negative: takeover of a stage that does not exist"
grep -q "hub start --stage web" $P.tk.err; check $? 0 "…points at hub start"

# ---- hub start
before=$(snap $R); $B/hub start --stage web --session $H1 --dry-run > /dev/null 2>&1; check $? 0 "start --dry-run"
check "$(snap $R)" "$before" "…writes nothing"
CLAUDE_CODE_SESSION_ID=$H1 $B/hub start --stage web --session $H1 > $P.start.out 2>&1; check $? 0 "start a new stage from a terminal session"
grep -q 'starts stage web' $P.start.out && grep -q 'jwait --journal --stage web --tag hub-1' $P.start.out; check $? 0 "…prints the first jwait for hub-1"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1]))["roles"]["hub"]; assert (r["tag"],r["kind"],r["session"])==("hub-1","cli",sys.argv[2]), r' $R/web/roles.json $H1; check $? 0 "…registers hub-1 as a cli session"
grep -q '\[hub-1\] start: "Hub web #1".*started stage web' $(journal web); check $? 0 "…and writes the start line"
CLAUDE_CODE_SESSION_ID=$H1 $B/jlog --stage web "first plan" > /dev/null; check $? 0 "jlog from the hub now finds its tag"
grep -q '\[hub-1\] first plan' $(journal web); check $? 0 "…tagged hub-1"
CLAUDE_CODE_SESSION_ID=$H1 $B/hub start --stage web --session $H1 > /dev/null 2>&1; check $? 0 "start again by the same session: a no-op"
[ "$(grep -c 'started stage web' $(journal web))" = 1 ]; check $? 0 "…one start line"
$B/hub start --stage web --session $H2 > /dev/null 2> $P.st2.err; check $? 2 "negative: start of a stage that has a hub"
grep -q "use \`hub takeover" $P.st2.err; check $? 0 "…says to take over"

# ---- derived shift numbers
CLAUDE_CODE_SESSION_ID=$H1 $B/hub handoff --stage web --out $R/web/coordinator/HANDOFF-hub-web-1.md > /dev/null; check $? 0 "handoff without --n"
grep -q '^# Handoff "Hub web #1" → "Hub web #2"' $R/web/coordinator/HANDOFF-hub-web-1.md; check $? 0 "…numbered from the registered hub"
CLAUDE_CODE_SESSION_ID=$H2 $B/hub takeover --stage web --session $H2 > $P.tk2.out 2>&1; check $? 0 "takeover without --n"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["roles"]["hub"]["tag"]=="hub-2"' $R/web/roles.json; check $? 0 "…becomes hub-2"
CLAUDE_CODE_SESSION_ID=$H2 $B/hub takeover --stage web --session $H2 > /dev/null 2>&1; check $? 0 "re-run of the takeover"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["roles"]["hub"]["tag"]=="hub-2"' $R/web/roles.json; check $? 0 "…keeps hub-2 (not hub-3)"
CLAUDE_CODE_SESSION_ID=$H3 $B/hub takeover --stage web --session $H3 --n 7 > /dev/null 2>&1; check $? 0 "--n overrides"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["roles"]["hub"]["tag"]=="hub-7"' $R/web/roles.json; check $? 0 "…hub-7"
# a handoff that names a later successor than roles: the larger number wins, with a note
printf '# Handoff "Hub web #9" → "Hub web #10" — web\n' > $R/web/coordinator/HANDOFF-hub-web-9.md
$B/hub takeover --stage web --session local_$DESK --handoff $R/web/coordinator/HANDOFF-hub-web-9.md > $P.tk4.out 2>&1; check $? 0 "takeover with a disagreeing handoff"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1]))["roles"]["hub"]; assert (r["tag"],r["kind"])==("hub-10","desktop"), r' $R/web/roles.json; check $? 0 "…takes the larger number"
grep -q 'roles say hub-7 (next #8), the handoff names #10' $P.tk4.out; check $? 0 "…and says so"
# no hub and no handoff: handoff needs --n
mkdir -p $R/empty/coordinator/work
$B/hub handoff --stage empty > /dev/null 2> $P.h0.err; check $? 2 "negative: handoff with nothing to count from"
grep -q "pass --n" $P.h0.err; check $? 0 "…asks for --n"

# ---- roles set infers the kind
$B/roles --stage web set reviewer $H3 > /dev/null; check $? 0 "roles set with a terminal uuid and no --kind"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["roles"]["reviewer"]["kind"]=="cli"' $R/web/roles.json; check $? 0 "…kind cli"
$B/roles --stage web set desk local_$DESK > /dev/null; check $? 0 "roles set with a local_ id"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["roles"]["desk"]["kind"]=="desktop"' $R/web/roles.json; check $? 0 "…kind desktop"
$B/roles --stage web set desk2 $DESK > /dev/null; check $? 0 "roles set with a bare uuid Claude Desktop knows"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["roles"]["desk2"]["kind"]=="desktop"' $R/web/roles.json; check $? 0 "…kind desktop"
$B/roles --stage web set ghost local_66666666-6666-4666-8666-666666666666 > /dev/null 2>&1; check $? 1 "negative: an unknown local_ id is refused"
$B/roles --stage web set x $H1 --kind headless > /dev/null; check $? 0 "an explicit --kind still wins"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["roles"]["x"]["kind"]=="headless"' $R/web/roles.json; check $? 0 "…kind headless"
exit $fail
