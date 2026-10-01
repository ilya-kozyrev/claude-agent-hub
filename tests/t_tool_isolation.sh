#!/bin/bash
# Tool isolation: an agent starts with the plugin's bin/ first on PATH and its brief footer names jlog by absolute path;
# `hub start` and the SessionStart hook warn (once) when a same-named command earlier on PATH shadows one of the
# plugin's tools (GitHub CLI `hub` from Homebrew is the usual one). Positive and negative controls throughout.
. "$(dirname "$0")/lib.sh"
new_home; R=$AGENT_HUB_HOME; P=$(mktemp -d); W=$P/w; mkdir -p $W $P/pybin $P/shadow $P/linkbin
BP=$(cd $B && pwd -P)
export HOME=$P/emptyhome; mkdir -p $HOME  # no Claude Desktop bundle: the CLI warning is not under test here
ln -s "$(command -v python3)" $P/pybin/python3
wait_dead(){ for i in $(seq 1 40); do $B/agent status $1 | grep -q 'ALIVE' || return 0; sleep 0.5; done; }

# ---- agent spawn: bin/ first on the agent's PATH, jlog by absolute path in the footer
echo "brief: do the thing" > $W/b.md
(export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py PATH="$P/shadow:$PATH"
 $B/agent spawn --role iso --cwd $W --model haiku --brief $W/b.md > $P/spawn.out 2>&1; check $? 0 "spawn with another directory first on the caller's PATH"
 wait_dead iso)
check "$(grep '^PATH_FIRST=' $W/env.log | tail -1)" "PATH_FIRST=$BP" "the agent's PATH starts with the plugin's bin/"
grep -qF "\`$BP/jlog \"…\"\`" $W/prompts.log; check $? 0 "the brief footer names jlog by its absolute path"
grep -qF "\`$BP/jlog \"@hub QUESTION" $W/prompts.log; check $? 0 "…in the question line too"
grep -q '`jlog "' $W/prompts.log; check $? 1 "negative: no bare \`jlog\` is left in the footer"

# ---- hub start warns about a shadowing command
H1=11111111-1111-4111-8111-111111111111
for t in hub jlog; do printf '#!/bin/sh\necho other %s\n' $t > $P/shadow/$t; chmod +x $P/shadow/$t; done
ln -s $BP/jlog $P/linkbin/jlog; ln -s $BP/ask $P/linkbin/ask
(PATH="$P/shadow:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/s1.out 2>&1; check $? 0 "hub start with an old hub and jlog first on PATH"
[ "$(grep -c '^ATTENTION: .*is .*shadow/' $P/s1.out)" = 1 ]; check $? 0 "…warns once"
grep -q "ATTENTION: \`hub\` is $P/shadow/hub, \`jlog\` is $P/shadow/jlog" $P/s1.out; check $? 0 "…naming every shadowing path"
grep -q "put the plugin's bin/ first on PATH, or remove the old tool" $P/s1.out; check $? 0 "…and the fix"
grep -q 'GitHub CLI `hub` from Homebrew' $P/s1.out; check $? 0 "…and the usual culprit"
(PATH="$BP:$P/shadow:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/s2.out 2>&1
grep -q 'shadow' $P/s2.out; check $? 1 "negative: the plugin's bin/ first on PATH, no warning"
(PATH="$P/linkbin:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/s3.out 2>&1
grep -q 'shadow\|linkbin' $P/s3.out; check $? 1 "negative: a symlink into the plugin's bin/ is not a shadow"
(PATH="$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/s4.out 2>&1; check $? 0 "hub start without any shadow"
grep -q '^ATTENTION' $P/s4.out; check $? 1 "…prints no ATTENTION line"

# ---- the SessionStart hook
hook(){ # hook CWD [PATH]: the hook's output for a session starting in CWD
  printf '{"cwd": "%s"}' "$1" | PATH="${2:-$P/shadow:$BP:$P/pybin}" python3 $HOOKS/path_shadow.py
}
python3 -c 'import json,sys; h=json.load(open(sys.argv[1]))["hooks"]["SessionStart"]; assert any("path_shadow.py" in x["command"] for g in h for x in g["hooks"])' $HOOKS/hooks.json; check $? 0 "hooks.json runs path_shadow.py at SessionStart"
mkdir -p $P/proj/.agent-hub $P/plain
hook $P/proj > $P/h1.out; check $? 0 "hook in a repository with .agent-hub/"
python3 -c 'import json,sys; c=json.load(open(sys.argv[1]))["hookSpecificOutput"]; assert c["hookEventName"]=="SessionStart" and "`hub` is" in c["additionalContext"] and "first on PATH" in c["additionalContext"], c' $P/h1.out; check $? 0 "…prints the warning as session context"
hook $P/proj > $P/h2.out; [ -s $P/h2.out ]; check $? 0 "…and again at the next session start (in scope: every time)"
hook $P/proj $BP:$P/pybin > $P/h3.out; check $? 0 "hook without a shadow"
[ ! -s $P/h3.out ]; check $? 0 "negative: …prints nothing"
hook $P/plain > $P/h4.out; [ -s $P/h4.out ]; check $? 0 "outside any hub scope the first session start still hears it"
hook $P/plain > $P/h5.out; [ ! -s $P/h5.out ]; check $? 0 "negative: …but the same shadowing set is not repeated"
printf '#!/bin/sh\n' > $P/shadow/lock; chmod +x $P/shadow/lock
hook $P/plain > $P/h6.out; [ -s $P/h6.out ]; check $? 0 "a new shadowing command is reported again"
HUB_TAG=x hook $P/plain > $P/h7.out; [ -s $P/h7.out ]; check $? 0 "a hub agent (HUB_TAG) hears it every time"
printf 'not json' | PATH="$P/shadow:$BP:$P/pybin" python3 $HOOKS/path_shadow.py > /dev/null; check $? 0 "fail-open: a broken event does not fail the hook"
exit $fail
