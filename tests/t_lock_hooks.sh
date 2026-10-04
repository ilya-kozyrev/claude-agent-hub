#!/bin/bash
# lock CLI and the three hooks: board_locks (PreToolUse Bash), handoff_size (PreToolUse Write|Edit),
# questions (SessionStart). Positive and negative controls for every decision.
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME
ME=aaaaaaaa-0000-4000-8000-000000000001; OTHER=bbbbbbbb-0000-4000-8000-000000000002
# ---- lock CLI
CLAUDE_CODE_SESSION_ID=$ME $B/lock take stage --until +1h --why x > $R/unknown.out 2>&1; check $? 2 "negative: a resource no lock-rules.json names is refused"
grep -q "unknown resource 'stage'.*Known: main-merge" $R/unknown.out; check $? 0 "…with the list of known resources"
printf '{"resources": {"stage": "the shared staging environment", "deploy-window": "a production rollout"}}\n' > $R/lock-rules.json
CLAUDE_CODE_SESSION_ID=$OTHER $B/lock take main-merge --repo '*' --until +2h --why "merging #700" --owner-name "merge steward" >/dev/null; check $? 0 "take main-merge"
CLAUDE_CODE_SESSION_ID=$ME $B/lock take main-merge --repo '*' --until +1h --why "mine" >/dev/null 2>&1; check $? 1 "negative: another session's active lock refused"
CLAUDE_CODE_SESSION_ID=$ME $B/lock release main-merge --repo '*' >/dev/null 2>&1; check $? 1 "negative: release of another's lock refused"
$B/lock list | grep -q '^main-merge .*active .*merge steward'; check $? 0 "list shows the active lock"
CLAUDE_CODE_SESSION_ID=$ME $B/lock take stage --repo webapp --until +1h --why "staging refresh" --owner-name "hub" >/dev/null; check $? 0 "take stage for one repo"
CLAUDE_CODE_SESSION_ID=$ME $B/lock take deploy-window --until 2000-01-01T00:00 --why x >/dev/null 2>&1; check $? 2 "usage: --until in the past"
$B/lock take stage --until +1h --why x >/dev/null 2>&1; check $? 2 "usage: no session id and no --force"
grep -q '^```locks' $R/board.md && grep -q '^## Summary' $R/board.md; check $? 0 "board rendered with a locks block and a summary"
# ---- board_locks hook
hook(){ python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","session_id":sys.argv[2],"cwd":sys.argv[3],"tool_input":{"command":sys.argv[1]}}))' "$1" "$2" "${3:-/}" | python3 $HOOKS/board_locks.py; }
deny(){ hook "$@" | grep -q '"permissionDecision": "deny"'; }
deny "gh pr merge 12 --squash" $ME; check $? 0 "deny: gh pr merge under another's main-merge"
hook "gh pr merge 12 --squash" $ME | grep -q 'held by \\"merge steward\\"'; check $? 0 "…the reason names the holder"
deny "gh pr merge 12" $OTHER; check $? 1 "own lock: no decision"
deny "git push origin HEAD:main" $ME; check $? 0 "deny: push to main"
deny "git push origin feature-x" $ME; check $? 1 "push to a feature branch: no decision"
deny "git push --dry-run origin main" $ME; check $? 1 "dry-run push: no decision"
deny "glab mr merge 5" $ME; check $? 0 "deny: glab mr merge"
deny "gh api -X PUT repos/acme/webapp/pulls/9/merge" $ME; check $? 0 "deny: merge through the API"
deny "gh api repos/acme/webapp/pulls/9" $ME; check $? 1 "GET through the API: no decision"
deny 'echo "gh pr merge 12"' $ME; check $? 1 "quoted text is not a command"
deny "gh pr merge 12 # lock-ok: merging my own docs PR" $ME; check $? 1 "escape hatch"
deny "bash -c 'gh pr merge 12'" $ME; check $? 0 "deny inside bash -c"
# repo scoping: the stage lock guards webapp only
mkdir -p $R/repos/webapp/.git $R/repos/mobile/.git $R/repos/webapp-wt
printf 'gitdir: %s/repos/webapp/.git/worktrees/wt\n' $R > $R/repos/webapp-wt/.git
printf '{"rules":[{"match":"\\\\bmake deploy-staging\\\\b","kinds":["stage"],"action":"staging deploy"}]}\n' > $R/lock-rules.json
deny "make deploy-staging" $OTHER $R/repos/webapp; check $? 0 "custom rule: deny staging deploy in webapp"
deny "make deploy-staging" $OTHER $R/repos/mobile; check $? 1 "custom rule: another repo is not guarded"
deny "make deploy-staging" $OTHER $R/repos/webapp-wt; check $? 0 "a worktree resolves to its main repository"
deny "make deploy-staging" $ME $R/repos/webapp; check $? 1 "custom rule: own lock passes"
deny "make build" $OTHER $R/repos/webapp; check $? 1 "unrelated command: no decision"
# expired lock and a broken board fail open
CLAUDE_CODE_SESSION_ID=$OTHER $B/lock release main-merge >/dev/null
deny "gh pr merge 12" $ME; check $? 1 "no lock: no decision"
echo "garbage" > $R/board.md
hook "gh pr merge 12" $ME > $R/fo.out 2>$R/fo.err; check $? 0 "broken board: exit 0"
check "$(wc -c < $R/fo.out | tr -d ' ')" 0 "broken board: no decision (fail-open)"
echo '{"rules": [' > $R/lock-rules.json; echo "" > $R/board.md; rm $R/board.md
hook "make deploy-staging" $ME $R/repos/webapp > $R/fo2.out 2>/dev/null; check $? 0 "broken rules file: exit 0, the file skipped with a warning"
# ---- handoff_size hook
hs(){ python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":"x"*int(sys.argv[2])}}))' "$1" "$2" | python3 $HOOKS/handoff_size.py; }
hs $R/HANDOFF-hub-stage-a-1.md 16000 | grep -q '"deny"'; check $? 0 "handoff_size: a 16 KB handoff is refused"
hs $R/HANDOFF-hub-stage-a-1.md 9000 | grep -q '"deny"'; check $? 1 "handoff_size: a 9 KB handoff passes"
hs $R/notes.md 90000 | grep -q '"deny"'; check $? 1 "handoff_size: other files are not checked"
printf 'a%.0s' $(seq 1 15000) > $R/HANDOFF-x.md
python3 -c 'import json,sys; print(json.dumps({"tool_name":"Edit","tool_input":{"file_path":sys.argv[1],"old_string":"aaaa","new_string":"b"*2000}}))' $R/HANDOFF-x.md | python3 $HOOKS/handoff_size.py | grep -q '"deny"'; check $? 0 "handoff_size: an Edit that grows past the cap is refused"
# ---- questions hook (SessionStart)
new_home
echo '{}' | python3 $HOOKS/questions.py > $R/q0.out; check "$(wc -c < $R/q0.out | tr -d ' ')" 0 "questions: no register, no output"
$B/ask add --stage stage-a --blocks "release" --default "ship" --due 2000-01-01 "Ship it?" >/dev/null
echo "{\"cwd\": \"$AGENT_HUB_HOME\"}" | python3 $HOOKS/questions.py > $R/q1.out
grep -q 'stage-a — open 1, overdue 1' $R/q1.out && grep -q '"hookEventName": "SessionStart"' $R/q1.out; check $? 0 "questions: open and overdue counted"
# scope: only the hub home, repositories with .agent-hub/, AGENT_HUB_SCOPE_DIRS, hub agents
S=$(mktemp -d); mkdir -p $S/other/.git $S/proj/.git $S/proj/.agent-hub $S/proj/src $S/mine/notes
qs(){ echo "{\"cwd\": \"$1\"}" | python3 $HOOKS/questions.py | grep -q 'open 1'; }
qs $S/other; check $? 1 "questions scope: an unrelated project hears nothing"
qs $S/proj/src; check $? 0 "questions scope: a repository with .agent-hub/"
HUB_TAG=builder qs $S/other; check $? 0 "questions scope: a hub agent anywhere"
echo "{\"AGENT_HUB_SCOPE_DIRS\": \"$S/mine\"}" > $AGENT_HUB_HOME/config.json
qs $S/mine/notes; check $? 0 "questions scope: under AGENT_HUB_SCOPE_DIRS"
qs $S/other; check $? 1 "…and still not elsewhere"
hsc(){ python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Write","cwd":sys.argv[3],"tool_input":{"file_path":sys.argv[1],"content":"x"*int(sys.argv[2])}}))' "$1" "$2" "${3:-/}" | python3 $HOOKS/handoff_size.py | grep -q '"deny"'; }
hsc $S/other/HANDOFF-x.md 16000; check $? 1 "handoff_size scope: a HANDOFF-*.md in an unrelated project passes"
hsc $S/proj/docs/HANDOFF-x.md 16000; check $? 0 "handoff_size scope: inside a repository with .agent-hub/"
hsc HANDOFF-rel.md 16000 $S/proj/src; check $? 0 "handoff_size scope: a relative path resolves against the cwd"
hsc $S/mine/HANDOFF-x.md 16000; check $? 0 "handoff_size scope: under AGENT_HUB_SCOPE_DIRS"
rm $AGENT_HUB_HOME/config.json
# ---- hooks.json points at existing scripts
python3 - "$T/../hooks/hooks.json" <<'PY'; check $? 0 "hooks.json: valid, every command script exists"
import json, os, re, sys
d = json.load(open(sys.argv[1]))
root = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[1])))
for ev, groups in d["hooks"].items():
    for g in groups:
        for h in g["hooks"]:
            for m in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", h["command"]):
                assert os.path.isfile(os.path.join(root, m)), m
