#!/bin/bash
# agent spawn --worktree [BRANCH]: the agent runs in a worktree of its branch — an existing one is reused wherever it
# is, else <repo>/.worktrees/<branch> (excluded in .git/info/exclude); status and stop name it; a branch of the main
# checkout, a foreign path, a non-repository and a bad name are refused. Against the stand-in CLI (fake_claude.py).
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py
R=$AGENT_HUB_HOME; P=$(mktemp -d); REPO=$P/app; mkdir -p $P/plain
git init -q -b main $REPO && git -C $REPO -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
echo "brief: do the thing" > $P/b.md
wait_dead(){ for i in $(seq 1 40); do $B/agent status $1 | grep -q 'ALIVE' || return 0; sleep 0.5; done; }
meta(){ python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(eval(sys.argv[2]))" $R/stage-a/agents/$1/meta.json "$2"; }

$B/agent spawn --role builder --cwd $REPO --model haiku --brief $P/b.md --worktree > $P/s1.out 2>&1; check $? 0 "spawn --worktree"
wait_dead builder
WT=$REPO/.worktrees/agent/builder
check "$(git -C $WT rev-parse --abbrev-ref HEAD 2>/dev/null)" "agent/builder" "worktree <repo>/.worktrees/agent/<role> on agent/<role>"
check "$(meta builder 'm["cwd"]')" "$(cd $WT && pwd -P)" "the agent's cwd is the worktree"
check "$(meta builder 'm["worktree"]["branch"]')" "agent/builder" "meta records the worktree"
[ -s $WT/prompts.log ] && [ ! -e $REPO/prompts.log ]; check $? 0 "the CLI ran in the worktree, not in the main checkout"
grep -q 'worktree .*\.worktrees/agent/builder (agent/builder)' $(journal stage-a); check $? 0 "the start line names the worktree"
grep -qx '/.worktrees/' $REPO/.git/info/exclude; check $? 0 ".worktrees/ is excluded in .git/info/exclude"
[ -z "$(git -C $REPO status --porcelain)" ]; check $? 0 "…so the main checkout shows nothing untracked"
$B/agent status builder | grep -q "; worktree .*agent/builder (agent/builder)"; check $? 0 "status names the worktree"
echo "work" > $WT/file.txt
$B/agent spawn --role builder --cwd $REPO --model haiku --brief $P/b.md --worktree > $P/s2.out 2>&1; check $? 0 "re-spawn with the same role"
grep -q 'reused' $P/s2.out && [ -f $WT/file.txt ]; check $? 0 "…reuses the worktree and keeps its files"
wait_dead builder
$B/agent stop builder > $P/stop.out 2>&1; grep -q 'git worktree remove .*agent/builder' $P/stop.out; check $? 0 "stop names the worktree and how to remove it"
[ -d $WT ]; check $? 0 "…and leaves it in place"
[ "$(grep -c '/.worktrees/' $REPO/.git/info/exclude)" = 1 ]; check $? 0 "the exclude line is written once"
$B/agent spawn --role fixer --cwd $REPO --model haiku --brief $P/b.md --worktree fix/login > /dev/null 2>&1; check $? 0 "spawn --worktree BRANCH"
check "$(git -C $REPO/.worktrees/fix/login rev-parse --abbrev-ref HEAD)" "fix/login" "…in .worktrees/<branch>"
wait_dead fixer
# a worktree of the branch made by hand elsewhere is reused, not duplicated
git -C $REPO worktree add -q -b hand $P/hand-wt
$B/agent spawn --role h --cwd $REPO --model haiku --brief $P/b.md --worktree hand > /dev/null 2>&1; check $? 0 "a branch with a worktree elsewhere"
check "$(meta h 'm["cwd"]')" "$(cd $P/hand-wt && pwd -P)" "…reuses that worktree"
wait_dead h
# spawned from inside a worktree: the new one still goes under the main repository
$B/agent spawn --role inner --cwd $WT --model haiku --brief $P/b.md --worktree > /dev/null 2>&1; check $? 0 "spawn from inside a worktree"
[ -d $REPO/.worktrees/agent/inner ]; check $? 0 "…lands in the main repository's .worktrees/"
wait_dead inner
git -C $REPO branch -q existing
$B/agent spawn --role ex --cwd $REPO --model haiku --brief $P/b.md --worktree existing > /dev/null 2>&1; check $? 0 "an existing branch is checked out, not recreated"
wait_dead ex
$B/agent spawn --role m --cwd $REPO --model haiku --brief $P/b.md --worktree main > /dev/null 2>&1; check $? 2 "negative: the main checkout's branch is refused"
mkdir -p $REPO/.worktrees/taken
$B/agent spawn --role t --cwd $REPO --model haiku --brief $P/b.md --worktree taken > /dev/null 2>&1; check $? 1 "negative: a foreign directory at the path"
$B/agent spawn --role p --cwd $P/plain --model haiku --brief $P/b.md --worktree > /dev/null 2>&1; check $? 2 "negative: --worktree outside a git repository"
$B/agent spawn --role bad --cwd $REPO --model haiku --brief $P/b.md --worktree 'a..b' > /dev/null 2>&1; check $? 2 "negative: a bad branch name"
$B/agent spawn --role nowt --cwd $REPO --model haiku --brief $P/b.md > /dev/null 2>&1; check $? 0 "control: without --worktree"
wait_dead nowt
check "$(meta nowt 'm["cwd"]')" "$(cd $REPO && pwd -P)" "…the agent runs in --cwd itself"
$B/agent status nowt | grep -q 'worktree'; check $? 1 "…and status names no worktree"
exit $fail
