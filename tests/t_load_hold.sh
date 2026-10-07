#!/bin/bash
# The machine-load spawn hold (R5, bin/spawn_hold.py): the watchdog tick writes <state>/spawn-hold.json while the load per core
# is above AGENT_HUB_SPAWN_HOLD_LOAD and deletes it below 80 % of it (hysteresis); `agent spawn` warns or refuses (exit 1)
# and --ignore-hold passes; an expired or unreadable file, an unset threshold and a resume (`agent send`) are never held.
# The load is faked (AGENT_HUB_WATCHDOG_LOAD=<load>:<cores>); stand-in CLIs only, no model, no launchctl/crontab.
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py
R=$AGENT_HUB_HOME; W=$R/w; mkdir -p $W $R/stage-a/agents; printf '# Brief: hold\n\nbody\n' > $W/b.md
export AGENT_HUB_WATCHDOG=on HOME=$R/home; mkdir -p $HOME
H=$R/.state/spawn-hold.json
tick(){ AGENT_HUB_WATCHDOG_LOAD=$1 "$B/watchdog" run "${@:2}" > $R/tick.out 2> $R/tick.err; }
field(){ python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])" $H $1; }
spawn(){ local r=$1; shift; $B/agent spawn --role $r --cwd $W --brief $W/b.md --model haiku "$@" > $R/$r.out 2> $R/$r.err; }
wait_dead(){ for i in $(seq 1 60); do $B/agent status $1 | grep -q 'ALIVE' || return 0; sleep 0.25; done; }
# a hold in force until the given offset (seconds from now): writes the file by hand, as the tick would
mkhold(){ python3 - "$H" "$1" <<'PY'
import datetime as dt, json, sys, os
t = dt.datetime.now(dt.timezone.utc)
os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
json.dump({"since": t.isoformat(timespec="seconds"), "load": 9.0, "cores": 4, "threshold": 1.5,
           "until": (t + dt.timedelta(seconds=int(sys.argv[2]))).isoformat(timespec="seconds")}, open(sys.argv[1], "w"))
PY
}

# ---- 1. the tick: threshold 1.5 per core, 4 cores (6.0 trips it; the hold ends below 1.2 per core = 4.8)
export AGENT_HUB_SPAWN_HOLD_LOAD=1.5
tick 8:4; check $? 0 "tick above the threshold"
[ -f $H ]; check $? 0 "…writes spawn-hold.json"
check "$(field load) $(field cores) $(field threshold)" "8.0 4 1.5" "…with the load, the cores and the threshold"
python3 - $H <<'PY'
import datetime as dt, json, sys
r = json.load(open(sys.argv[1])); s, u = (dt.datetime.fromisoformat(r[k]) for k in ("since", "until"))
sys.exit(0 if abs((u - s).total_seconds() - 600) < 5 else 1)   # 2 x the default 5 m interval
PY
check $? 0 "…valid for two intervals (until = now + 2 × AGENT_HUB_WATCHDOG_EVERY)"
S1=$(field since); sleep 1.2
tick 9:4; check "$(field since)" "$S1" "a second tick above the threshold keeps since"
check "$(field load)" 9.0 "…and refreshes the load"
tick 5:4; [ -f $H ]; check $? 0 "inside the hysteresis band (1.25 per core, 1.2–1.5): the hold stays"
check "$(field since)" "$S1" "…unchanged since"
tick 4.7:4; [ ! -f $H ]; check $? 0 "below 80 % of the threshold (1.175 per core): the hold is deleted"
tick 5:4; [ ! -f $H ]; check $? 0 "inside the band with no hold in force: none is written"
tick 6:4; [ ! -f $H ]; check $? 0 "exactly at the threshold (1.5 per core) is not above it"
tick 6.4:4; [ -f $H ]; check $? 0 "just above the threshold: written"
rm -f $H

# ---- 2. dry run, unset, invalid
tick 8:4 --dry-run; [ ! -f $H ]; check $? 0 "--dry-run above the threshold writes nothing"
grep -q '^\[plan\] machine: would hold spawns: load 8.00 on 4 cores' $R/tick.out; check $? 0 "…and says what it would do"
tick 8:4; tick 1:4 --dry-run; [ -f $H ]; check $? 0 "--dry-run below the threshold deletes nothing"
grep -q 'would release the spawn hold' $R/tick.out; check $? 0 "…and says it would release"
tick 1:4; [ ! -f $H ]; check $? 0 "(released by a real tick)"
tick 8:4; unset AGENT_HUB_SPAWN_HOLD_LOAD
tick 8:4; [ ! -f $H ]; check $? 0 "threshold unset: a leftover file is deleted"
tick 8:4; [ ! -f $H ]; check $? 0 "threshold unset, load 2 per core: nothing is written"
tick 8:4 --dry-run; grep -q 'plan.*nothing to do' $R/tick.out; check $? 0 "…and a dry run has nothing to say"
AGENT_HUB_SPAWN_HOLD_LOAD=lots tick 8:4; [ ! -f $H ]; check $? 0 "an invalid threshold counts as unset"
grep -q "AGENT_HUB_SPAWN_HOLD_LOAD='lots'.*the load hold is off" $R/tick.err; check $? 0 "…with a warning naming the setting"
AGENT_HUB_SPAWN_HOLD_LOAD=-2 tick 8:4; [ ! -f $H ]; check $? 0 "a threshold of zero or below counts as unset"
AGENT_HUB_SPAWN_HOLD_LOAD=nan tick 8:4; [ ! -f $H ]; check $? 0 "nan counts as unset"
echo '{"AGENT_HUB_SPAWN_HOLD_LOAD": "1.5"}' > $R/config.json
tick 8:4; [ -f $H ]; check $? 0 "the threshold from the hub home's config.json is honoured"
rm -f $R/config.json $H
export AGENT_HUB_SPAWN_HOLD_LOAD=1.5
AGENT_HUB_WATCHDOG=off tick 8:4; [ ! -f $H ]; check $? 0 "a watchdog that is off does nothing"
AGENT_HUB_WATCHDOG_LOAD= "$B/watchdog" run > $R/tick.out 2> $R/tick.err; check $? 0 "an unset fake load: the real load average is measured, the tick runs"
grep -q "machine: error" $R/tick.out; check $? 1 "…without an error line"
rm -f $H

