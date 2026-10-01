#!/bin/bash
# Where the hub keeps its files: the resolution order (environment > a repository's "project"/"user" > ~/agent-hub >
# the legacy ~/.claude/agent-hub), the "project" home shared by every worktree, hooks resolving for the input's cwd,
# children pinned to the parent's home with --add-dir, a stage found in another home, and `hub home migrate`.
. "$(dirname "$0")/lib.sh"
unset AGENT_HUB_HOME AGENT_HUB_DELEGATION AGENT_HUB_STATE_DIR CLAUDE_PLUGIN_ROOT
S=$(cd "$(mktemp -d)" && pwd -P)
export HOME=$S/home; mkdir -p $HOME
# layer and path of the resolved home, as `hub home --json` reports them, from directory $1
hh(){ (cd "$1" && $B/hub home --json 2>/dev/null) | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["layer"], d["home"])'; }
newrepo(){ git init -q -b main $1 && git -C $1 -c user.email=t@t -c user.name=t commit -q --allow-empty -m init; }
mkdir -p $S/plain

# ================================================================== the order
check "$(hh $S/plain)" "default $HOME/agent-hub" "no setting: the user default ~/agent-hub"
mkdir -p $HOME/.claude/agent-hub
check "$(hh $S/plain)" "legacy $HOME/.claude/agent-hub" "~/agent-hub absent, ~/.claude/agent-hub present: the legacy home"
mkdir -p $HOME/agent-hub
check "$(hh $S/plain)" "default $HOME/agent-hub" "…but once ~/agent-hub exists, the user default wins over the legacy one"
check "$(AGENT_HUB_HOME=$S/envhome hh $S/plain)" "env $S/envhome" "AGENT_HUB_HOME wins"
P=$S/proj; newrepo $P; mkdir -p $P/.agent-hub
echo '{"AGENT_HUB_HOME": "project"}' > $P/.agent-hub/config.json
check "$(hh $P)" "project $P/.agent-hub/local" "a repository's \"project\": <repo>/.agent-hub/local"
check "$(AGENT_HUB_HOME=$S/envhome hh $P)" "env $S/envhome" "…the environment still wins over it"
check "$(hh $S/plain)" "default $HOME/agent-hub" "…and a directory outside the repository keeps the user default"
U=$S/userproj; newrepo $U; mkdir -p $U/.agent-hub; echo '{"AGENT_HUB_HOME": "user"}' > $U/.agent-hub/config.json
check "$(hh $U)" "user $HOME/agent-hub" "a repository's \"user\": the user default"
X=$S/evil; newrepo $X; mkdir -p $X/.agent-hub; echo "{\"AGENT_HUB_HOME\": \"$S/stolen\"}" > $X/.agent-hub/config.json
(cd $X && $B/hub home --json > $S/x.out 2> $S/x.err)
check "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["layer"])' $S/x.out)" "default" "negative: a repository's path value is ignored"
check "$(grep -c 'AGENT_HUB_HOME=.*ignored' $S/x.err)" "1" "…with one warning line"
(cd $X && $B/jlog --stage stage-a --tag t "x" > /dev/null 2>&1)
[ ! -e $S/stolen ] && [ -f $HOME/agent-hub/stage-a/coordinator/work/journal-$(today).md ]; check $? 0 "…a tool there writes to the user default, never to the repository's path"
rm -rf $HOME/agent-hub/stage-a

# ================================================================== "project": shared by every worktree
git -C $P worktree add -q $P/.worktrees/w1 -b w1
check "$(hh $P/.worktrees/w1)" "project $P/.agent-hub/local" "a linked worktree (no .agent-hub of its own) shares the main checkout's home"
C=$S/committed; newrepo $C; mkdir -p $C/.agent-hub; echo '{"AGENT_HUB_HOME": "project"}' > $C/.agent-hub/config.json
git -C $C add .agent-hub/config.json && git -C $C -c user.email=t@t -c user.name=t commit -q -m cfg
git -C $C worktree add -q $S/cwt -b cwt
check "$(hh $S/cwt)" "project $C/.agent-hub/local" "a worktree with the committed .agent-hub/ still shares the main checkout's home"
(cd $P && $B/jlog --stage stage-a --tag t "one" > /dev/null) && (cd $P/.worktrees/w1 && $B/jlog --stage stage-a --tag t "two" > /dev/null)
check "$(grep -c '\[t\]' $P/.agent-hub/local/stage-a/coordinator/work/journal-$(today).md)" "2" "…both write one journal"
check "$(grep -cx '/.agent-hub/local/' $P/.git/info/exclude)" "1" "/.agent-hub/local/ is excluded once in .git/info/exclude"
check "$(git -C $C status --porcelain | wc -l | tr -d ' ')" "0" "…so the home never shows as untracked"

