#!/bin/bash
# Generic lock resources: only main-merge is built in; every other resource comes from lock-rules.json.
# `lock rules init|add|check|show` (the setup flow's tools), `lock take` refusing an unknown resource, old board
# records of any kind still parsing. Positive and negative controls for each.
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME
P=$(mktemp -d); APP=$P/shop; LIB=$P/textlib; OUT=$P/outside
mkdir -p $OUT
for d in $APP $LIB; do git init -q -b main $d; done
ME=aaaaaaaa-0000-4000-8000-000000000001; OTHER=bbbbbbbb-0000-4000-8000-000000000002
export CLAUDE_CODE_SESSION_ID=$ME

# ---- built-ins only
(cd $OUT && $B/lock rules) > $P/show0.out; check $? 0 "rules show with no file"
grep -q '^  main-merge' $P/show0.out && [ "$(grep -c '^  [a-z]' $P/show0.out)" = 1 ]; check $? 0 "…lists main-merge only"
(cd $OUT && $B/lock take deploy-window --until +1h --why x) > /dev/null 2> $P/unk.err; check $? 2 "negative: take of an unconfigured resource is refused"
grep -q "Known: main-merge" $P/unk.err; check $? 0 "…and the refusal lists the known resources"

# ---- a project with no deployment: init only, main-merge is the only resource
(cd $LIB && $B/lock rules init) > $P/init.out; check $? 0 "init in a repository without deployment"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d=={"protected_branches":["main"],"resources":{},"rules":[]}, d' $LIB/.agent-hub/lock-rules.json; check $? 0 "…writes an empty rules file with main protected"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["AGENT_HUB_DEFAULT_REPO"]=="textlib"' $LIB/.agent-hub/config.json; check $? 0 "…and config.json with the repository name"
(cd $LIB && $B/lock rules init) > $P/init2.out; grep -q 'left as it is' $P/init2.out; check $? 0 "init again: nothing overwritten"
(cd $LIB && $B/lock rules check "git push origin main" --expect main-merge) > /dev/null; check $? 0 "positive: push to main is guarded by main-merge"
(cd $LIB && $B/lock rules check "make deploy" --expect-none) > /dev/null; check $? 0 "negative: nothing else is guarded"
(cd $LIB && $B/lock rules check "make deploy" --expect main-merge) > /dev/null 2>&1; check $? 1 "control: a wrong expectation fails the check"

# ---- a project with deployment: resources and rules added by the setup flow
cd $APP
$B/lock rules init --protected main release > /dev/null; check $? 0 "init with two protected branches"
$B/lock rules add deploy-window --about "a production rollout is in progress" \
  --match '^make deploy-prod\b' --action "production deploy" > /dev/null; check $? 0 "add a resource with a rule"
$B/lock rules add staging --about "the shared staging environment" \
  --match '^helm upgrade\b.* -n staging\b' --action "staging rollout" > /dev/null; check $? 0 "add a second resource"
