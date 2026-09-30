#!/bin/bash
# hub takeover / handoff on synthetic fixtures: dry run, negatives, a failing step, lock handover, idempotent
# re-runs, a third-party main-merge holder, a stale registry, cli-prefix predecessors, handoff draft.
. "$(dirname "$0")/lib.sh"
FX=$T/fixtures
export CLAUDE_SESSIONS_DIR=$(mktemp -d)/s; mkdir -p $CLAUDE_SESSIONS_DIR/a/b
mk(){ printf '{"sessionId":"local_%s","cliSessionId":"%s","title":"%s","isArchived":%s}' "$1" "$2" "$3" "${4:-false}" > $CLAUDE_SESSIONS_DIR/a/b/local_$1.json; }
PREV=12121212-1212-4121-8121-121212121212; PREV_CLI=34343434-3434-4343-8343-343434343434
NEW=77777777-7777-4777-8777-777777777777; NEW_CLI=eeeeeeee-7777-4777-8777-777777777777
OLD=66666666-6666-4666-8666-666666666666; OLD_CLI=cccccccc-6666-4666-8666-666666666666
STEWARD=55555555-5555-4555-8555-555555555555
mk $PREV $PREV_CLI "Hub stage-a #16"; mk $NEW $NEW_CLI "Hub stage-a #17"; mk $OLD $OLD_CLI "Hub stage-a #14"
mk 88888888-8888-4888-8888-888888888888 dddddddd-8888-4888-8888-888888888888 "archived" true
# setup <coordinator value> <extra: none|steward|other-repo>
setup(){
  new_home; R=$AGENT_HUB_HOME; C=$R/stage-a/coordinator; mkdir -p $C/work
  sed "s/PREV_ID/$1/" $FX/night-queue.md > $R/stage-a/night-queue.md
  cp $FX/HANDOFF-hub-stage-a-2026-09-29-1150.md $C/
  $B/ask add --stage stage-a --blocks "release" --default "ship without the flag" --due 2099-01-01T10:00 --by hub-16 "Ship the flag on by default?" >/dev/null
  $B/ask decided --stage stage-a --by hub-16 --alternative "keep the old schema" "Use the new schema for the export" >/dev/null
  python3 - "$R/board.md" "$2" "$PREV_CLI" "$STEWARD" <<'PY'
import json, sys
path, extra, prev, steward = sys.argv[1:]
rows = [{"kind": "stage", "repo": "webapp", "owner_name": "Hub stage-a #16", "session_id": prev,
         "until": "2099-12-31T23:59:00+00:00", "why": "staging data refresh", "taken_at": "2026-09-29T14:37:57+00:00"},
        {"kind": "deploy-window", "repo": "*", "owner_name": "Hub stage-a #16", "session_id": prev,
         "until": "2099-12-31T23:59:00+00:00", "why": "release 1.4", "value": "v1.4", "taken_at": "2026-09-29T14:40:00+00:00"},
        {"kind": "stage", "repo": "mobile", "owner_name": "someone else", "session_id": "99999999-9999-4999-8999-999999999999",
         "until": "2099-12-31T23:59:00+00:00", "why": "other team", "taken_at": "2026-09-29T14:00:00+00:00"}]
if extra == "steward":
    rows.append({"kind": "main-merge", "repo": "*", "owner_name": "merge steward", "session_id": steward,
                 "until": "2099-12-31T23:59:00+00:00", "why": "merging #700", "taken_at": "2026-09-29T14:00:00+00:00"})
open(path, "w").write("# b\n\n```locks\n" + "\n".join(json.dumps(r) for r in rows) + "\n```\n")
PY
}
holder(){ python3 - "$R/board.md" "$1" "${2:-}" <<'PY'
import json, re, sys
t = open(sys.argv[1]).read()
rows = [json.loads(l) for l in re.search(r"```locks\n(.*?)```", t, re.S).group(1).splitlines() if l.strip()]
print(next((r["session_id"] for r in rows if r["kind"] == sys.argv[2] and (not sys.argv[3] or r["repo"] == sys.argv[3])), "-"))
PY
}