# ---- 3. agent spawn
# 3a. no hold at all
spawn a1; check $? 0 "no hold file: spawn goes on"; wait_dead a1
grep -q 'spawn held' $R/a1.err; check $? 1 "…silently"
# 3b. a hold in force, the default action: warn
mkhold 300
spawn a2; check $? 0 "hold in force, default AGENT_HUB_SPAWN_HOLD: spawn goes on"; wait_dead a2
grep -q 'spawn held: machine load 9.00 on 4 cores (2.25 per core), above AGENT_HUB_SPAWN_HOLD_LOAD=1.5 since .*--ignore-hold' $R/a2.err; check $? 0 "…with a warning: the load, the cores, the threshold, --ignore-hold"
AGENT_HUB_SPAWN_HOLD=warn spawn a3; check $? 0 "AGENT_HUB_SPAWN_HOLD=warn: spawn goes on"; wait_dead a3
grep -q 'spawn held' $R/a3.err; check $? 0 "…with the warning"
AGENT_HUB_SPAWN_HOLD=sometimes spawn a4; check $? 0 "an invalid action counts as warn"; wait_dead a4
grep -q "AGENT_HUB_SPAWN_HOLD='sometimes'.*using warn" $R/a4.err; check $? 0 "…with a warning naming the setting"
# 3c. refuse
AGENT_HUB_SPAWN_HOLD=refuse spawn b1; check $? 1 "AGENT_HUB_SPAWN_HOLD=refuse: spawn exits 1"
grep -q 'spawn held: machine load 9.00 on 4 cores (2.25 per core), above AGENT_HUB_SPAWN_HOLD_LOAD=1.5.*--ignore-hold' $R/b1.err; check $? 0 "…naming the load, the cores, the threshold and --ignore-hold"
[ ! -e $R/stage-a/agents/b1 ]; check $? 0 "…and nothing was started"
AGENT_HUB_SPAWN_HOLD=refuse spawn b2 --ignore-hold; check $? 0 "--ignore-hold passes a refusal"; wait_dead b2
grep -q 'spawn held' $R/b2.err; check $? 1 "…silently"
spawn b3 --ignore-hold; grep -q 'spawn held' $R/b3.err; check $? 1 "--ignore-hold silences the warning"; wait_dead b3
# 3d. never held: a file that has expired, one that cannot be read, one of the wrong shape; a resume
mkhold -5
AGENT_HUB_SPAWN_HOLD=refuse spawn c1; check $? 0 "an expired hold file is ignored (even with refuse)"; wait_dead c1
echo 'not json {' > $H
AGENT_HUB_SPAWN_HOLD=refuse spawn c2; check $? 0 "an unreadable hold file is ignored"; wait_dead c2
echo '[1]' > $H
AGENT_HUB_SPAWN_HOLD=refuse spawn c3; check $? 0 "a hold file of the wrong shape is ignored"; wait_dead c3
echo '{"until": "never", "load": 1, "cores": 1}' > $H
AGENT_HUB_SPAWN_HOLD=refuse spawn c4; check $? 0 "a hold file with an unreadable until is ignored"; wait_dead c4
mkhold 300
AGENT_HUB_SPAWN_HOLD=refuse $B/agent send c1 "carry on" > $R/send.out 2> $R/send.err; check $? 0 "a resume (agent send) is never held"
grep -q 'spawn held' $R/send.err $R/send.out; check $? 1 "…and says nothing about the hold"; wait_dead c1

# ---- 4. the tick and the spawn together
rm -f $H; tick 12:4
AGENT_HUB_SPAWN_HOLD=refuse spawn d1; check $? 1 "a hold written by a tick refuses a spawn"
tick 1:4; AGENT_HUB_SPAWN_HOLD=refuse spawn d2; check $? 0 "…and the tick that releases it lets spawns through"; wait_dead d2
exit $fail
