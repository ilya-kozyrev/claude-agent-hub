#!/bin/bash
# Configuration layers: <hub home>/config.json, <repo>/.agent-hub/ (config.json, lock-rules.json, brief-footer.md,
# handoff-facts.sh, takeover.sh) and <hub home>/<stage>/. Positive and negative controls for each file.
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME
P=$(mktemp -d); REPO=$P/webapp; OUT=$P/outside
mkdir -p $REPO/.git $REPO/.agent-hub $REPO/src/deep $OUT
setting(){ (cd "$1" && python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import hubcore; print(hubcore.setting(sys.argv[2], "-"))' "$B" "$2"); }

# ---- config.json: env > repository > hub home > default
echo '{"AGENT_HUB_DEFAULT_EFFORT": "low", "AGENT_HUB_NIGHT": "22:00-07:00"}' > $R/config.json
echo '{"AGENT_HUB_DEFAULT_EFFORT": "max", "_comment": "ignored"}' > $REPO/.agent-hub/config.json
check "$(setting $OUT AGENT_HUB_DEFAULT_EFFORT)" low "home config.json outside any repository"
check "$(setting $REPO/src/deep AGENT_HUB_DEFAULT_EFFORT)" max "repository config.json wins, found from a subdirectory"
check "$(AGENT_HUB_DEFAULT_EFFORT=medium setting $REPO AGENT_HUB_DEFAULT_EFFORT)" medium "environment wins over both"
check "$(setting $REPO AGENT_HUB_PERMISSION_MODE)" - "unset everywhere: the default"
check "$(setting $REPO AGENT_HUB_NIGHT)" 22:00-07:00 "a hub-wide key from the home config"
mkdir -p $REPO/sub/.git; check "$(setting $REPO/sub AGENT_HUB_DEFAULT_EFFORT)" low "a nested repository does not inherit its parent's .agent-hub"
echo '{"AGENT_HUB_TZ": "Asia/Tokyo", "AGENT_HUB_DEFUALT_EFFORT": "x"}' > $REPO/.agent-hub/config.json
(cd $REPO && python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import hubcore; hubcore.setting("AGENT_HUB_DEFAULT_EFFORT")' "$B") 2> $P/w.err
grep -q 'AGENT_HUB_TZ is not a setting this file may set (hub-wide' $P/w.err; check $? 0 "negative: a hub-wide key in a repository config is refused with a reason"
grep -q 'AGENT_HUB_DEFUALT_EFFORT is not a setting' $P/w.err; check $? 0 "negative: a misspelt key is reported"
echo '{"AGENT_HUB_DEFAULT_EFFORT": ' > $REPO/.agent-hub/config.json
check "$(setting $REPO AGENT_HUB_DEFAULT_EFFORT 2>$P/b.err)" low "negative: a broken repository config is ignored"
grep -q 'config.json ignored' $P/b.err; check $? 0 "…and reported on stderr"
rm $REPO/.agent-hub/config.json
# the time zone comes from the home config (journal clock)
( unset AGENT_HUB_TZ; echo '{"AGENT_HUB_TZ": "Pacific/Kiritimati"}' > $R/config.json
  cd $OUT && $B/jlog --stage stage-a --tag probe "tz probe" ) > $P/tz.out
want=$(TZ=Pacific/Kiritimati date +%H:%M); got=$(sed -n 's/^- \([0-9:]*\) .*/\1/p' $P/tz.out)
check "$got" "$want" "AGENT_HUB_TZ from the home config.json sets the journal clock"
rm $R/config.json

# ---- agent spawn: model map, effort and brief footer from the agent's repository
export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py
echo "brief: do the thing" > $P/b.md
printf '{"AGENT_HUB_MODEL_MAP": {"sonnet": "claude-sonnet-test-9"}, "AGENT_HUB_DEFAULT_EFFORT": "xhigh"}\n' > $REPO/.agent-hub/config.json
printf -- '- Project rule for {role} ({tag}): run `make check` before DONE; report to {report}.\n' > $REPO/.agent-hub/brief-footer.md
wait_dead(){ for i in $(seq 1 40); do $B/agent status --stage stage-a "$1" | grep -q 'ALIVE' || return 0; sleep 0.5; done; }
(cd $OUT && $B/agent spawn --role builder --cwd $REPO --model sonnet --brief $P/b.md) > $P/s1.out 2>&1; check $? 0 "spawn into a configured repository"
wait_dead builder
grep -q -- '--model claude-sonnet-test-9' $REPO/argv.log; check $? 0 "model map from the agent's repository (not the caller's cwd)"
grep -q -- '--effort xhigh' $REPO/argv.log; check $? 0 "default effort from the agent's repository"
grep -q 'Project rule for builder (builder): run `make check`' $REPO/prompts.log; check $? 0 "brief-footer.md appended with {role}/{tag} filled"
grep -q "report to $R/stage-a/coordinator/work/builder-REPORT.md" $REPO/prompts.log; check $? 0 "…and {report}"
grep -q 'Talk to the hub only through the journal' $REPO/prompts.log; check $? 0 "the standard footer stays"
mkdir -p $OUT/w; (cd $REPO && $B/agent spawn --role plain --cwd $OUT/w --model sonnet --brief $P/b.md) > $P/s2.out 2>&1; wait_dead plain
grep -q -- '--model sonnet ' $OUT/w/argv.log && ! grep -q 'Project rule' $OUT/w/prompts.log; check $? 0 "negative: an agent outside the repository gets neither its model map nor its footer"
echo '- Stage rule for {role}.' > $R/stage-a/brief-footer.md
(cd $OUT && $B/agent spawn --role builder2 --cwd $REPO --model sonnet --brief $P/b.md) > /dev/null 2>&1; wait_dead builder2
tail -c 4000 $REPO/prompts.log | grep -q 'Stage rule for builder2' && ! tail -c 4000 $REPO/prompts.log | grep -q 'Project rule for builder2'
check $? 0 "the stage's brief-footer.md wins over the repository's"
rm $R/stage-a/brief-footer.md
unset HUB_TAG CLAUDE_BIN

# ---- lock: default repo from the repository config
printf '{"AGENT_HUB_DEFAULT_REPO": "webapp"}\n' > $REPO/.agent-hub/config.json
printf '{"resources": {"stage": "staging", "deploy-window": "production rollout"}}\n' > $R/lock-rules.json
(cd $REPO && $B/lock take stage --until +1h --why x --force) > /dev/null; check $? 0 "lock take in the repository"
grep -q '"kind": "stage", "repo": "webapp"' $R/board.md; check $? 0 "…recorded for the configured repo"
(cd $OUT && $B/lock take deploy-window --until +1h --why x --force) > /dev/null
grep -q '"kind": "deploy-window", "repo": "\*"' $R/board.md; check $? 0 "negative: outside it the default stays *"
rm $R/board.md

# ---- board_locks: repository and home lock-rules.json together
ME=aaaaaaaa-0000-4000-8000-000000000001; OTHER=bbbbbbbb-0000-4000-8000-000000000002
hook(){ python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","session_id":sys.argv[2],"cwd":sys.argv[3],"tool_input":{"command":sys.argv[1]}}))' "$1" "$2" "$3" | python3 $HOOKS/board_locks.py; }
deny(){ hook "$@" | grep -q '"permissionDecision": "deny"'; }
CLAUDE_CODE_SESSION_ID=$OTHER $B/lock take deploy-window --repo '*' --until +2h --why "release" --owner-name "release hub" >/dev/null
CLAUDE_CODE_SESSION_ID=$OTHER $B/lock take main-merge --repo '*' --until +2h --why "merge train" --owner-name "steward" >/dev/null
printf '{"protected_branches": ["trunk"], "rules": [{"match": "^make release\\\\b", "kinds": ["deploy-window"], "action": "release"}]}\n' > $REPO/.agent-hub/lock-rules.json
printf '{"rules": [{"match": "^helm upgrade\\\\b", "kinds": ["deploy-window"], "action": "helm rollout"}]}\n' > $R/lock-rules.json
deny "make release" $ME $REPO/src; check $? 0 "repository rule applies inside the repository"
deny "make release" $ME $OUT; check $? 1 "negative: repository rule does not apply outside it"
deny "cd $REPO && make release" $ME $OUT; check $? 0 "…but applies after cd into it"
deny "helm upgrade app ./chart" $ME $REPO; check $? 0 "home rule applies inside the repository too"
deny "helm upgrade app ./chart" $ME $OUT; check $? 0 "home rule applies everywhere"
deny "git push origin HEAD:trunk" $ME $REPO; check $? 0 "repository protected branch"
deny "git -C $REPO push origin trunk" $ME $OUT; check $? 0 "…found through git -C"
deny "git push origin HEAD:trunk" $ME $OUT; check $? 1 "negative: not protected elsewhere (default main/master)"
deny "git push origin HEAD:main" $ME $OUT; check $? 0 "default protected branches outside the repository"
deny "make release" $OTHER $REPO; check $? 1 "own lock passes"
echo '{"rules": [' > $REPO/.agent-hub/lock-rules.json
hook "make release" $ME $REPO > $P/fo.out 2>/dev/null; check $? 0 "broken repository rules: exit 0"
! grep -q permissionDecision $P/fo.out && grep -q '"systemMessage"' $P/fo.out; check $? 0 "…its rule cannot decide; the user is warned (t_hardening)"
rm -f $REPO/.agent-hub/lock-rules.json $R/lock-rules.json $R/board.md

# ---- handoff_size: the cap from the home config
printf '{"AGENT_HUB_HANDOFF_MAX_BYTES": "1000"}\n' > $R/config.json
hs(){ python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":"x"*int(sys.argv[2])}}))' "$1" "$2" | python3 $HOOKS/handoff_size.py; }
hs $R/HANDOFF-hub-x.md 2000 | grep -q '"deny"'; check $? 0 "handoff cap from config.json: 2000 bytes refused"
hs $R/HANDOFF-hub-x.md 900 | grep -q '"deny"'; check $? 1 "…900 bytes pass"
rm $R/config.json

# ---- hub handoff: handoff-facts.sh from the repository, the stage's copy wins
export CLAUDE_SESSIONS_DIR=$P/sessions; mkdir -p $CLAUDE_SESSIONS_DIR $R/stage-a/coordinator/work
printf '#!/bin/sh\necho "| Production | from the repository | ci |"\n' > $REPO/.agent-hub/handoff-facts.sh; chmod +x $REPO/.agent-hub/handoff-facts.sh
(cd $REPO && $B/hub handoff --stage stage-a --n 3 --out $P/H1.md) > /dev/null 2>&1
grep -q '^| Production | from the repository' $P/H1.md; check $? 0 "repository handoff-facts.sh fills § 1"
(cd $OUT && $B/hub handoff --stage stage-a --n 3 --out $P/H2.md) > /dev/null 2>&1
grep -q 'from the repository' $P/H2.md; check $? 1 "negative: not used outside the repository"
printf '#!/bin/sh\necho "| Production | from the stage | ci |"\n' > $R/stage-a/handoff-facts.sh; chmod +x $R/stage-a/handoff-facts.sh
(cd $REPO && $B/hub handoff --stage stage-a --n 3 --out $P/H3.md) > /dev/null 2>&1
grep -q '^| Production | from the stage' $P/H3.md && ! grep -q 'from the repository' $P/H3.md; check $? 0 "the stage's handoff-facts.sh wins"
rm $R/stage-a/handoff-facts.sh

# ---- hub takeover: the project step (takeover.sh check/apply)
NEWCLI=eeeeeeee-1111-4111-8111-111111111111
cat > $REPO/.agent-hub/takeover.sh <<'SH'
#!/bin/sh
# marks the hub's number in a pointer file; check = is it there already
f="$AGENT_HUB_HOME/$HUB_STAGE/pointer.txt"
case "$1" in
  check) grep -qx "hub $HUB_N $HUB_CLI_SESSION" "$f" 2>/dev/null && { echo "pointer is current"; exit 0; }; echo "pointer is stale"; exit 1 ;;
  apply) [ -n "$FAIL_APPLY" ] && { echo "cannot write" >&2; exit 3; }; echo "hub $HUB_N $HUB_CLI_SESSION" > "$f"; echo "pointer set to $HUB_TAG" ;;
  *) exit 2 ;;
esac
SH
chmod +x $REPO/.agent-hub/takeover.sh
(cd $REPO && $B/hub takeover --stage stage-a --n 4 --session $NEWCLI --dry-run) > $P/k0.out 2>&1; check $? 0 "takeover dry-run"
grep -q '\[plan\] project step' $P/k0.out && [ ! -f $R/stage-a/pointer.txt ]; check $? 0 "dry-run: project step planned, nothing written"
(cd $REPO && FAIL_APPLY=1 $B/hub takeover --stage stage-a --n 4 --session $NEWCLI) > $P/k1.out 2>&1; check $? 1 "negative: a failing apply stops the takeover"
grep -q 'takeover.sh apply exited 3' $P/k1.out && ! grep -q '"hub"' $R/stage-a/roles.json 2>/dev/null; check $? 0 "…named, and the roles step was not run"
(cd $REPO && $B/hub takeover --stage stage-a --n 4 --session $NEWCLI) > $P/k2.out 2>&1; check $? 0 "takeover with the project step"
check "$(cat $R/stage-a/pointer.txt)" "hub 4 $NEWCLI" "takeover.sh got HUB_N and HUB_CLI_SESSION"
grep -q '\[ok\] project step' $P/k2.out && grep -q 'pointer set to hub-4' $P/k2.out; check $? 0 "…verified by check, output shown"
(cd $REPO && $B/hub takeover --stage stage-a --n 4 --session $NEWCLI) > $P/k3.out 2>&1
grep -q '\[already done\] project step' $P/k3.out; check $? 0 "re-run: already done"
chmod -x $REPO/.agent-hub/takeover.sh
(cd $REPO && $B/hub takeover --stage stage-a --n 4 --session $NEWCLI) > $P/k4.out 2>&1
grep -q 'takeover.sh is not executable' $P/k4.out; check $? 0 "negative: a non-executable step is reported, not run"

# ---- takeover: main-merge per repository (the hub's repo is AGENT_HUB_DEFAULT_REPO)
new_home; R=$AGENT_HUB_HOME; mkdir -p $R/stage-a
python3 - "$R/board.md" <<'PY'
import json, sys
rows = [{"kind": "main-merge", "repo": "webapp", "owner_name": "steward A", "session_id": "55555555-5555-4555-8555-555555555555",
         "until": "2099-12-31T23:59:00+00:00", "why": "train A", "taken_at": "2026-09-29T14:00:00+00:00"},
        {"kind": "main-merge", "repo": "mobile", "owner_name": "steward B", "session_id": "66666666-6666-4666-8666-666666666666",
         "until": "2099-12-31T23:59:00+00:00", "why": "train B", "taken_at": "2026-09-29T14:00:00+00:00"}]
open(sys.argv[1], "w").write("# b\n\n```locks\n" + "\n".join(json.dumps(r) for r in rows) + "\n```\n")
PY
rm -f $REPO/.agent-hub/takeover.sh
(cd $REPO && $B/hub takeover --stage stage-a --n 5 --session $NEWCLI) > $P/m1.out 2>&1
grep -q 'main-merge (webapp) is held by steward A' $P/m1.out && grep -q 'main-merge (mobile) is held by steward B' $P/m1.out
check $? 0 "every repo's third-party main-merge is reported"
(cd $REPO && $B/hub takeover --stage stage-a --n 5 --session $NEWCLI --take-main-merge) > $P/m2.out 2>&1; check $? 0 "--take-main-merge run"
python3 - "$R/board.md" "$NEWCLI" <<'PY' ; check $? 0 "…takes the hub repo's main-merge only"
import json, re, sys
rows = [json.loads(l) for l in re.search(r"```locks\n(.*?)```", open(sys.argv[1]).read(), re.S).group(1).splitlines() if l.strip()]
own = {r["repo"]: r["session_id"] for r in rows if r["kind"] == "main-merge"}
sys.exit(0 if own.get("webapp") == sys.argv[2] and own.get("mobile") != sys.argv[2] else 1)
PY
exit $fail
