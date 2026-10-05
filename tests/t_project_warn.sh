#!/bin/bash
# agent spawn --cwd warns (ATTENTION, never a refusal) about a working directory outside git and about a checkout without
# .agent-hub/ while the remote default branch has it; nothing in a normal checkout. Real git repos. (hub start and hub
# takeover do not warn about these: they move the session to a fresh worktree, see t_location.sh.)
. "$(dirname "$0")/lib.sh"
unset AGENT_HUB_NO_PROJECT
new_home; export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py; R=$AGENT_HUB_HOME
G=$(mktemp -d); cd $G
git(){ command git -c user.name=t -c user.email=t@t -c init.defaultBranch=main -c protocol.file.allow=always "$@"; }
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
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
echo "brief" > $G/b.md
sp(){ $B/agent spawn --role "$2" --cwd "$1" --model haiku --brief $G/b.md 2>&1; $B/agent stop "$2" >/dev/null 2>&1; }
out=$(sp $G/bad p1); echo "$out" | grep -q '^ATTENTION: the checkout .*/bad on branch feat has no .agent-hub/'; check $? 0 "agent spawn --cwd in such a checkout → ATTENTION"
echo "$out" | grep -q 'started\|spawned\|CLI'; check $? 0 "…and the agent is still started"
out=$(sp $G/nogit p2); echo "$out" | grep -q '^ATTENTION: no project folder'; check $? 0 "agent spawn --cwd outside git → ATTENTION"
out=$(sp $G/ok p3); echo "$out" | grep -q 'ATTENTION: \(the checkout\|no project folder\)'; check $? 1 "negative: agent spawn --cwd in a normal checkout → none"
exit $fail