$B/lock rules add migration-head --about "expected head of the migration chain" > /dev/null; check $? 0 "add an informational resource (no rule)"
$B/lock rules add staging --match '^make refresh-staging\b' > /dev/null; check $? 0 "add a rule to a known resource without --about"
$B/lock rules add brand-new > /dev/null 2>&1; check $? 2 "negative: a new resource needs --about"
$B/lock rules add Bad_Name --about x > /dev/null 2>&1; check $? 2 "negative: a bad resource name"
$B/lock rules add main-merge --about x > /dev/null 2>&1; check $? 2 "negative: main-merge is built in"
cp .agent-hub/lock-rules.json $P/before.json
$B/lock rules add staging --match '^make (oops' > /dev/null 2> $P/badrx.err; check $? 2 "negative: a bad regex is refused"
cmp -s .agent-hub/lock-rules.json $P/before.json && [ ! -e .agent-hub/.lock-rules.check.json ]; check $? 0 "…and the file is left as it was"
$B/lock rules check "make deploy-prod" --expect deploy-window > $P/c1.out; check $? 0 "positive: the deploy is guarded by deploy-window"
grep -q 'guarded by deploy-window: production deploy' $P/c1.out; check $? 0 "…and the check names the action"
$B/lock rules check "helm upgrade web ./chart -n staging" --expect staging > /dev/null; check $? 0 "positive: the staging rollout is guarded by staging"
$B/lock rules check "make refresh-staging" --expect staging > /dev/null; check $? 0 "positive: the added rule of a known resource"
$B/lock rules check "git push origin release" --expect main-merge > /dev/null; check $? 0 "positive: a configured protected branch"
$B/lock rules check "make test" --expect-none > /dev/null; check $? 0 "negative: an ordinary command is not guarded"
$B/lock rules check "helm upgrade web ./chart -n prod" --expect-none > /dev/null; check $? 0 "negative: a rollout elsewhere is not guarded"
[ ! -e $R/board.md ]; check $? 0 "the checks never touch the real board"
$B/lock rules show --json | python3 -c 'import json,sys; d=json.load(sys.stdin); n=[r["name"] for r in d["resources"]]; assert n==["main-merge","deploy-window","staging","migration-head"], n; assert [r["guards"] for r in d["resources"] if r["name"]=="migration-head"]==[[]]'
check $? 0 "show --json: built-in first, then the project's, informational has no guards"

# ---- take/release with project resources
CLAUDE_CODE_SESSION_ID=$OTHER $B/lock take staging --until +1h --why "load test" --owner-name "perf" > /dev/null; check $? 0 "take a configured resource inside the repository"
grep -q '"kind": "staging", "repo": "shop"' $R/board.md; check $? 0 "…recorded on the repository from config.json"
$B/lock take migration-head --until +1h --why "0042" --value 0042 > /dev/null; check $? 0 "take an informational resource"
python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","session_id":sys.argv[1],"cwd":sys.argv[2],"tool_input":{"command":"helm upgrade web ./c -n staging"}}))' $ME $APP \
  | python3 $HOOKS/board_locks.py | grep -q '"deny"'; check $? 0 "the real hook denies the staging rollout under perf's lock"
python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","session_id":sys.argv[1],"cwd":sys.argv[2],"tool_input":{"command":"helm upgrade web ./c -n staging"}}))' $OTHER $APP \
  | python3 $HOOKS/board_locks.py | grep -q '"deny"'; check $? 1 "negative: the holder passes"
cd $OUT
$B/lock take staging --until +1h --why x > /dev/null 2>&1; check $? 0 "a resource already on the board is takeable anywhere (handover)"
$B/lock take deploy-window --until +1h --why x > /dev/null 2>&1; check $? 2 "negative: outside the repository its resources (not on the board) are unknown"

# ---- declared resources catch a typo in a rule
mkdir -p $P/typo/.agent-hub; git init -q $P/typo
printf '{"resources": {"deploy-window": "prod"}, "rules": [{"match": "^make ship\\\\b", "kinds": ["deploy-windw"]}]}\n' > $P/typo/.agent-hub/lock-rules.json
(cd $P/typo && $B/lock rules show) > /dev/null 2> $P/typo.err; grep -q "deploy-windw.*not declared" $P/typo.err; check $? 0 "a rule naming an undeclared resource: the file is refused with a reason"
python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","session_id":"x","cwd":sys.argv[1],"tool_input":{"command":"git push origin main"}}))' $P/typo \
  | python3 $HOOKS/board_locks.py 2>/dev/null | grep -q systemMessage; check $? 0 "…and the hook warns on every Bash call"

# ---- old records of any kind keep parsing
python3 - "$R/board.md" <<'PY'
import json, sys
recs = [{"kind": k, "repo": "*", "owner_name": "old hub", "session_id": "cccccccc-0000-4000-8000-000000000003",
         "until": "2099-01-01T00:00:00+00:00", "why": "legacy"} for k in ("stage", "deploy-window", "migration-head")]
