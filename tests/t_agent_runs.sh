#!/bin/bash
# Runs of a headless agent: `agent send` signs its journal line with the caller's tag (HUB_TAG, the registry entry of
# the calling session, else `cli`), never a hard-coded `hub`; status and agent-top show the last run's turns next to
# the total; `agent spawn --worktree` in a repository with no commits fails with a clear message. Stand-in CLI.
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a CLAUDE_BIN=$T/fake_claude.py
R=$AGENT_HUB_HOME; P=$(mktemp -d); W=$P/w; mkdir -p $W; echo "brief: do the thing" > $W/b.md
wait_dead(){ for i in $(seq 1 40); do $B/agent status $1 | grep -q 'ALIVE' || return 0; sleep 0.5; done; }
last_line(){ grep -F "$1" $(journal stage-a) | tail -1; }

# ---- 3. the tag of an `agent send` line
H1=11111111-1111-4111-8111-111111111111
FAKE_HOLD=6 $B/agent spawn --role probe --cwd $W --model haiku --brief $W/b.md > /dev/null 2>&1; check $? 0 "spawn from a shell without a role"
$B/agent send probe "alive one" > /dev/null; check $? 0 "send to a running agent"
last_line '@probe alive one' | grep -q '^- [0-9:]* \[cli\] @probe alive one'; check $? 0 "…is signed [cli], not [hub]"
wait_dead probe
$B/agent send probe "resume one" > /dev/null; check $? 0 "send to a finished agent (resume)"
last_line '@probe (session resumed' | grep -q '^- [0-9:]* \[cli\] @probe (session resumed'; check $? 0 "…is signed [cli] too"
wait_dead probe
HUB_TAG=ahub-pr9 $B/agent send probe "tagged one" > /dev/null
last_line '@probe (session resumed' | grep -q '\[ahub-pr9\] @probe (session resumed.*tagged one'; check $? 0 "HUB_TAG names the caller"
wait_dead probe
$B/roles --stage stage-a set hub $H1 --tag hub-4 > /dev/null; check $? 0 "a hub registered in the roles registry"
CLAUDE_CODE_SESSION_ID=$H1 $B/agent send probe "from the hub" > /dev/null
last_line '@probe (session resumed' | grep -q '\[hub-4\] @probe (session resumed.*from the hub'; check $? 0 "the hub keeps its hub-<N> tag (registry lookup of its session)"
wait_dead probe
FAKE_HOLD=6 $B/agent spawn --role live2 --cwd $W --model haiku --brief $W/b.md > /dev/null 2>&1
CLAUDE_CODE_SESSION_ID=$H1 $B/agent send live2 "hub to alive" > /dev/null
last_line '@live2 hub to alive' | grep -q '\[hub-4\] @live2 hub to alive'; check $? 0 "…also for a message to a running agent"
$B/agent stop live2 > /dev/null; $B/agent stop probe > /dev/null

# ---- 4. turns: the last run's next to the total
FAKE_TURNS=4 $B/agent spawn --role turns --cwd $W --model sonnet --brief $W/b.md > /dev/null 2>&1; check $? 0 "spawn an agent that works 5 turns"
wait_dead turns
$B/agent status turns | grep -q '; turns 5; last:'; check $? 0 "one run: status shows plain turns 5"
FAKE_TURNS=2 $B/agent send turns "go on" > /dev/null; check $? 0 "resume it for 3 more turns"
wait_dead turns
$B/agent status turns | grep -q '; turns 3 (total 8); last:'; check $? 0 "status: turns 3 (total 8)"
grep -q 'EXIT turns: .*turns 3 (total 8)' $(journal stage-a); check $? 0 "the EXIT line says the same"
$B/agent-top --json --stage stage-a > $P/top.json 2>&1
python3 -c 'import json,sys; a={x["role"]:x for x in json.load(open(sys.argv[1]))["agents"]}["turns"]; assert (a["run_turns"], a["turns"])==(3, 8), a' $P/top.json; check $? 0 "agent-top --json: run_turns 3, turns 8"
$B/agent-top --once --stage stage-a --width 120 > $P/top.out 2>&1
grep -E '^. turns ' $P/top.out | grep -q ' 3/8 '; check $? 0 "agent-top --once: the TURN column reads 3/8"
$B/agent-top --once --stage stage-a --agent turns --width 120 > $P/card.out 2>&1
grep -q 'turns 3 (total 8)' $P/card.out; check $? 0 "agent-top card: turns 3 (total 8)"
$B/agent-top --widget --stage stage-a > $P/widget.html 2>&1
grep -q '3 turns (total 8)' $P/widget.html; check $? 0 "agent-top widget: 3 turns (total 8)"
FAKE_TURNS=0 $B/agent spawn --role single --cwd $W --model haiku --brief $W/b.md > /dev/null 2>&1; wait_dead single
$B/agent-top --once --stage stage-a --width 120 > $P/top2.out 2>&1
grep -E '^. single ' $P/top2.out | grep -Eq ' 1 '; check $? 0 "negative: an agent of one run keeps a plain TURN cell"
grep -E '^. single ' $P/top2.out | grep -q '/'; check $? 1 "…without a slash"

# ---- 5. --worktree in a repository with no commits
git init -q -b main $P/empty
$B/agent spawn --role first --cwd $P/empty --model haiku --brief $W/b.md --worktree > $P/e1.out 2>&1; check $? 1 "spawn --worktree in a repository with no commits fails"
grep -q 'the repository .* has no commits yet — make a first commit' $P/e1.out; check $? 0 "…saying the repository has no commits yet"
[ ! -e $P/empty/.worktrees ] && [ ! -e $R/stage-a/agents/first ] && ! grep -q worktrees $P/empty/.git/info/exclude 2>/dev/null; check $? 0 "…and leaves no worktree, agent directory or exclude line behind"
$B/agent spawn --role nowt --cwd $P/empty --model haiku --brief $W/b.md > /dev/null 2>&1; check $? 0 "positive control: without --worktree an empty repository is fine"
wait_dead nowt
git -C $P/empty -c user.email=t@t -c user.name=t commit -q --allow-empty -m "first commit"
$B/agent spawn --role first --cwd $P/empty --model haiku --brief $W/b.md --worktree > $P/e2.out 2>&1; check $? 0 "positive control: after the first commit the same spawn works"
[ -d $P/empty/.worktrees/agent/first ]; check $? 0 "…in .worktrees/agent/first"
wait_dead first
exit $fail
