#!/bin/bash
# A handoff with TODO left in § 0–2 is not a handoff (WP9, A-03): `hub handoff --finish` refuses it (exit 2, the lines
# listed) and `--allow-todo` lets it through, saying what stays open; `hub succeed --handoff` makes the same check before
# it starts a successor; `hub takeover` warns when the handoff it reads still has TODO there. TODO in § 3–6 or in an
# HTML comment is not an obstacle.
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME; HUB1=11111111-1111-4111-8111-111111111111; HUB2=22222222-2222-4222-8222-222222222222
export CLAUDE_BIN=$T/fake_claude_bg.py FAKE_AGENTS=none FAKE_BG_LOG=$R/bg.log   # never the real `claude`
$B/hub start --stage stage-a --session $HUB1 > $R/start.out 2>&1; check $? 0 "setup: hub start"
C=$R/stage-a/coordinator
$B/hub handoff --stage stage-a --n 1 --out $C/HANDOFF-hub-stage-a-DRAFT.md > $R/h.out 2>&1; check $? 0 "the raw draft is written (TODO is expected there)"

# 1. --finish on the raw draft
$B/hub handoff --stage stage-a --finish --handoff $C/HANDOFF-hub-stage-a-DRAFT.md > $R/f1.out 2> $R/f1.err; check $? 2 "--finish refuses the raw draft (exit 2)"
grep -q 'still hold [0-9]* TODO line' $R/f1.err; check $? 0 "…and says how many lines"
grep -q 'line [0-9]*: 1\. TODO' $R/f1.err && grep -q 'Open PRs | TODO' $R/f1.err; check $? 0 "…lists them with line numbers (§ 1 and § 2)"
grep -q 'Risks\|TODO: what breaks' $R/f1.err; check $? 1 "…and not the TODO of § 5"
grep -q '^## 0' $R/f1.err; check $? 1 "…headings are not listed"

# 2. the override
$B/hub handoff --stage stage-a --finish --handoff $C/HANDOFF-hub-stage-a-DRAFT.md --allow-todo > $R/f2.out 2> $R/f2.err; check $? 0 "--allow-todo lets it through"
grep -q 'ATTENTION: --allow-todo: .* TODO line(s) in § 0–2 .* stay open' $R/f2.err; check $? 0 "…and prints what stays open"
grep -q 'handoff ready' $R/f2.out; check $? 0 "…then the ready line"

# 3. filled in § 0–2, TODO left in § 3–6: ready. A TODO in an HTML comment of § 1 does not count either
python3 - $C/HANDOFF-hub-stage-a-DRAFT.md $C/HANDOFF-hub-stage-a-FILLED.md <<'PY'
import re, sys
t = open(sys.argv[1], encoding="utf-8").read()
parts = re.split(r"(?m)^(?=## )", t)
out = []
for p in parts:
    m = re.match(r"## (\d)\.", p)
    if m and int(m.group(1)) <= 2:
        p = p.replace("TODO", "done:")
    out.append(p)
t = "".join(out).replace("## 1. Where things stand", "## 1. Where things stand\n<!-- TODO in a comment is a hint, not an open item -->", 1)
open(sys.argv[2], "w", encoding="utf-8").write(t)
PY
grep -q 'TODO' $C/HANDOFF-hub-stage-a-FILLED.md; check $? 0 "setup: TODO is left in § 3–6 and in the comment"
$B/hub handoff --stage stage-a --finish --handoff $C/HANDOFF-hub-stage-a-FILLED.md > $R/f3.out 2> $R/f3.err; check $? 0 "§ 0–2 filled: --finish passes"
grep -q 'handoff ready: .*FILLED.md (.* TODO left outside § 0–2)' $R/f3.out; check $? 0 "…and counts what is left outside § 0–2"
check "$(wc -c < $R/f3.err | tr -d ' ')" 0 "…without a warning"

# 4. without --handoff: the stage's latest handoff
touch -t 202001010000 $C/HANDOFF-hub-stage-a-DRAFT.md; $B/hub handoff --stage stage-a --finish > $R/f4.out 2>&1; check $? 0 "--finish with no path takes the latest handoff (FILLED.md, newest)"
grep -q 'FILLED.md' $R/f4.out; check $? 0 "…and names it"
$B/hub handoff --stage stage-a --finish --handoff $C/HANDOFF-hub-stage-a-NOPE.md > $R/f5.out 2>&1; check $? 2 "negative: a missing file is a usage error"
$B/hub handoff --stage stage-a --handoff $C/HANDOFF-hub-stage-a-FILLED.md > $R/f6.out 2>&1; check $? 2 "negative: --handoff without --finish is refused"

# 5. hub succeed makes the same check (a dry run is enough: the check comes before any plan)
$B/hub succeed --stage stage-a --handoff $C/HANDOFF-hub-stage-a-DRAFT.md --model opus --effort high --dry-run --cwd $R > $R/s1.out 2> $R/s1.err; check $? 2 "succeed refuses the raw draft (exit 2)"
grep -q 'still hold [0-9]* TODO line' $R/s1.err; check $? 0 "…with the same message"
$B/hub succeed --stage stage-a --handoff $C/HANDOFF-hub-stage-a-DRAFT.md --allow-todo --model opus --effort high --dry-run --cwd $R > $R/s2.out 2> $R/s2.err; check $? 0 "succeed --allow-todo goes on"
grep -q '^\[plan\] auto-handoff' $R/s2.out; check $? 0 "…to the plan"
$B/hub succeed --stage stage-a --handoff $C/HANDOFF-hub-stage-a-FILLED.md --model opus --effort high --dry-run --cwd $R > $R/s3.out 2> $R/s3.err; check $? 0 "positive control: the filled handoff passes succeed"

# 6. takeover warns, once, in the output and the digest, and still takes over
$B/hub takeover --stage stage-a --session $HUB2 --handoff $C/HANDOFF-hub-stage-a-DRAFT.md --dry-run > $R/t1.out 2>&1; check $? 0 "takeover (dry run) from the raw draft still works"
grep -c 'ATTENTION: the handoff HANDOFF-hub-stage-a-DRAFT.md still has [0-9]* TODO line(s) in § 0–2' $R/t1.out | grep -qx 2; check $? 0 "…and warns (the step list and the digest)"
$B/hub takeover --stage stage-a --session $HUB2 --handoff $C/HANDOFF-hub-stage-a-FILLED.md --dry-run > $R/t2.out 2>&1; check $? 0 "takeover from the filled handoff"
grep -q 'still has [0-9]* TODO' $R/t2.out; check $? 1 "…no warning"
exit $fail