# ================================================================== hooks resolve for the input's cwd
(cd $P && $B/ask add --stage stage-q --due 2099-01-01T10:00 "Ship it?" > /dev/null)
Q=$S/other; newrepo $Q; mkdir -p $Q/.agent-hub; echo '{"AGENT_HUB_HOME": "project"}' > $Q/.agent-hub/config.json
(cd $S/plain && echo "{\"cwd\": \"$P\"}" | python3 $HOOKS/questions.py > $S/q1.out 2>&1)
grep -q 'stage-q' $S/q1.out; check $? 0 "questions hook: the register of the input cwd's home (process elsewhere)"
(cd $P && echo "{\"cwd\": \"$Q\"}" | python3 $HOOKS/questions.py > $S/q2.out 2>&1)
grep -q 'stage-q' $S/q2.out; check $? 1 "control: run from that repository with another repository's cwd, the other home answers"
(cd $S/plain && echo "{\"session_id\": \"sid-1\", \"cwd\": \"$Q\"}" | AGENT_HUB_DELEGATION=on python3 $HOOKS/delegation.py session-start > /dev/null 2>&1)
[ -f $Q/.agent-hub/local/.state/delegation/injected/sid-1 ] && [ ! -e $HOME/agent-hub/.state/delegation/injected/sid-1 ]; check $? 0 "delegation hook writes its state in the input cwd's home"
LH=$S/lhome; mkdir -p $LH/.claude/agent-hub
(cd $S/plain && echo "{\"cwd\": \"$LH/.claude/agent-hub\"}" | HOME=$LH python3 $HOOKS/questions.py > $S/q3.out 2>&1)
grep -q 'legacy .*hub home migrate' $S/q3.out; check $? 0 "SessionStart: one line when the home is the legacy one"
grep -q 'legacy' $S/q1.out; check $? 1 "…and none when it is not"

# ================================================================== children pinned, with --add-dir
export CLAUDE_BIN=$T/fake_claude.py HUB_STAGE=stage-a
W=$S/work; mkdir -p $W; echo "brief" > $S/b.md
wait_dead(){ for i in $(seq 1 40); do (cd $P && $B/agent status $1) | grep -q 'ALIVE' || return 0; sleep 0.5; done; }
(cd $P && $B/agent spawn --role r1 --cwd $W --model haiku --brief $S/b.md > $S/sp1.out 2>&1); check $? 0 "spawn from the repository (project home), agent cwd elsewhere"
wait_dead r1
grep -q -- "--add-dir $P/.agent-hub/local -n" $W/argv.log; check $? 0 "…the CLI gets --add-dir <home>, before the next option"
grep -qx "AGENT_HUB_HOME=$P/.agent-hub/local" $W/env.log; check $? 0 "…and AGENT_HUB_HOME pinned to the parent's resolved home"
[ -f $P/.agent-hub/local/stage-a/agents/r1/meta.json ]; check $? 0 "…its files are in that home"
(cd $P && $B/agent send r1 "next" > /dev/null 2>&1); wait_dead r1
check "$(grep -c -- "--resume .*--add-dir $P/.agent-hub/local" $W/argv.log)" "1" "resume: --add-dir again"
mkdir -p $P/sub
(cd $P && $B/agent spawn --role r2 --cwd $P/sub --model haiku --brief $S/b.md > /dev/null 2>&1); wait_dead r2
(cd $P && $B/agent spawn --role r3 --cwd $P --model haiku --brief $S/b.md > /dev/null 2>&1); wait_dead r3
grep -q -- "--add-dir" $P/argv.log; check $? 1 "control: an agent whose cwd holds the home gets no --add-dir"
grep -q -- "--add-dir" $P/sub/argv.log; check $? 0 "…one in a subdirectory beside the home does"
unset HUB_STAGE CLAUDE_BIN

# the autopilot successor: --add-dir, the pinned home, no inherited AGENT_SESSION_ID
R=$S/aphome; export AGENT_HUB_HOME=$R CLAUDE_BIN=$T/fake_claude_bg.py FAKE_BG_LOG=$S/bg.log AGENT_HUB_AUTO_HANDOFF=on \
  AGENT_HUB_SUCCESSOR_TIMEOUT=2 CLAUDE_SESSIONS_DIR=$(mktemp -d)
