#!/bin/bash
# The end of a run without a status word (WP9, N1-11 / DAY-12 / C-12 / D-06 / D-12): a run that ended with code 0 and a
# successful result is journaled as the neutral `ENDED <role>` (`REVIEWED <role>` for a review role), never as an
# alarm-looking `EXIT`; EXIT stays for an abnormal end; the hub's default wake pattern includes the new words; a progress
# line is not a status word. Both engines (stand-in CLIs, no model).
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py CODEX_BIN=$T/fake_codex.py
R=$AGENT_HUB_HOME; W=$R/w; mkdir -p $W; echo "brief: do the thing" > $W/b.md
J(){ journal stage-a; }
wait_dead(){ for i in $(seq 1 60); do $B/agent status "$1" | grep -q 'ALIVE' || return 0; sleep 0.5; done; }
spawn(){ FAKE_HOLD=1 FAKE_CODEX_HOLD=1 $B/agent spawn --role "$@" --cwd $W --brief $W/b.md > /dev/null 2>&1; }
ended(){ grep -c "^- [0-9:]* \[${2:-$1}\] ENDED $1: " "$(J)"; }
reviewed(){ grep -c "^- [0-9:]* \[${2:-$1}\] REVIEWED $1: " "$(J)"; }
exits(){ grep -c "EXIT $1: " "$(J)"; }
PAT=$(python3 -c "import sys; sys.path.insert(0, '$B'); import hubcore as hc; print(hc.status_pattern())")
PAT_OWN=$(python3 -c "import sys; sys.path.insert(0, '$B'); import hubcore as hc; print(hc.status_pattern(exit_word=False))")

# 1. a clean run with no status word: ENDED under the agent's tag, no EXIT, and the hub's default pattern wakes on it
spawn plain --model haiku; wait_dead plain; sleep 1
check "$(ended plain)" 1 "claude: a clean run without a status word journals ENDED"
check "$(exits plain)" 0 "…and no EXIT line"
LINE=$(grep "ENDED plain: " "$(J)")
echo "$LINE" | grep -q 'ENDED plain: finished, no status word in the journal; code 0, turns 1; last: echo: .* — agent status plain'; check $? 0 "…the line says what ended, the code, the turns and the last text"
echo "$LINE" | grep -Eq "$PAT"; check $? 0 "the hub's default wake pattern matches it (the agent stopped: the hub wakes)"
echo "$LINE" | grep -Eq "$PAT_OWN"; check $? 1 "…but it is not counted as an agent's own status word"
echo "- 10:00 [plain] ENDED plain: x" | grep -Eq "$PAT_OWN"; check $? 1 "…nor is REVIEWED"
echo "- 10:00 [plain] DONE report" | grep -Eq "$PAT_OWN"; check $? 0 "positive control: DONE is"

# 2. a review role: REVIEWED. Names that merely contain the letters are not review roles
spawn review-pr34 --model haiku; wait_dead review-pr34; sleep 1
check "$(reviewed review-pr34)" 1 "a review role (review-pr34) journals REVIEWED"
check "$(ended review-pr34)" 0 "…not ENDED"
spawn desktop-review --model haiku; wait_dead desktop-review; sleep 1
check "$(reviewed desktop-review)" 1 "desktop-review journals REVIEWED too"
spawn preview --model haiku; wait_dead preview; sleep 1
check "$(ended preview)" 1 "negative: preview is not a review role (ENDED)"
check "$(reviewed preview)" 0 "…no REVIEWED"
spawn reviewfix --model haiku; wait_dead reviewfix; sleep 1
check "$(ended reviewfix)" 1 "negative: reviewfix is not a review role (ENDED)"

# 3. a status word of the agent's own: no line at all; a progress word is not one
cat > $W/jl.md <<'B'
brief
B
FAKE_HOLD=3 $B/agent spawn --role fin --tag hub-test-fin --cwd $W --model haiku --brief $W/jl.md > /dev/null 2>&1
$B/jlog --tag hub-test-fin "DONE report at work/fin-REPORT.md" > /dev/null
wait_dead fin; sleep 1
check "$(grep -c 'ENDED fin\|EXIT fin\|REVIEWED fin' "$(J)")" 0 "a DONE line of its own: no ENDED, no EXIT"
FAKE_HOLD=3 $B/agent spawn --role prog --tag hub-test-prog --cwd $W --model haiku --brief $W/jl.md > /dev/null 2>&1
$B/jlog --tag hub-test-prog "PROGRESS 2 of 5 packages written, tests next" > /dev/null
wait_dead prog; sleep 1
check "$(ended prog hub-test-prog)" 1 "a PROGRESS line is not a status word: the run's end is still reported (ENDED)"
grep -q 'PROGRESS 2 of 5' "$(J)" && ! grep 'PROGRESS' "$(J)" | grep -Eq "$PAT"; check $? 0 "…and the PROGRESS line itself wakes nobody"

