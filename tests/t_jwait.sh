#!/bin/bash
# jlog / jwait: baseline, own-tag exclusion, rewrite without replay, filters, file sources, partial lines,
# --since replay, alarms, usage errors.
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a; O=$AGENT_HUB_HOME
J=$(journal stage-a)
$B/jlog --tag old "old line before the first run" >/dev/null
# 1. first run: baseline; a line from another process wakes it
( sleep 2; $B/jlog --tag hub-16-builder "DONE builder finished" >/dev/null ) &
HUB_TAG=hub-16 $B/jwait --journal --settle 1 --for 30s > $O/o1.out 2>&1; rc=$?
check $rc 0 "positive: line from another process delivered"
grep -q 'DONE builder' $O/o1.out && ! grep -q 'old line' $O/o1.out; check $? 0 "baseline: old line not delivered"
grep -q 'first run of \[hub-16\]' $O/o1.out; check $? 0 "baseline run says it marked lines as seen"
# 2. own tag and own sub-tag ignored, sibling tag delivered
( sleep 1; $B/jlog --tag hub-16 "own line" >/dev/null; $B/jlog --tag hub-16/r7 "own sub-line" >/dev/null; sleep 2; $B/jlog --tag steward "MERGED #700" >/dev/null ) &
HUB_TAG=hub-16 $B/jwait --journal --settle 1 --for 30s > $O/o2.out 2>&1; rc=$?
check $rc 0 "sibling line delivered"
! grep -q 'own' $O/o2.out; check $? 0 "negative: own tag and sub-tag ignored"
grep -q 'MERGED #700' $O/o2.out; check $? 0 "MERGED line present"
# 3. rewrite/replay: same content rewritten (new inode) -> nothing delivered -> alarm
cp $J $J.tmp && mv $J.tmp $J
HUB_TAG=hub-16 $B/jwait --journal --settle 1 --for 4s --note "replay check" > $O/o3.out 2>&1; rc=$?
check $rc 3 "negative: replayed journal after rewrite delivers nothing (alarm)"
grep -q '^ALARM replay check' $O/o3.out; check $? 0 "ALARM line printed"
# 4. lines appended while nobody waits are delivered on the next run
$B/jlog --tag qa "BLOCKED need the staging env" >/dev/null
HUB_TAG=hub-16 $B/jwait --journal --settle 0 --for 5s > $O/o4.out 2>&1; rc=$?
check $rc 0 "line appended between runs delivered"
grep -q 'BLOCKED need the staging env' $O/o4.out; check $? 0 "…with its text"
# 5. filters: --match / --tag @mention; non-matching ignored
( sleep 1; $B/jlog --tag builder "just progress" >/dev/null; sleep 1; $B/jlog --tag builder "@hub-16 QUESTION about #701" >/dev/null ) &
HUB_TAG=hub-16 $B/jwait --journal --tag hub-16 --match 'MERGED|STOP' --settle 1 --for 20s > $O/o5.out 2>&1; rc=$?
check $rc 0 "@mention delivered"
! grep -q 'just progress' $O/o5.out; check $? 0 "negative: non-matching line filtered"
# 6. file source: a question already in the file before start is delivered; settle batches
F=$O/script.log; printf 'step 1 ok\nAWAITING ANSWER [go] continue?\n' > $F
( sleep 1; echo 'AWAITING ANSWER [go2] and this?' >> $F ) &
$B/jwait --file $F --match 'AWAITING ANSWER' --settle 3 --for 20s --caller t6 > $O/o6.out 2>&1; rc=$?
check $rc 0 "file source delivered"
check "$(grep -c 'AWAITING ANSWER' $O/o6.out)" 2 "settle batched both questions into one block"
$B/jwait --file $F --match 'AWAITING ANSWER' --settle 0 --for 3s --caller t6 > $O/o7.out 2>&1; rc=$?
check $rc 3 "negative: same file lines not re-delivered"
# 7. pure alarm
$B/jwait --until "$(utc_hhmm 1)" --note "check the nightly import" > $O/o8.out 2>&1; rc=$?
check $rc 3 "pure alarm exit 3"; grep -q '^ALARM check the nightly import' $O/o8.out; check $? 0 "pure alarm text"
# 8. usage errors
$B/jwait >/dev/null 2>&1; check $? 2 "usage: no source, no deadline"
$B/jlog "no tag" >/dev/null 2>&1; check $? 2 "usage: jlog without tag"
# 9. an in-place edit that grows a watched file delivers only the inserted line
F=$O/p.log
printf -- '- 10:00 [qa] line A\n- 10:01 [qa] line B\n- 10:02 [qa] line C\n' > $F
$B/jwait --file $F --settle 0 --for 3s --caller r1 >/dev/null 2>&1
( sleep 1.5; python3 -c "
p='$F'; s=open(p).read(); fh=open(p,'r+'); fh.seek(0); fh.write('- 09:59 [qa] line NEW\n'+s); fh.close()" ) &
$B/jwait --file $F --settle 1 --for 10s --caller r1 > $O/o9.out 2>&1
check "$(grep -c '^p.log:' $O/o9.out)" 1 "in-place growing edit delivers only the inserted line"
grep -q 'line NEW' $O/o9.out; check $? 0 "…and it is the new line"
# 10. a new caller gets what arrived since --since (ISO), even after a baseline run
new_home
$B/jlog --tag qa "AWAITING ANSWER [go] ship it?" >/dev/null
$B/jwait --journal --match 'AWAITING ANSWER' --caller hub-17 --since "$(utc_iso -2)" --settle 0 --for 5s > $O/o10.out 2>&1; rc=$?
check $rc 0 "--since <ISO> delivers the line written before the first run"
$B/jwait --journal --caller hub-18 --settle 0 --for 2s >/dev/null 2>&1   # baseline: the line is now "seen" by hub-18
$B/jwait --journal --match 'AWAITING ANSWER' --caller hub-18 --since "$(utc_iso -2)" --settle 0 --for 4s > $O/o11.out 2>&1; rc=$?
check $rc 0 "--since after a baseline run replays the line"
grep -q 'ship it' $O/o11.out; check $? 0 "…the right line"
$B/jwait --journal --match 'AWAITING ANSWER' --caller hub-18 --settle 0 --for 3s >/dev/null 2>&1; check $? 3 "negative: without --since it stays seen"
# 11. partial last line of a --file source (a script blocked on read -p)
F=$O/go.log; printf 'step 1 ok\nAWAITING ANSWER [go] ship? (yes/no) ' > $F
$B/jwait --file $F --match 'AWAITING ANSWER' --caller p1 --settle 2 --for 20s > $O/o12.out 2>&1; rc=$?
check $rc 0 "partial: a question without a newline is delivered once stable"
grep -q 'ship?' $O/o12.out; check $? 0 "partial: …with its text"
printf '\n' >> $F
$B/jwait --file $F --match 'AWAITING ANSWER' --caller p1 --settle 1 --for 4s >/dev/null 2>&1; check $? 3 "partial: completing the line later does not deliver it again"
# 12. the default deadline is 2 h: a background Bash task is not guaranteed to live longer
secs=$(python3 - "$B" <<'PY'
import importlib.machinery, importlib.util, sys
sys.path.insert(0, sys.argv[1])
import hubcore as hc
loader = importlib.machinery.SourceFileLoader("jwait_cli", sys.argv[1] + "/jwait")
spec = importlib.util.spec_from_loader("jwait_cli", loader); jw = importlib.util.module_from_spec(spec); loader.exec_module(jw)
print(int(hc.parse_duration(jw.DEFAULT_FOR).total_seconds()))
PY
)
check "$secs" 7200 "default --for is 2h"
$B/jwait --help | tr '\n' ' ' | grep -q 'default --for 2h'; check $? 0 "--help says the default is 2h"
exit $fail
