#!/bin/bash
# ask (owner-question register) and nightq (night queue) on a throw-away hub home.
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME; F=$R/stage-a/questions.md
out=$($B/ask add --stage stage-a --blocks "release" --default "ship with the flag off" --due 2099-01-01T10:00 --by hub-3 "Ship the flag on by default?")
check "$(echo "$out" | head -1)" "Q-A-001" "add prints the new id"
echo "$out" | sed -n 2p | grep -q '^Q-A-001 recorded [0-9][0-9]\.[0-9][0-9] [0-9:]*: Ship the flag'; check $? 0 "add prints a ready journal line"
$B/ask add --stage stage-a --due 2000-01-01 "Rename the service?" >/dev/null
$B/ask decided --stage stage-a --alternative "keep CSV" "Export as Parquet" >/dev/null
grep -q '^<!-- ask:v1 prefix=A -->' $F && grep -q '^## D-A-001 — Export as Parquet' $F; check $? 0 "register file with prefix and entries"
check "$($B/ask summary)" "stage-a — open 2, overdue 1, decided by an agent, contestable 1" "summary line"
$B/ask list --overdue | grep -q 'Q-A-002 \[stage-a\] open OVERDUE — Rename the service?'; check $? 0 "list --overdue"
$B/ask close Q-A-001 --answer "yes, on by default" > $R/c.out; check $? 0 "close"
grep -q '^- status: answered: yes, on by default (20' $F; check $? 0 "close writes the answer with a stamp"
$B/ask close Q-A-001 --answer again >/dev/null 2>&1; check $? 1 "negative: closing twice refused"
$B/ask list --pending | grep -q '^Q-A-001'; check $? 0 "an answer without done is pending"
$B/ask done Q-A-001 --evidence "flag default flipped in PR #12" >/dev/null; check $? 0 "done"
$B/ask list --pending 2>/dev/null | grep -q '^Q-A-001'; check $? 1 "…no longer pending"
$B/ask search parquet | grep -q '^D-A-001'; check $? 0 "search is case-insensitive over titles"
$B/ask search nonexistentword | grep -q 'nothing found'; check $? 0 "search reports an empty result with its scope"
$B/ask digest | grep -q '^Q-A-001 yes, on by default'; check $? 0 "digest line per answer"
$B/ask withdraw Q-A-002 --reason "not needed" >/dev/null; grep -q 'withdrawn: not needed' $F; check $? 0 "withdraw"
$B/ask close Q-A-009 --answer x >/dev/null 2>&1; check $? 1 "negative: unknown id"
$B/ask add --stage Bad_Stage "x" >/dev/null 2>&1; check $? 1 "negative: bad stage name"
# ---- nightq
cp $T/fixtures/night-queue.md $R/stage-a/night-queue.md
subst $R/stage-a/night-queue.md 'PREV_ID' 'abababab-abab-4bab-8bab-abababababab'
$B/nightq check --stage stage-a > $R/n1.out; check $? 0 "nightq check passes on the fixture"
echo '- [ ] Deploy to production | stop: errors | class: prod' >> $R/stage-a/night-queue.md
$B/nightq check --stage stage-a > $R/n2.out; check $? 1 "negative: prod item without yes: fails"
grep -q "prod without the owner's" $R/n2.out; check $? 0 "…and says why"
echo '- [ ] Something | class: other' >> $R/stage-a/night-queue.md
$B/nightq check --stage stage-a > $R/n3.out; grep -q 'no "stop:"' $R/n3.out && grep -q "class 'other' is not one of" $R/n3.out; check $? 0 "missing stop and unknown class reported"
$B/nightq status --json | python3 -c 'import json,sys; d=json.load(sys.stdin); s=d["stages"][0]; assert s["stage"]=="stage-a" and s["open"]==4 and s["done"]==1, s'; check $? 0 "status --json counts open and done"
$B/nightq log --stage stage-a "nudged the coordinator" | grep -q ' — nudged the coordinator$'; check $? 0 "log appends a line"
head -1 $R/stage-a/night-log.md | grep -q '^# Night log — stage-a'; check $? 0 "log file gets a header"
exit $fail