$B/hub start --stage stage-a --session 11111111-1111-4111-8111-111111111111 > /dev/null 2>&1
H=$R/stage-a/coordinator/HANDOFF-hub-stage-a-2026-10-01-1200.md; printf '# Handoff\n\n## 0. First steps\n1. x\n' > $H
HUB_TAG=hub-1 AGENT_SESSION_ID=old-hub-id $B/hub succeed --stage stage-a --handoff $H --cwd $W --model opus --permission-mode default > $S/succ.out 2>&1
python3 - $S/bg.log $R <<'PY' > $S/bg.chk
import json, sys
c = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
bg = [x for x in c if x["argv"] and x["argv"][0] == "--bg"][-1]
a = bg["argv"]
print("add-dir" if a[a.index("--add-dir") + 1] == sys.argv[2] and a[a.index("--add-dir") + 2] == "--model" else "no add-dir")
print("home " + str(bg["env"].get("AGENT_HUB_HOME") == sys.argv[2]))
print("sid " + str(bg["env"].get("AGENT_SESSION_ID")))
PY
check "$(sed -n 1p $S/bg.chk)" "add-dir" "successor: claude --bg gets --add-dir <home>, followed by an option"
check "$(sed -n 2p $S/bg.chk)" "home True" "…and the parent's home in its environment"
check "$(sed -n 3p $S/bg.chk)" "sid None" "…without the old hub's AGENT_SESSION_ID"
unset AGENT_HUB_HOME CLAUDE_BIN FAKE_BG_LOG AGENT_HUB_AUTO_HANDOFF AGENT_HUB_SUCCESSOR_TIMEOUT

# ================================================================== a stage in another home
mkdir -p $HOME/agent-hub/stage-x
AGENT_HUB_HOME=$S/elsewhere $B/jlog --stage stage-x --tag t "x" > /dev/null 2> $S/e1.err; check $? 1 "a stage absent here but in ~/agent-hub: refused"
grep -q "stage stage-x is not in the hub home $S/elsewhere .* but in $HOME/agent-hub: move the stage (.mv $HOME/agent-hub/stage-x $S/elsewhere/" $S/e1.err; check $? 0 "…naming where it is and moving that one stage (not the whole home)"
mkdir -p $HOME/.claude/agent-hub/stage-l
$B/jlog --stage stage-l --tag t "x" > /dev/null 2> $S/e2.err; check $? 1 "a stage in the legacy home while ~/agent-hub is the home: refused"
grep -q "but in $HOME/.claude/agent-hub: move the old home with .hub home migrate." $S/e2.err; check $? 0 "…pointing at hub home migrate"
rm -rf $HOME/.claude/agent-hub/stage-l
AGENT_HUB_HOME=$S/elsewhere $B/jlog --stage stage-new --tag t "x" > /dev/null 2>&1; check $? 0 "control: a stage in no other home starts here"
mkdir -p $S/elsewhere/stage-x; AGENT_HUB_HOME=$S/elsewhere $B/jlog --stage stage-x --tag t "x" > /dev/null 2>&1; check $? 0 "…and once the stage exists here, it is used"

# ================================================================== hub home
(cd $S/plain && HOME=$LH $B/hub home > $S/hh1.out 2>&1); check $? 0 "hub home: exit 0"
grep -q '^protected: yes' $S/hh1.out && grep -q 'hub home migrate' $S/hh1.out; check $? 0 "…the legacy home is reported protected, with the migrate command"
(cd $S/plain && $B/hub home > $S/hh2.out 2>&1)
grep -q '^protected: no' $S/hh2.out && grep -q "/add-dir $HOME/agent-hub" $S/hh2.out && grep -q '"additionalDirectories": \["'"$HOME/agent-hub"'"\]' $S/hh2.out; check $? 0 "…the grant lines for a session started elsewhere"
(cd $P && $B/hub home > $S/hh3.out 2>&1); grep -q 'needs no grant' $S/hh3.out; check $? 0 "…none needed inside the repository holding the home"

