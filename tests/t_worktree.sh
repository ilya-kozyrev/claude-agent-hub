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
# a worktree directory deleted by hand: the stale entry is pruned and the worktree made again
$B/agent spawn --role gone --cwd $REPO --model haiku --brief $P/b.md --worktree > /dev/null 2>&1; wait_dead gone
rm -rf $REPO/.worktrees/agent/gone
$B/agent spawn --role gone --cwd $REPO --model haiku --brief $P/b.md --worktree > $P/gone.out 2>&1; check $? 0 "re-spawn after the worktree directory was deleted by hand"
grep -q 'created' $P/gone.out && [ -d $REPO/.worktrees/agent/gone ]; check $? 0 "…prunes the stale entry and creates it again"
wait_dead gone
# a locked worktree whose directory is gone: prune keeps it, the spawn fails cleanly and names git worktree unlock
$B/agent spawn --role lk --cwd $REPO --model haiku --brief $P/b.md --worktree > /dev/null 2>&1; wait_dead lk
git -C $REPO worktree lock $REPO/.worktrees/agent/lk && rm -rf $REPO/.worktrees/agent/lk
$B/agent spawn --role lk --cwd $REPO --model haiku --brief $P/b.md --worktree > $P/lk.out 2>&1; check $? 1 "negative: a locked, missing worktree is a failure (exit 1)"
grep -q 'git worktree unlock' $P/lk.out && ! grep -q Traceback $P/lk.out; check $? 0 "…naming git worktree unlock, without a traceback"
(cd $P && GIT_DIR=$REPO/.git GIT_WORK_TREE=$REPO $B/agent spawn --role gd --cwd $P/plain --model haiku --brief $P/b.md --worktree) > /dev/null 2>&1; check $? 2 "GIT_DIR/GIT_WORK_TREE do not turn a non-repository --cwd into a repository"
$B/agent spawn --role nowt --cwd $REPO --model haiku --brief $P/b.md > /dev/null 2>&1; check $? 0 "control: without --worktree"
wait_dead nowt
check "$(meta nowt 'm["cwd"]')" "$(cd $REPO && pwd -P)" "…the agent runs in --cwd itself"
$B/agent status nowt | grep -q '; worktree '; check $? 1 "…and status names no worktree"
# ---- a new branch starts from origin's default branch, not from the commit --cwd has checked out
git init -q --bare $P/rem.git; git clone -q $P/rem.git $P/seed 2>/dev/null
G(){ git -c user.name=t -c user.email=t@t -c init.defaultBranch=main -c commit.gpgsign=false "$@"; }
( cd $P/seed && G checkout -q -b main 2>/dev/null; echo 1 > f && G add f && G commit -qm one && G push -q origin main 2>/dev/null )
git -C $P/rem.git symbolic-ref HEAD refs/heads/main
git clone -q $P/rem.git $P/clone 2>/dev/null
( cd $P/clone && G checkout -qb feat/foreign && echo f > foreign && G add foreign && G commit -qm foreign )   # the owner's clone
MAIN1=$(git -C $P/seed rev-parse HEAD); FOREIGN=$(git -C $P/clone rev-parse HEAD)
sp(){ local role=$1; shift; $B/agent spawn --role $role --cwd $P/clone --model haiku --brief $P/b.md "$@" > $P/$role.out 2>&1; local rc=$?; [ $rc = 0 ] && wait_dead $role; return $rc; }
sp fb --worktree; check $? 0 "spawn --worktree from a clone on a foreign feature branch"
check "$(git -C $P/clone/.worktrees/agent/fb rev-parse HEAD)" "$MAIN1" "…the new branch starts from origin/main, not from the clone's feature branch"
grep -q "worktree .*agent/fb on agent/fb (created from origin/main ${MAIN1:0:7})" $P/fb.out; check $? 0 "…the 'created' line names the base"
[ -z "$(git -C $P/clone/.worktrees/agent/fb config branch.agent/fb.remote)" ]; check $? 0 "…the branch tracks nothing"
( cd $P/seed && echo 2 >> f && G commit -qam two && G push -q origin main 2>/dev/null ); MAIN2=$(git -C $P/seed rev-parse HEAD)
sp fb2 --worktree fb2; check $? 0 "origin moved on: the next spawn fetches first"
check "$(git -C $P/clone/.worktrees/fb2 rev-parse HEAD)" "$MAIN2" "…the new branch is on the fetched origin/main"
sp fb3 --worktree fb3 --base HEAD; check $? 0 "--base HEAD"
check "$(git -C $P/clone/.worktrees/fb3 rev-parse HEAD)" "$FOREIGN" "…keeps the old behaviour: the checked-out commit of --cwd"
grep -q "(created from HEAD ${FOREIGN:0:7})" $P/fb3.out; check $? 0 "…and the line names it"
sp fb4 --worktree fb4 --base origin/main~1; check $? 0 "--base <any ref>"
check "$(git -C $P/clone/.worktrees/fb4 rev-parse HEAD)" "$MAIN1" "…starts from that ref"
sp fb5 --worktree fb5 --base nonsense; check $? 2 "negative: --base that is not a commit → usage error"
sp fb6 --base HEAD; check $? 2 "negative: --base without --worktree → usage error"
git -C $P/clone branch -q have origin/main~1
sp fb7 --worktree have --base HEAD; check $? 0 "an existing branch with --base"
check "$(git -C $P/clone/.worktrees/have rev-parse HEAD)" "$MAIN1" "…is used as it is, --base ignored"
grep -q "note: --base HEAD ignored: branch have exists" $P/fb7.out; check $? 0 "…with a note"
sp fb8 --worktree fb2; check $? 0 "an existing worktree with --base unchanged: re-spawn"
grep -q "(reused)" $P/fb8.out; check $? 0 "…is reused as before"
# fetch failing: the local origin/main is used, with a note
git clone -q $P/rem.git $P/offline 2>/dev/null; git -C $P/offline remote set-url origin $P/nonexistent.git
$B/agent spawn --role off --cwd $P/offline --model haiku --brief $P/b.md --worktree > $P/off.out 2>&1; check $? 0 "origin unreachable: spawn still works"; wait_dead off
grep -q "note: fetch of origin main failed" $P/off.out && grep -q "branching from the local origin/main" $P/off.out; check $? 0 "…with a note"
check "$(git -C $P/offline/.worktrees/agent/off rev-parse HEAD)" "$MAIN2" "…from the local origin/main (the last fetched)"
# no origin at all: the local default branch (the repository of the first part), and the line says so
G -C $REPO checkout -q -b somefeature; G -C $REPO commit -q --allow-empty -m "feature commit"
MAINSHA=$(git -C $REPO rev-parse main)
$B/agent spawn --role nr --cwd $REPO --model haiku --brief $P/b.md --worktree > $P/nr.out 2>&1; check $? 0 "no origin: spawn works"; wait_dead nr
check "$(git -C $REPO/.worktrees/agent/nr rev-parse HEAD)" "$MAINSHA" "…the new branch starts from the local main, not from the checked-out feature branch"
grep -q "note: .*has no origin/main: branching from the local main" $P/nr.out && grep -q "(created from main ${MAINSHA:0:7})" $P/nr.out; check $? 0 "…with a note, and the line names the base"
exit $fail
