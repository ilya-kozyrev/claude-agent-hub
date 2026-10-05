#!/bin/bash
# hub start / hub takeover / agent spawn warn (ATTENTION, never a refusal) about a working directory outside git and about
# a checkout without .agent-hub/ while the remote default branch has it; nothing in a normal checkout. Real git repos.
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py; R=$AGENT_HUB_HOME
G=$(mktemp -d); cd $G
git(){ command git -c user.name=t -c user.email=t@t -c init.defaultBranch=main -c protocol.file.allow=always "$@"; }
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
H1=11111111-1111-4111-8111-111111111111
# a remote that has .agent-hub/ on main, and one that has not
git init -q --bare rem.git; git clone -q rem.git seed 2>/dev/null
mkdir seed/.agent-hub; echo '{}' > seed/.agent-hub/config.json; echo x > seed/f
( cd seed && git add -A && git commit -qm init && git push -q origin main 2>/dev/null )
git init -q --bare plain-rem.git; git clone -q plain-rem.git plainseed 2>/dev/null
( cd plainseed && echo x > f && git add -A && git commit -qm init && git push -q origin main 2>/dev/null )
git clone -q rem.git ok 2>/dev/null                                             # normal checkout: has .agent-hub/
git clone -q rem.git bad 2>/dev/null; ( cd bad && git checkout -qb feat && git rm -rqf .agent-hub && git commit -qm drop )
git clone -q plain-rem.git noremote-cfg 2>/dev/null                              # remote without .agent-hub/ either
git init -q local; ( cd local && echo x > f && git add -A && git commit -qm init )   # no remote at all
mkdir -p nogit/sub
for d in ok bad noremote-cfg local nogit; do mkdir -p $R/web-$d; done
start(){ ( cd $1 && $B/hub start --stage web-$1 --session $H1 --dry-run 2>&1 ); }
# (b) the checkout lacks .agent-hub/, origin/main has it
out=$(start bad); echo "$out" | grep -q '^ATTENTION: the checkout .*/bad on branch feat has no .agent-hub/ but origin/main has it.*run from a worktree of origin/main'; check $? 0 "start: checkout without .agent-hub/ while origin/main has it → ATTENTION"
echo "$out" | grep -c 'ATTENTION: the checkout' | grep -q '^2$'; check $? 0 "…in the output and in the digest"
out=$(cd bad && $B/hub takeover --stage web-bad --session $H1 --dry-run 2>&1); echo "$out" | grep -q '^ATTENTION: the checkout .* has no .agent-hub/'; check $? 0 "takeover: the same warning"
echo "$out" | grep -q '^DIGEST'; check $? 0 "…and it is a warning, not a refusal"
out=$( cd bad && mkdir -p deep && cd deep && $B/hub start --stage web-bad --session $H1 --dry-run 2>&1 ); echo "$out" | grep -q 'ATTENTION: the checkout .*/bad on branch feat'; check $? 0 "…from a subdirectory of the checkout too"
# no warning
out=$(start ok); echo "$out" | grep -q 'ATTENTION: \(the checkout\|no project folder\)'; check $? 1 "negative: a normal checkout with .agent-hub/ → no project warning"
echo "$out" | grep -q '^DIGEST'; check $? 0 "…control: the command ran"
out=$(start noremote-cfg); echo "$out" | grep -q 'ATTENTION: \(the checkout\|no project folder\)'; check $? 1 "negative: the remote has no .agent-hub/ either → no warning"
out=$(start local); echo "$out" | grep -q 'ATTENTION: \(the checkout\|no project folder\)'; check $? 1 "negative: a repository without a remote → silent"
# (a) not inside git
out=$(start nogit); echo "$out" | grep -q "^ATTENTION: no project folder: .*/nogit is not inside a git repository.*No folder.*project's folder group"; check $? 0 "start outside a git repository → 'no project folder'"
out=$(cd nogit/sub && $B/hub takeover --stage web-nogit --session $H1 --dry-run 2>&1); echo "$out" | grep -q '^ATTENTION: no project folder'; check $? 0 "takeover outside git → the same"
# a linked worktree of the dropped branch: the main checkout has no .agent-hub/ either, the warning stays
( cd bad && git worktree add -q ../bad-wt -b wt 2>/dev/null ); out=$(cd bad-wt && $B/hub start --stage web-bad --session $H1 --dry-run 2>&1); echo "$out" | grep -q 'ATTENTION: the checkout'; check $? 0 "a worktree of a checkout without .agent-hub/ → warned"
( cd ok && git worktree add -q ../ok-wt -b wt2 origin/main 2>/dev/null ); out=$(cd ok-wt && $B/hub start --stage web-ok --session $H1 --dry-run 2>&1); echo "$out" | grep -q 'ATTENTION: \(the checkout\|no project folder\)'; check $? 1 "negative: a worktree of origin/main → no warning"
# git cannot run: silent
out=$(cd bad && PATH=$(dirname $(command -v python3)):/nonexistent $B/hub start --stage web-bad --session $H1 --dry-run 2>&1); echo "$out" | grep -q 'ATTENTION: \(the checkout\|no project folder\)'; check $? 1 "negative: no git on PATH → silent"
# agent spawn --cwd
echo "brief" > $G/b.md
sp(){ $B/agent spawn --role "$2" --cwd "$1" --model haiku --brief $G/b.md 2>&1; $B/agent stop "$2" >/dev/null 2>&1; }
out=$(sp $G/bad p1); echo "$out" | grep -q '^ATTENTION: the checkout .*/bad on branch feat has no .agent-hub/'; check $? 0 "agent spawn --cwd in such a checkout → ATTENTION"
echo "$out" | grep -q 'started\|spawned\|CLI'; check $? 0 "…and the agent is still started"
out=$(sp $G/nogit p2); echo "$out" | grep -q '^ATTENTION: no project folder'; check $? 0 "agent spawn --cwd outside git → ATTENTION"
out=$(sp $G/ok p3); echo "$out" | grep -q 'ATTENTION: \(the checkout\|no project folder\)'; check $? 1 "negative: agent spawn --cwd in a normal checkout → none"
exit $fail