PY
# ---- lock take without --repo: the enclosing git repository (a worktree: its main repository), `*` only on request
new_home; R=$AGENT_HUB_HOME
G=$(mktemp -d); MAIN=$G/shop; BLOG=$G/blog; PLAIN=$G/plain; mkdir $PLAIN
for r in $MAIN $BLOG; do git init -q -b main $r && git -C $r -c user.email=t@t -c user.name=t commit -q --allow-empty -m init; done
git -C $MAIN worktree add -q -b feat $G/shop-wt; WT=$G/shop-wt
[ ! -e $MAIN/.agent-hub ] && [ ! -e $WT/.agent-hub ]; check $? 0 "control: the fixture repositories have no .agent-hub/"
(cd $WT && CLAUDE_CODE_SESSION_ID=$ME $B/lock take main-merge --until +1h --why "from the worktree") > $R/wt.out; check $? 0 "take in a fresh worktree without .agent-hub/"
grep -q '"kind": "main-merge", "repo": "shop"' $R/board.md; check $? 0 "…the lock's repo is the repository name, not *"
deny "gh pr merge 3" $OTHER $MAIN; check $? 0 "the hook finds a worktree's lock from the main checkout"
deny "gh pr merge 3" $OTHER $WT; check $? 0 "…and from the worktree itself"
deny "gh pr merge 3" $OTHER $BLOG; check $? 1 "negative: a merge in another repository is not held up"
(cd $MAIN && CLAUDE_CODE_SESSION_ID=$OTHER $B/lock take main-merge --until +1h --why "from the main checkout") > $R/mc.out 2>&1; check $? 1 "negative: the main checkout resolves to the same lock key (held by another session)"
(cd $MAIN && CLAUDE_CODE_SESSION_ID=$ME $B/lock release main-merge) > /dev/null; check $? 0 "release from the main checkout finds the worktree's lock"
(cd $WT && CLAUDE_CODE_SESSION_ID=$ME $B/lock take main-merge --repo '*' --until +1h --why "everything") > /dev/null; check $? 0 "explicit --repo '*' still works"
grep -q '"kind": "main-merge", "repo": "\*"' $R/board.md; check $? 0 "…and records the wildcard"
deny "gh pr merge 3" $OTHER $BLOG; check $? 0 "…which holds up every repository"
rm -f $R/board.md
ln -s $MAIN $G/shop-link
(cd $G/shop-link && CLAUDE_CODE_SESSION_ID=$ME $B/lock take main-merge --until +1h --why "via a symlink") > /dev/null; check $? 0 "take from a symlinked checkout"
grep -q '"kind": "main-merge", "repo": "shop"' $R/board.md; check $? 0 "…a symlinked checkout names the same repository as its worktree"
rm -f $R/board.md
(cd $PLAIN && CLAUDE_CODE_SESSION_ID=$ME $B/lock take main-merge --until +1h --why "no repository") > /dev/null; check $? 0 "take outside any git repository"
grep -q '"kind": "main-merge", "repo": "\*"' $R/board.md; check $? 0 "…falls back to *"
exit $fail