open(sys.argv[1], "w").write("# board\n\n```locks\n" + "\n".join(json.dumps(r) for r in recs) + "\n```\n")
PY
$B/lock list > $P/legacy.out; check $? 0 "a board with legacy kinds parses"
[ "$(grep -c 'old hub' $P/legacy.out)" = 3 ]; check $? 0 "…and lists all three records"
$B/lock take stage --until +1h --why "successor" --force > /dev/null; check $? 0 "a legacy resource on the board can be taken over"

# ---- review fixes: worktrees see the main checkout's .agent-hub/; add extends a file without "resources"; init from
#      a worktree configures the main checkout; relative AGENT_HUB_SCOPE_DIRS are refused
cd $APP && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m init && git worktree add -q -b wt-b $APP/.worktrees/wt-b
(cd $APP/.worktrees/wt-b && $B/lock rules check "make deploy-prod" --expect deploy-window) > /dev/null; check $? 0 "a worktree without .agent-hub/ uses the main checkout's rules"
python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","session_id":sys.argv[1],"cwd":sys.argv[2],"tool_input":{"command":"make deploy-prod"}}))' $ME $APP/.worktrees/wt-b \
  | python3 $HOOKS/board_locks.py | grep -q '"deny"'; check $? 0 "…and the real hook denies there under another session's lock"
mkdir -p $APP/.worktrees/wt-b/.agent-hub && echo '{"rules": []}' > $APP/.worktrees/wt-b/.agent-hub/lock-rules.json
(cd $APP/.worktrees/wt-b && $B/lock rules check "make deploy-prod" --expect-none) > /dev/null; check $? 0 "…but a worktree's own .agent-hub/ wins"
rm -rf $APP/.worktrees/wt-b/.agent-hub
git init -q $P/sub-host && git init -q $P/sub-host/inner && mkdir -p $P/sub-host/.agent-hub && echo '{"rules": []}' > $P/sub-host/.agent-hub/lock-rules.json
python3 -c "import sys; sys.path.insert(0, '$B'); import hubcore; print(hubcore.project_dir('$P/sub-host/inner'))" | grep -qx None; check $? 0 "control: a nested repository does not inherit its host's config"
mkdir -p $P/old/.agent-hub; git init -q $P/old
printf '{"rules": [{"match": "^make ship\\\\b", "kinds": ["deploy-window"]}, {"match": "^make stg\\\\b", "kinds": ["stage"]}]}\n' > $P/old/.agent-hub/lock-rules.json
(cd $P/old && $B/lock rules add stage --about "staging" --match '^make stg2\b') > /dev/null 2>&1; check $? 0 "add extends a file without resources (0.2.0 style)"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert set(d["resources"])=={"deploy-window","stage"} and len(d["rules"])==3, d' $P/old/.agent-hub/lock-rules.json; check $? 0 "…declaring the names its rules already use"
git init -q -b main $P/fresh && git -C $P/fresh -c user.email=t@t -c user.name=t commit -q --allow-empty -m i && git -C $P/fresh worktree add -q -b w $P/fresh/.worktrees/w
(cd $P/fresh/.worktrees/w && $B/lock rules init) > /dev/null; check $? 0 "init from a worktree"
[ -f $P/fresh/.agent-hub/lock-rules.json ] && [ ! -e $P/fresh/.worktrees/w/.agent-hub ]; check $? 0 "…configures the main checkout"
echo '{"AGENT_HUB_SCOPE_DIRS": "relative/dir"}' > $R/config.json
(cd $P && python3 -c "import sys; sys.path.insert(0, '$B'); import hubcore; print(hubcore.in_scope('$P/relative/dir/x'))") > $P/scope.out 2> $P/scope.err
grep -qx False $P/scope.out && grep -q "not an absolute path" $P/scope.err; check $? 0 "a relative AGENT_HUB_SCOPE_DIRS entry is ignored with a warning"
rm $R/config.json
exit $fail
