#!/bin/bash
# roles: registry, Desktop session validation (fake sessions dir), send budget, broadcast, retire.
. "$(dirname "$0")/lib.sh"
new_home; export CLAUDE_SESSIONS_DIR=$AGENT_HUB_HOME/sessions HUB_STAGE=stage-a
mk(){ mkdir -p $CLAUDE_SESSIONS_DIR/a/b; printf '{"sessionId":"local_%s","cliSessionId":"%s","title":"%s","isArchived":%s}' "$1" "$2" "$3" "$4" > $CLAUDE_SESSIONS_DIR/a/b/local_$1.json; }
H=11111111-1111-4111-8111-111111111111; HC=aaaaaaaa-1111-4111-8111-111111111111
P=22222222-2222-4222-8222-222222222222; PC=bbbbbbbb-2222-4222-8222-222222222222
X=33333333-3333-4333-8333-333333333333
mk $H $HC "Hub stage-a #17" false; mk $P $PC "builder" false; mk $X cccccccc-3333-4333-8333-333333333333 "old" true
$B/roles set hub local_$H --tag hub-17 >/dev/null; check $? 0 "set desktop role"
check "$($B/roles get hub)" "local_$H" "get prints the full local id"
$B/roles set p3 local_$X >/dev/null 2>&1; check $? 1 "negative: archived session refused"
$B/roles set p3 local_44444444-4444-4444-8444-444444444444 >/dev/null 2>&1; check $? 1 "negative: unknown session refused"
$B/roles set p3 local_2222 >/dev/null 2>&1; check $? 2 "negative: short id refused"
$B/roles set p3 $P --tag builder >/dev/null; check $? 0 "set without local_ prefix"
$B/roles set steward 55555555-5555-4555-8555-555555555555 --kind headless --tag steward >/dev/null; check $? 0 "set headless"
$B/roles set term 66666666-6666-4666-8666-666666666666 --kind cli --tag term >/dev/null; check $? 0 "set cli (terminal session)"
$B/roles set term2 not-a-uuid --kind cli >/dev/null 2>&1; check $? 2 "negative: cli id must be a uuid"
$B/roles get nobody >/dev/null 2>&1; check $? 1 "negative: get unknown role"
# jlog picks the tag from the registry by CLAUDE_CODE_SESSION_ID
out=$(CLAUDE_CODE_SESSION_ID=$HC $B/jlog "tag check"); echo "$out" | grep -q '\[hub-17\] tag check'; check $? 0 "jlog tag from registry"
# budget: 10 per sender; broadcast records and writes one journal line
check "$($B/roles budget hub p3)" "10 (sent to this recipient: 0)" "budget starts at 10"
for i in 1 2 3 4 5 6 7 8; do $B/roles sent hub p3 >/dev/null; done
out=$(CLAUDE_CODE_SESSION_ID=$HC $B/roles broadcast --all "main is now e1f2"); rc=$?
check $rc 0 "broadcast ok"
echo "$out" | grep -q "^p3 .* 1$"; check $? 0 "broadcast row shows budget after send"
echo "$out" | grep -q "^steward .*headless: agent send"; check $? 0 "headless recipient routed to agent send"
echo "$out" | grep -q "^term .*cli: no cross-session send"; check $? 0 "cli recipient routed to the journal"
J=$(journal stage-a)
check "$(grep -c '@builder @steward @term main is now e1f2' $J)" 1 "one journal line for the broadcast"
$B/roles sent hub p3 >/dev/null
out=$($B/roles budget hub p3); echo "$out" | head -1 | grep -q '^0 '; check $? 0 "budget exhausted at 10"
echo "$out" | grep -q 'jlog "@builder'; check $? 0 "fallback jlog line printed at 0"
$B/roles reset hub >/dev/null; check "$($B/roles budget hub | head -1)" "10" "reset restores budget"
AGENT_HUB_SEND_CAP=3 $B/roles budget hub > $AGENT_HUB_HOME/cap.out; check "$(head -1 $AGENT_HUB_HOME/cap.out)" "3" "send cap is configurable"
# replace keeps history; retire removes
$B/roles set hub local_$P --tag hub-18 >/dev/null; $B/roles list --all | grep -q "(retired) hub .*local_$H"; check $? 0 "replaced holder kept in retired"
$B/roles retire steward >/dev/null; $B/roles get steward >/dev/null 2>&1; check $? 1 "retire removes role"
$B/roles bogus >/dev/null 2>&1; check $? 2 "usage error exit 2"
exit $fail