# ================================================================== migrate
export CLAUDE_BIN=$T/fake_claude_bg.py FAKE_AGENTS=none FAKE_BG_LOG=$S/bg-m.log
M=$S/mhome; L=$M/.claude/agent-hub; mkdir -p $L/stage-m/agents/a1 $L/stage-m/coordinator/work $L/.jwait-state $L/.state/x
printf '{"version": 1, "roles": {"a1": {"log": "%s/stage-m/agents/a1/log.jsonl", "cwd": "/w"}}}\n' $L > $L/stage-m/roles.json
printf '{"dir": "%s/stage-m/agents/a1", "report": "%s/stage-m/coordinator/work/a1-REPORT.md", "other": "%s2/x", "pid": 0, "session_id": "s"}\n' $L $L $L > $L/stage-m/agents/a1/meta.json
printf '{"offsets": {"%s/stage-m/coordinator/work/journal.md": 3}}\n' $L > $L/.jwait-state/hub.json
printf '{"chain": 1, "handoff": "%s/stage-m/coordinator/HANDOFF.md"}\n' $L > $L/stage-m/auto-handoff.json
printf '{"p": "%s"}\n' $L > $L/.state/x/s.json
printf -- '- 10:00 [hub-1] report %s/stage-m/coordinator/work/a1-REPORT.md\n' $L > $L/stage-m/coordinator/work/journal-2026-10-01.md
printf '#!/bin/sh\necho hi\n' > $L/stage-m/takeover.sh; chmod +x $L/stage-m/takeover.sh
: > $L/stage-m/.roles.lock
before=$(snap $L)
(cd $S/plain && HOME=$M $B/hub home migrate > $S/m1.out 2>&1); check $? 0 "migrate: a dry run by default (exit 0)"
grep -q "dry run: $L -> $M/agent-hub" $S/m1.out && grep -q '^files: 8 ' $S/m1.out && grep -q 'naming the old path (rewritten to the new one): 5' $S/m1.out; check $? 0 "…lists the files and the 5 JSON files to rewrite"
[ ! -e $M/agent-hub ] && [ "$(snap $L)" = "$before" ]; check $? 0 "…and writes nothing"
# a live agent of the source: refused
python3 -c 'import time, sys; time.sleep(60)' live-session-id & LIVE=$!
printf '{"pid": %s, "session_id": "live-session-id"}\n' $LIVE > $L/stage-m/agents/a1/meta.live.json
mkdir -p $L/stage-m/agents/a2; printf '{"pid": %s, "session_id": "live-session-id", "dir": "%s"}\n' $LIVE $L > $L/stage-m/agents/a2/meta.json
(cd $S/plain && HOME=$M $B/hub home migrate --apply > $S/m2.out 2>&1); check $? 1 "negative: --apply while an agent of the source is alive"
grep -q 'stage-m/a2 (pid' $S/m2.out && [ ! -e $M/agent-hub ] && [ -d $L ]; check $? 0 "…names it and copies nothing"
kill $LIVE 2>/dev/null; wait $LIVE 2>/dev/null; rm -rf $L/stage-m/agents/a2 $L/stage-m/agents/a1/meta.live.json
md_before=$(shasum < $L/stage-m/coordinator/work/journal-2026-10-01.md)
(cd $S/plain && HOME=$M $B/hub home migrate --apply > $S/m3.out 2>&1); check $? 0 "migrate --apply"
N=$M/agent-hub
grep -q 'copied and verified: 8 files' $S/m3.out && [ "$(find $N -type f | wc -l | tr -d ' ')" = 8 ]; check $? 0 "…copies and verifies every file"
[ -x $N/stage-m/takeover.sh ]; check $? 0 "…keeping modes (an executable takeover.sh)"
! grep -rqF -e "$L/" -e "$L\"" --include='*.json' $N && grep -q "\"dir\": \"$N/stage-m/agents/a1\"" $N/stage-m/agents/a1/meta.json \
  && grep -q "$N/stage-m/agents/a1/log.jsonl" $N/stage-m/roles.json && grep -q "$N/stage-m/coordinator/work/journal.md" $N/.jwait-state/hub.json \
  && grep -q "\"handoff\": \"$N/" $N/stage-m/auto-handoff.json && grep -q "\"p\": \"$N\"" $N/.state/x/s.json; check $? 0 "…rewrites the old path in every JSON file (roles, meta, .jwait-state, autopilot, .state)"