# 4. abnormal ends stay EXIT: a killed run (no result), a failing CLI result
spawn dead --model haiku; python3 - "$B" <<'PY'
import json, os, sys, time
p = json.load(open(os.path.join(os.environ["AGENT_HUB_HOME"], "stage-a/agents/dead/meta.json")))["pid"]
os.killpg(p, 9)
PY
sleep 1; $B/agent status dead > /dev/null 2>&1
check "$(grep -c 'EXIT dead: killed (no result)' "$(J)")" 1 "a killed run: EXIT killed (no result), as before"
check "$(ended dead)" 0 "…never ENDED"
# the exit-note itself, fed a hand-made log: an error result with code 1, and code 0 with no result at all
exit_note(){  # exit_note ROLE CODE [RESULT-JSON]
python3 - "$R" "$B" "$1" "$2" "${3:-}" <<'PY'
import json, os, sys, subprocess
R, B, role, code, result = sys.argv[1:]
d = f"{R}/stage-a/agents/{role}"; os.makedirs(d, exist_ok=True)
json.dump({"role": role, "tag": role, "stage": "stage-a", "session_id": f"s-{role}", "dir": d, "runs": [{"at": "2026-01-01T00:00:00+00:00"}],
           "pid": 1, "model": "haiku", "engine": "claude", "cwd": R}, open(f"{d}/meta.json", "w"))
open(f"{d}/log.jsonl", "w").write((result + "\n") if result else "")
subprocess.run([f"{B}/agent", "exit-note", role, "--stage", "stage-a", "--code", code], check=True)
PY
}
exit_note errd 1 '{"type": "result", "subtype": "error_max_turns", "is_error": true, "num_turns": 3, "result": "stopped"}' > /dev/null
grep -q '\[errd\] EXIT errd: error_max_turns, error; code 1' "$(J)"; check $? 0 "an error result with code 1 stays EXIT"
exit_note errn 0 > /dev/null
grep -q 'EXIT errn: no result — died or killed; code 0' "$(J)"; check $? 0 "code 0 without a result stays EXIT (died or killed)"
exit_note errc 1 '{"type": "result", "subtype": "success", "is_error": false, "num_turns": 1, "result": "ok"}' > /dev/null
grep -q 'EXIT errc: .*code 1' "$(J)"; check $? 0 "a success result with a non-zero code stays EXIT"
exit_note errok 0 '{"type": "result", "subtype": "success", "is_error": false, "num_turns": 1, "result": "ok"}' > /dev/null
grep -q 'ENDED errok: .*code 0' "$(J)"; check $? 0 "positive control: the same result with code 0 is ENDED"

# 5. Codex parity: the same classification for a Codex run
FAKE_CODEX_HOLD=1 $B/agent spawn --engine codex --role cdx --cwd $W --brief $W/b.md > /dev/null 2>&1; wait_dead cdx; sleep 1
check "$(ended cdx)" 1 "codex: a clean run without a status word journals ENDED"
check "$(exits cdx)" 0 "…no EXIT"
FAKE_CODEX_HOLD=1 $B/agent spawn --engine codex --role review-cdx --cwd $W --brief $W/b.md > /dev/null 2>&1; wait_dead review-cdx; sleep 1
check "$(reviewed review-cdx)" 1 "codex: a review role journals REVIEWED"
FAKE_CODEX=error FAKE_CODEX_HOLD=1 $B/agent spawn --engine codex --role cdx-bad --cwd $W --brief $W/b.md > /dev/null 2>&1; wait_dead cdx-bad; sleep 1
check "$(grep -c 'EXIT cdx-bad: error' "$(J)")" 1 "codex: an API failure stays EXIT"

# 6. a custom wake word still counts as the agent's own status
export AGENT_HUB_JWAIT_MATCH='PENDING OWNER'
FAKE_HOLD=3 $B/agent spawn --role pend --tag hub-test-pend --cwd $W --model haiku --brief $W/jl.md > /dev/null 2>&1
$B/jlog --tag hub-test-pend "PENDING OWNER: which branch?" > /dev/null; wait_dead pend; sleep 1
check "$(grep -c 'ENDED pend\|EXIT pend' "$(J)")" 0 "an extra wake word counts as a status word (no ENDED)"
unset AGENT_HUB_JWAIT_MATCH
for r in plain review-pr34 desktop-review preview reviewfix fin prog dead pend cdx review-cdx cdx-bad; do $B/agent stop $r > /dev/null 2>&1; done
exit $fail
