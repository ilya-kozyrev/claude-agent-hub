#!/bin/bash
# tell: a journal line to another stage's hub (addressed @hub, signed with the caller's qualified tag), the direct
# address from the registry, no write with --address, unresolvable targets, a failing `claude agents`.
. "$(dirname "$0")/lib.sh"
new_home; O=$AGENT_HUB_HOME
export CLAUDE_BIN=$T/fake_claude_bg.py FAKE_BG_LOG=$O/bg.log FAKE_AGENTS=none   # never the real `claude agents`
HUBC=aaaaaaaa-1111-4111-8111-111111111111   # tc-core's hub (a terminal session)
ME=bbbbbbbb-2222-4222-8222-222222222222     # the caller: hub-4 of tc-dolya
STW=cccccccc-3333-4333-8333-333333333333    # a headless steward of tc-core
$B/roles --stage tc-core set hub $HUBC --kind cli --tag hub-30 --title "Hub tc-core #30" >/dev/null
$B/roles --stage tc-core set steward $STW --kind headless --tag steward --title "steward" >/dev/null
$B/roles --stage tc-dolya set hub $ME --kind cli --tag hub-4 >/dev/null
JC=$(journal tc-core); JD=$(journal tc-dolya)
tell(){ HUB_STAGE=tc-dolya CLAUDE_CODE_SESSION_ID=$ME $B/tell "$@"; }

# 1. the line: addressed @hub, signed with the caller's stage-qualified tag, in the TARGET stage's journal
FAKE_AGENTS=prev FAKE_PREV_SID=$HUBC tell tc-core "review !41 please" > $O/t1.out 2>&1; check $? 0 "tell tc-core exits 0"
grep -q '^- [0-9:]* \[tc-dolya-hub-4\] @hub review !41 please$' $JC; check $? 0 "journal line: @hub, qualified tag tc-dolya-hub-4, in tc-core's journal"
[ ! -e $JD ] || ! grep -q 'review !41' $JD; check $? 0 "negative: nothing is written to the caller's own journal"
grep -q "session  $HUBC" $O/t1.out && grep -q 'kind     cli' $O/t1.out && grep -q 'title    "Hub tc-core #30"' $O/t1.out; check $? 0 "prints the full session id, kind and title"
grep -q 'name     Hub stage-a #16' $O/t1.out; check $? 0 "…and the name from claude agents, found by session id"
# 2. --question
FAKE_AGENTS=prev FAKE_PREV_SID=$HUBC tell tc-core --question "merge or wait?" > $O/t2.out 2>&1; check $? 0 "--question exits 0"
grep -q '\[tc-dolya-hub-4\] @hub QUESTION merge or wait?$' $JC; check $? 0 "--question: @hub QUESTION …"
# 3. --role: the steward is headless → agent send, no session name lookup
tell tc-core --role steward "pause the merge" > $O/t3.out 2>&1; check $? 0 "--role steward exits 0"
grep -q '\[tc-dolya-hub-4\] @steward pause the merge$' $JC; check $? 0 "--role: @steward …"
grep -q 'agent send --stage tc-core steward' $O/t3.out; check $? 0 "headless: the address is the agent send command"
! grep -q 'name  ' $O/t3.out; check $? 0 "negative: no session name for a headless agent"
# 4. --address: prints the address, writes nothing
before=$(cat $JC | wc -l)
FAKE_AGENTS=prev FAKE_PREV_SID=$HUBC tell tc-core --address > $O/t4.out 2>&1; check $? 0 "--address exits 0"
check "$(cat $JC | wc -l)" "$before" "--address writes nothing"
grep -q "session  $HUBC" $O/t4.out && grep -q 'name     Hub stage-a #16' $O/t4.out; check $? 0 "--address prints the id and the name"
# 5. a stage or a holder that cannot be resolved: exit 1, naming the stages that have a hub
tell tc-nostage "hello" > $O/t5.out 2>&1; check $? 1 "unknown stage → exit 1"
grep -q 'tc-core' $O/t5.out && grep -q 'tc-dolya' $O/t5.out; check $? 0 "…listing the stages that have a hub"
[ ! -e $(journal tc-nostage) ]; check $? 0 "negative: no journal is created for an unknown stage"
mkdir -p $O/tc-empty; $B/roles --stage tc-empty set qa $STW --kind headless >/dev/null
tell tc-empty "hello" > $O/t5b.out 2>&1; check $? 1 "a stage without a hub → exit 1"
tell tc-core --role nobody --address > $O/t5c.out 2>&1; check $? 1 "no holder of the role → exit 1, also with --address"
# 6. usage
tell tc-core > $O/t6.out 2>&1; check $? 2 "no text → exit 2"
env -u CLAUDE_CODE_SESSION_ID -u HUB_STAGE -u HUB_TAG $B/tell tc-core "anonymous" > $O/t6b.out 2>&1; check $? 2 "caller without a tag → exit 2"
grep -q 'anonymous' $JC; check $? 1 "negative: nothing written without a tag"
# 7. `claude agents` failing: the journal line is still written, exit 0, no name
FAKE_AGENTS=fail tell tc-core "still delivered" > $O/t7.out 2>&1; check $? 0 "claude agents failing → exit 0"
grep -q '\[tc-dolya-hub-4\] @hub still delivered$' $JC; check $? 0 "…the journal line is there"
grep -q "session  $HUBC" $O/t7.out && ! grep -q 'name  ' $O/t7.out; check $? 0 "…the address without a name"
CLAUDE_BIN=/nonexistent/claude tell tc-core "no cli" > $O/t7b.out 2>&1; check $? 0 "no claude binary → exit 0"
# 8. the tool is listed like the others
python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import hubcore as hc; sys.exit(0 if "tell" in hc.plugin_tools() else 1)' $B; check $? 0 "plugin_tools() lists tell"
exit $fail