grep -q "\"other\": \"${L}2/x\"" $N/stage-m/agents/a1/meta.json; check $? 0 "…but not a longer name that merely starts with it"
check "$(shasum < $N/stage-m/coordinator/work/journal-2026-10-01.md)" "$md_before" "…leaves the Markdown history as written"
[ ! -e $L ] && [ -d $M/.claude/agent-hub.migrated-$(date +%Y%m%d) ]; check $? 0 "…renames the source to .migrated-YYYYMMDD (nothing deleted)"
(cd $S/plain && HOME=$M $B/hub home migrate > $S/m4.out 2>&1); check $? 0 "a second run: exit 0"
grep -q 'nothing to migrate' $S/m4.out; check $? 0 "…says there is nothing to migrate"
check "$(cd $S/plain && HOME=$M hh $S/plain)" "default $N" "after the move the user default is the home"
(cd $S/plain && HOME=$M $B/jlog --stage stage-m --tag t "after" > /dev/null 2>&1) && grep -q after $N/stage-m/coordinator/work/journal-$(today).md; check $? 0 "…and the stage goes on there"
# a background hub of a source stage still runs (an autopilot successor, its home pinned to the source): refused
A=$S/ma/.claude/agent-hub; mkdir -p $A/stage-a; echo '{"chain": 1, "pending": null}' > $A/stage-a/auto-handoff.json
(cd $S/plain && HOME=$S/ma FAKE_AGENTS=stale $B/hub home migrate --apply > $S/m6.out 2>&1); check $? 1 "negative: --apply while a background hub of a source stage runs"
grep -q 'stage-a-hub-2 (bg-older' $S/m6.out && [ -d $A ] && [ ! -e $S/ma/agent-hub ]; check $? 0 "…names it (claude stop) and copies nothing"
(cd $S/plain && HOME=$S/ma FAKE_AGENTS=none $B/hub home migrate --apply > $S/m7.out 2>&1); check $? 0 "control: with no background hub running, it migrates"
# a copy that fails half-way: nothing at the target (it would become the live home), the source untouched
F=$S/mf/.claude/agent-hub; mkdir -p $F/s1 $F/s2; echo a > $F/s1/a.md; echo b > $F/s2/b.md; chmod 000 $F/s2/b.md
(cd $S/plain && HOME=$S/mf $B/hub home migrate --apply > $S/m8.out 2>&1); rc=$?; chmod 644 $F/s2/b.md
check $rc 1 "negative: a file that cannot be read fails the migration"
[ ! -e $S/mf/agent-hub ] && [ -z "$(ls -A $S/mf | grep migrating)" ] && [ -f $F/s1/a.md ]; check $? 0 "…leaves no partial copy at the target (nor a staging directory) and the source in place"
check "$(cd $S/plain && HOME=$S/mf hh $S/plain | cut -d' ' -f1)" "legacy" "…so the home is still the legacy one"
# a target path that is a file where the source has a directory: refused before anything is written
G=$S/mg/.claude/agent-hub; mkdir -p $G/s1; echo a > $G/s1/a.md; mkdir -p $S/mg/agent-hub; echo x > $S/mg/agent-hub/s1
(cd $S/plain && HOME=$S/mg $B/hub home migrate --apply > $S/m9.out 2>&1); check $? 1 "negative: a file in the target where the source has a directory"
# a symlink into the old home follows the move
K=$S/mk/.claude/agent-hub; mkdir -p $K/s1; echo a > $K/s1/a.md; ln -s $K/s1/a.md $K/s1/link.md
(cd $S/plain && HOME=$S/mk $B/hub home migrate --apply > /dev/null 2>&1)
check "$(readlink $S/mk/agent-hub/s1/link.md)" "$S/mk/agent-hub/s1/a.md" "a symlink into the old home points into the new one"
unset CLAUDE_BIN FAKE_AGENTS FAKE_BG_LOG
# a file of the source already in the target: refused
L2=$S/m2/.claude/agent-hub; mkdir -p $L2/s $S/m2/agent-hub/s; echo a > $L2/s/f.md; echo b > $S/m2/agent-hub/s/f.md
(cd $S/plain && HOME=$S/m2 $B/hub home migrate --apply > $S/m5.out 2>&1); check $? 1 "negative: a file already in the target"
check "$(cat $S/m2/agent-hub/s/f.md)" "b" "…is never overwritten"
# a relative AGENT_HUB_HOME is made absolute (a child in another directory gets the same home)
check "$(cd $S && AGENT_HUB_HOME=rel hh $S)" "env $S/rel" "a relative AGENT_HUB_HOME resolves against the working directory"

# ================================================================== the autopilot strips AGENT_SESSION_ID (a unit check)
AGENT_SESSION_ID=x python3 -c "import sys; sys.path.insert(0, '$B'); import autopilot; sys.exit('AGENT_SESSION_ID' in autopilot.child_env())"; check $? 0 "autopilot.child_env drops AGENT_SESSION_ID"
exit $fail