# 1. dry-run writes nothing
setup local_$PREV none
before=$(snap $R); $B/hub takeover --stage stage-a --n 17 --session local_$NEW --dry-run > $R/dry.out 2>&1; rc=$?
check $rc 0 "dry-run exit 0"; check "$(snap $R)" "$before" "dry-run changed no file"
check "$(sed -n '/^DIGEST/,$p' $R/dry.out | wc -c | tr -d ' ' | awk '{print ($1<=3072)}')" 1 "digest ≤ 3 KB"
grep -q "^DIGEST" $R/dry.out && grep -q "First jwait" $R/dry.out && grep -q "§ 0 of the handoff" $R/dry.out && grep -q "ask register" $R/dry.out; check $? 0 "digest has § 0, ask, jwait"
grep -q "Q-A-001 open: Ship the flag" $R/dry.out && grep -q "D-A-001 in force: Use the new schema" $R/dry.out; check $? 0 "digest lists the open question and the standing decision"
# 2. negatives before the real run
$B/hub takeover --stage stage-a --n 17 --session local_88888888-8888-4888-8888-888888888888 >/dev/null 2>&1; check $? 1 "negative: archived session refused"
$B/hub takeover --stage stage-a --n 17 --session local_99999999-9999-4999-8999-999999999999 >/dev/null 2>&1; check $? 1 "negative: unknown session refused"
$B/hub takeover --stage stage-a --n 17 >/dev/null 2>&1; check $? 2 "usage: missing --session"
$B/hub takeover --stage nope --n 17 --session local_$NEW >/dev/null 2>&1; check $? 2 "usage: unknown stage directory"
# 3. a failing step stops the rest: night-queue without coordinator:
cp $R/stage-a/night-queue.md $R/nq.bak; subst $R/stage-a/night-queue.md '^coordinator:.*\n' ''
$B/hub takeover --stage stage-a --n 17 --session local_$NEW --skip-lock stage --skip-lock deploy-window > $R/fail.out 2>&1; rc=$?
check $rc 1 "negative: broken night-queue stops takeover"
[ ! -f $R/stage-a/roles.json ]; check $? 0 "…roles not written after the failed step"
cat $(journal stage-a) 2>/dev/null | grep -q "hub-17\] start"; check $? 1 "…no start line in the journal"
cp $R/nq.bak $R/stage-a/night-queue.md
# 4. real takeover (the session given as a bare uuid)
$B/hub takeover --stage stage-a --n 17 --session $NEW > $R/take.out 2>&1; rc=$?
check $rc 0 "takeover exit 0"
check "$(holder stage webapp)" $NEW_CLI "prev hub's stage lock taken"
check "$(holder deploy-window)" $NEW_CLI "prev hub's deploy-window taken"
check "$(holder stage mobile)" 99999999-9999-4999-8999-999999999999 "another holder's lock untouched"
check "$(holder main-merge)" "-" "main-merge not taken without --take-main-merge"
grep -q '"value": "v1.4"' $R/board.md; check $? 0 "lock value kept on handover"
check "$(sed -n 's/^coordinator: //p' $R/stage-a/night-queue.md)" "local_$NEW" "night-queue coordinator updated (local_ id)"
grep -q "^updated: .*Hub stage-a #17 (local_$NEW" $R/stage-a/night-queue.md; check $? 0 "night-queue updated line"
$B/nightq check --stage stage-a > /dev/null; check $? 0 "nightq check passes after edit"
check "$($B/roles --stage stage-a get hub)" "local_$NEW" "roles hub set"
grep -q "\[hub-17\] start: \"Hub stage-a #17\"" $(journal stage-a); check $? 0 "journal start line"
# 5. second takeover by the same session changes nothing
before=$(snap $R); $B/hub takeover --stage stage-a --n 17 --session local_$NEW > $R/again.out 2>&1; check $? 0 "repeat takeover is a no-op"
check "$(grep -c '^\[ok\]' $R/again.out)" 0 "…no step runs again"
check "$(grep -c '^\[already done\] \(night-queue\|roles\|journal\)' $R/again.out)" 3 "…every file step reports already done"
# 6. handoff
$B/hub handoff --stage stage-a --n 17 --out $R/H.md > $R/h.out 2>&1; check $? 0 "handoff exit 0"
miss=0; for s in 0 1 2 3 4 5; do grep -q "^## $s\." $R/H.md || { echo "missing § $s"; miss=1; }; done; check $miss 0 "handoff has §§ 0–5"
[ "$(wc -c < $R/H.md)" -le 12288 ]; check $? 0 "handoff ≤ 12 KB"
grep -q "TODO" $R/H.md && grep -q "deploy-window (\*)" $R/H.md && grep -q "hub takeover --stage stage-a --n 18" $R/H.md; check $? 0 "handoff has facts and TODOs"
$B/hub handoff --stage stage-a --n 17 --out $R/H.md >/dev/null 2>&1; check $? 1 "negative: handoff does not overwrite"
printf '#!/bin/sh\necho "| Production | v1.4 deployed | release notes |"\n' > $R/stage-a/handoff-facts.sh; chmod +x $R/stage-a/handoff-facts.sh
$B/hub handoff --stage stage-a --n 17 --out $R/H2.md >/dev/null 2>&1; grep -q '^| Production | v1.4 deployed' $R/H2.md; check $? 0 "handoff-facts.sh rows go into § 1"
# 7. a third-party main-merge holder is left alone and reported; --take-main-merge takes it
setup local_$PREV steward
$B/hub takeover --stage stage-a --n 17 --session local_$NEW > $R/t7.out 2>&1; rc=$?
check $rc 0 "takeover succeeds with a steward holding main-merge"
check "$(holder main-merge)" $STEWARD "main-merge stays with the steward"
grep -q 'main-merge.*merge steward' $R/t7.out; check $? 0 "the foreign holder is reported"
$B/hub takeover --stage stage-a --n 17 --session local_$NEW --take-main-merge > $R/t7b.out 2>&1; check $? 0 "--take-main-merge run"
check "$(holder main-merge)" $NEW_CLI "--take-main-merge takes it from the steward"
# 8. a takeover that failed midway completes on re-run
setup local_$PREV none
chmod a-w $R/stage-a
$B/hub takeover --stage stage-a --n 17 --session local_$NEW > $R/t8a.out 2>&1; rc=$?; chmod u+w $R/stage-a
check $rc 1 "a step fails on a read-only stage dir"
$B/hub takeover --stage stage-a --n 17 --session local_$NEW > $R/t8b.out 2>&1; rc=$?
check $rc 0 "re-run completes the takeover"
check "$($B/roles --stage stage-a get hub)" "local_$NEW" "roles hub written on re-run"
grep -q 'already done' $R/t8b.out; check $? 0 "re-run reports done steps as already done"
$B/hub takeover --stage stage-a --n 17 --session local_$NEW > $R/t8c.out 2>&1; check $? 0 "third run is a no-op with exit 0"
check "$(grep -c '\[hub-17\] start' $(journal stage-a))" 1 "exactly one start line after three runs"
# 9. stale roles hub: the night-queue predecessor's locks are still taken
setup local_$PREV none
$B/roles --stage stage-a set hub local_$OLD --tag hub-14 >/dev/null
$B/hub takeover --stage stage-a --n 17 --session local_$NEW > $R/t9.out 2>&1; rc=$?
check $rc 0 "takeover with a stale registry"
check "$(holder stage webapp)" $NEW_CLI "stage taken from the night-queue predecessor"
grep -q 'sources disagree' $R/t9.out; check $? 0 "registry/night-queue disagreement reported"
grep -q 'jwait --journal .*--since 20' $R/t9.out; check $? 0 "digest jwait has --since"
# 10. an 8-char cli prefix in coordinator: resolves to its unique session; an ambiguous one stops
setup ${PREV_CLI:0:8} none
$B/hub takeover --stage stage-a --n 17 --session local_$NEW > $R/t10.out 2>&1; rc=$?
check $rc 0 "takeover with a short coordinator: prefix"
check "$(holder stage webapp)" $NEW_CLI "the prefix-resolved predecessor's stage lock is taken"
mk 99999999-9999-4999-8999-999999999999 ${PREV_CLI:0:8}-0000-4000-8000-000000000000 "twin"
setup ${PREV_CLI:0:8} none
$B/hub takeover --stage stage-a --n 17 --session local_$NEW > $R/t10b.out 2>&1; check $? 1 "negative: an ambiguous prefix stops the takeover"
grep -q 'matches 2 sessions' $R/t10b.out; check $? 0 "…and says why"
rm $CLAUDE_SESSIONS_DIR/a/b/local_99999999-9999-4999-8999-999999999999.json
# 11. a terminal (CLI) session can be the hub too
setup local_$PREV none
TERM_ID=abababab-abab-4bab-8bab-abababababab
$B/hub takeover --stage stage-a --n 17 --session $TERM_ID > $R/t11.out 2>&1; check $? 0 "takeover by a terminal session uuid"
check "$(holder stage webapp)" $TERM_ID "locks recorded on the terminal session"
$B/roles --stage stage-a list | grep -q "^hub .*cli .*$TERM_ID"; check $? 0 "hub role recorded as kind cli"
exit $fail
