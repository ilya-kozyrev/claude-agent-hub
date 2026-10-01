#!/bin/bash
# agent spawn --worktree [BRANCH]: the agent runs in <repo>/.claude/worktrees/<role> on its own branch; a re-spawn
# reuses it; a path on another branch or a non-repository is refused. Against the stand-in CLI (fake_claude.py).
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py
R=$AGENT_HUB_HOME; P=$(mktemp -d); REPO=$P/app; mkdir -p $P/plain
git init -q -b main $REPO && git -C $REPO -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
echo "brief: do the thing" > $P/b.md
wait_dead(){ for i in $(seq 1 40); do $B/agent status $1 | grep -q 'ALIVE' || return 0; sleep 0.5; done; }
meta(){ python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(eval(sys.argv[2]))" $R/stage-a/agents/$1/meta.json "$2"; }

$B/agent spawn --role builder --cwd $REPO --model haiku --brief $P/b.md --worktree > $P/s1.out 2>&1; check $? 0 "spawn --worktree"
wait_dead builder
WT=$REPO/.claude/worktrees/builder
check "$(git -C $WT rev-parse --abbrev-ref HEAD 2>/dev/null)" "agent/builder" "worktree on agent/<role>"
check "$(meta builder 'm["cwd"]')" "$(cd $WT && pwd -P)" "the agent's cwd is the worktree"
check "$(meta builder 'm["worktree"]["branch"]')" "agent/builder" "meta records the worktree"
[ -s $WT/prompts.log ] && [ ! -e $REPO/prompts.log ]; check $? 0 "the CLI ran in the worktree, not in the main checkout"
grep -q 'worktree .*\.claude/worktrees/builder (agent/builder)' $(journal stage-a); check $? 0 "the start line names the worktree"
echo "work" > $WT/file.txt
$B/agent spawn --role builder --cwd $REPO --model haiku --brief $P/b.md --worktree > $P/s2.out 2>&1; check $? 0 "re-spawn with the same role"
grep -q 'reused' $P/s2.out && [ -f $WT/file.txt ]; check $? 0 "…reuses the worktree and keeps its files"
wait_dead builder
$B/agent spawn --role fixer --cwd $REPO --model haiku --brief $P/b.md --worktree fix/login > /dev/null 2>&1; check $? 0 "spawn --worktree BRANCH"
check "$(git -C $REPO/.claude/worktrees/fixer rev-parse --abbrev-ref HEAD)" "fix/login" "…on the named branch"
wait_dead fixer
git -C $REPO branch -q existing
$B/agent spawn --role ex --cwd $REPO --model haiku --brief $P/b.md --worktree existing > /dev/null 2>&1; check $? 0 "an existing branch is checked out, not recreated"
wait_dead ex
$B/agent spawn --role builder --cwd $REPO --model haiku --brief $P/b.md --worktree other > $P/s3.out 2>&1; check $? 1 "negative: the role's worktree is on another branch"
$B/agent spawn --role p --cwd $P/plain --model haiku --brief $P/b.md --worktree > /dev/null 2>&1; check $? 2 "negative: --worktree outside a git repository"
$B/agent spawn --role bad --cwd $REPO --model haiku --brief $P/b.md --worktree 'a..b' > /dev/null 2>&1; check $? 2 "negative: a bad branch name"
$B/agent spawn --role nowt --cwd $REPO --model haiku --brief $P/b.md > /dev/null 2>&1; check $? 0 "control: without --worktree"
wait_dead nowt
check "$(meta nowt 'm["cwd"]')" "$(cd $REPO && pwd -P)" "…the agent runs in --cwd itself"
exit $fail
