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

# ---- agent spawn: bin/ first on the agent's PATH, jlog as "$HUB_BIN/jlog" in the footer
echo "brief: do the thing" > $W/b.md
(export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py PATH="$P/shadow:$PATH"
 $B/agent spawn --role iso --cwd $W --model haiku --brief $W/b.md > $P/spawn.out 2>&1; check $? 0 "spawn with another directory first on the caller's PATH"
 wait_dead iso)
check "$(grep '^PATH_FIRST=' $W/env.log | tail -1)" "PATH_FIRST=$BP" "the agent's PATH starts with the plugin's bin/"
check "$(grep '^HUB_BIN=' $W/env.log | tail -1)" "HUB_BIN=$BP" "the agent's environment names the plugin's bin/ in HUB_BIN"
grep -qF '`"$HUB_BIN/jlog" "…"`' $W/prompts.log; check $? 0 "the brief footer names jlog as \"\$HUB_BIN/jlog\""
grep -qF '`"$HUB_BIN/jlog" "@hub QUESTION' $W/prompts.log; check $? 0 "…in the question line too"
grep -q '`jlog "' $W/prompts.log; check $? 1 "negative: no bare \`jlog\` is left in the footer"
grep -qF "$BP/jlog" $W/prompts.log; check $? 1 "negative: …and no version-pinned path either (it vanishes with a plugin update)"
# a resume after a plugin update: the footer of the first prompt is history, the variable is rebuilt by the new copy
cp -R $BP $P/binA; cp -R $BP $P/binB
(export HUB_STAGE=stage-a HUB_TAG=hub-test CLAUDE_BIN=$T/fake_claude.py
 $P/binA/agent spawn --role upd --cwd $W --model haiku --brief $W/b.md > /dev/null 2>&1; wait_dead upd
 $P/binB/agent send upd "after the update" > /dev/null 2>&1; check $? 0 "resume through the updated copy of the plugin"
 wait_dead upd)
grep '^HUB_BIN=' $W/env.log | tail -2 | tr '\n' ' ' | grep -q "HUB_BIN=$(cd $P/binA && pwd -P) HUB_BIN=$(cd $P/binB && pwd -P)"; check $? 0 "…HUB_BIN of the spawn is the old copy, of the resume the new one"

# ---- hub start warns about a shadowing command
H1=11111111-1111-4111-8111-111111111111
for t in hub jlog; do printf '#!/bin/sh\necho other %s\n' $t > $P/shadow/$t; chmod +x $P/shadow/$t; done
ln -s $BP/jlog $P/linkbin/jlog; ln -s $BP/ask $P/linkbin/ask
mkdir -p $P/shadow2; for t in agent-spawn nightq board.py hubcore.py; do printf '#!/bin/sh\n' > $P/shadow2/$t; chmod +x $P/shadow2/$t; done
(PATH="$P/shadow:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/s1.out 2>&1; check $? 0 "hub start with an old hub and jlog first on PATH"
[ "$(grep -c '^ATTENTION: .*is .*shadow/' $P/s1.out)" = 1 ]; check $? 0 "…warns once"
grep -q "ATTENTION: \`hub\` is $P/shadow/hub, \`jlog\` is $P/shadow/jlog" $P/s1.out; check $? 0 "…naming every shadowing path"
grep -q "put the plugin's bin/ first on PATH, or remove the old tool" $P/s1.out; check $? 0 "…and the fix"
grep -q 'GitHub CLI `hub` from Homebrew' $P/s1.out; check $? 0 "…and the usual culprit"
# the commands are every executable of bin/, not a fixed list: agent-spawn and nightq count, the .py modules do not
(PATH="$P/shadow2:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/s5.out 2>&1; check $? 0 "hub start with an old agent-spawn and nightq first on PATH"
grep -q "ATTENTION: \`agent-spawn\` is $P/shadow2/agent-spawn, \`nightq\` is $P/shadow2/nightq" $P/s5.out; check $? 0 "…names exactly those two (board.py and hubcore.py there are not commands)"
python3 - $BP > $P/tools.out <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1]); import hubcore as hc
want = sorted(n for n in os.listdir(sys.argv[1]) if os.path.isfile(os.path.join(sys.argv[1], n)) and os.access(os.path.join(sys.argv[1], n), os.X_OK) and "." not in n)
print("ok" if hc.plugin_tools() == want and {"agent-stop", "agent-send", "delegation", "nightq", "hub", "jlog"} <= set(want) else f"{hc.plugin_tools()} != {want}")
PY
check "$(cat $P/tools.out)" ok "plugin_tools() is the executables of bin/ (agent-stop, delegation, nightq included)"
(PATH="$BP:$P/shadow:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/s2.out 2>&1
grep -q 'shadow' $P/s2.out; check $? 1 "negative: the plugin's bin/ first on PATH, no warning"
(PATH="$P/linkbin:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/s3.out 2>&1
grep -q 'shadow\|linkbin' $P/s3.out; check $? 1 "negative: a symlink into the plugin's bin/ is not a shadow"
(PATH="$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/s4.out 2>&1; check $? 0 "hub start without any shadow"
grep -q '^ATTENTION' $P/s4.out; check $? 1 "…prints no ATTENTION line"
# a personal dispatcher into the plugin: its own marker line (symlinks resolved), or a copy inside an installed plugin's bin/
mkdir -p $P/disp $P/disp-nomark $P/disp-late
printf '#!/bin/sh\n# delamain: dispatcher\nexec true\n' > $P/disp/delamain-tool
printf '#!/bin/sh\nexec true\n' > $P/disp-nomark/delamain-tool
{ printf '#!/bin/sh\n'; for i in $(seq 1 20); do echo "# filler $i"; done; echo '# delamain: dispatcher'; } > $P/disp-late/delamain-tool
for d in disp disp-nomark disp-late; do chmod +x $P/$d/delamain-tool; for t in hub jlog; do ln -s delamain-tool $P/$d/$t; done; done
(PATH="$P/disp:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/d1.out 2>&1; check $? 0 "hub start with a marked dispatcher first on PATH"
grep -q 'ATTENTION' $P/d1.out; check $? 1 "…no warning: a symlink to a file with the dispatcher marker is the plugin's own"
(PATH="$P/disp-nomark:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/d2.out 2>&1
grep -q "ATTENTION: \`hub\` is $P/disp-nomark/hub, \`jlog\` is $P/disp-nomark/jlog" $P/d2.out; check $? 0 "negative: the same dispatcher without the marker is still reported"
(PATH="$P/disp-late:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/d3.out 2>&1
grep -q "ATTENTION: \`hub\` is $P/disp-late/hub" $P/d3.out; check $? 0 "negative: a marker far from the top of the file does not count"
(PATH="$P/shadow:$P/disp:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/d4.out 2>&1
grep -q "ATTENTION: \`hub\` is $P/shadow/hub, \`jlog\` is $P/shadow/jlog" $P/d4.out; check $? 0 "negative: a foreign hub (GitHub CLI style) ahead of the dispatcher is still reported"
CC=$P/cfg; mkdir -p $CC/plugins/cache/mk/delamain/99.0.0/bin $CC/plugins/marketplaces/self/bin; : > $CC/plugins/marketplaces/self/bin/hubcore.py
for t in hub jlog; do printf '#!/bin/sh\necho installed %s\n' $t > $CC/plugins/cache/mk/delamain/99.0.0/bin/$t; chmod +x $CC/plugins/cache/mk/delamain/99.0.0/bin/$t; done
printf '#!/bin/sh\n' > $CC/plugins/marketplaces/self/bin/lock; chmod +x $CC/plugins/marketplaces/self/bin/lock
(CLAUDE_CONFIG_DIR=$CC PATH="$CC/plugins/cache/mk/delamain/99.0.0/bin:$CC/plugins/marketplaces/self/bin:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/d5.out 2>&1
grep -q "not the plugin's own tool" $P/d5.out; check $? 1 "a command inside an installed plugin's cache or marketplace bin/ is the plugin's own"
(CLAUDE_CONFIG_DIR=$P/elsewhere PATH="$CC/plugins/cache/mk/delamain/99.0.0/bin:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/d6.out 2>&1
grep -q "ATTENTION: \`hub\` is $CC/plugins/cache/mk/delamain/99.0.0/bin/hub" $P/d6.out; check $? 0 "negative: the same directory is foreign when it is not under an installed plugin location"
mkdir -p $CC/plugins/cache/mk/delamain/0.0.1/bin $CC/plugins/marketplaces/old/bin $CC/plugins/marketplaces/old/.claude-plugin
printf '#!/bin/sh\n' > $CC/plugins/cache/mk/delamain/0.0.1/bin/hub; printf '#!/bin/sh\n' > $CC/plugins/marketplaces/old/bin/lock; : > $CC/plugins/marketplaces/old/bin/hubcore.py
chmod +x $CC/plugins/cache/mk/delamain/0.0.1/bin/hub $CC/plugins/marketplaces/old/bin/lock
printf '{"name": "delamain", "version": "0.0.2"}\n' > $CC/plugins/marketplaces/old/.claude-plugin/plugin.json
(CLAUDE_CONFIG_DIR=$CC PATH="$CC/plugins/cache/mk/delamain/0.0.1/bin:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/d7.out 2>&1
grep -q "ATTENTION: \`hub\` is $CC/plugins/cache/mk/delamain/0.0.1/bin/hub" $P/d7.out; check $? 0 "negative: an installed copy older than this plugin (cache folder 0.0.1) is still a shadow"
(CLAUDE_CONFIG_DIR=$CC PATH="$CC/plugins/marketplaces/old/bin:$BP:$P/pybin" $B/hub start --stage web --session $H1 --dry-run) > $P/d8.out 2>&1
grep -q "ATTENTION: \`lock\` is $CC/plugins/marketplaces/old/bin/lock" $P/d8.out; check $? 0 "negative: …and so is a marketplace copy whose manifest says 0.0.2"

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
(export AGENT_HUB_HOME=$P/nohome; hook $P/proj > $P/h8.out; check $? 0 "hook on a machine without a hub home"
 [ ! -s $P/h8.out ] && [ ! -e $P/nohome ]; check $? 0 "negative: …says nothing and creates nothing (no .state/path-shadow)")
(export AGENT_HUB_HOME=$P/nohome; hook $P/plain > $P/h9.out; [ ! -s $P/h9.out ] && [ ! -e $P/nohome ]); check $? 0 "…also outside any scope"
mkdir $P/nohome; (export AGENT_HUB_HOME=$P/nohome; hook $P/plain > $P/h10.out); [ -s $P/h10.out ]; check $? 0 "positive control: once the hub home exists the hook speaks"
printf 'not json' | PATH="$P/shadow:$BP:$P/pybin" python3 $HOOKS/path_shadow.py > /dev/null; check $? 0 "fail-open: a broken event does not fail the hook"

# ---- $HUB_BIN: a --bg session gets the daemon's environment, with the HUB_BIN of the plugin version the daemon started under
rm -rf $P/shadow; export AGENT_HUB_HOME=$P/nohome  # no shadow, an existing hub home: only HUB_BIN is under test
hubbin(){ # hubbin STALE|CURRENT|UNSET|NOFILE: runs the hook the way Claude Code does for SessionStart, env file in $P/envfile
  rm -f $P/envfile; : > $P/envfile
  case $1 in
    STALE)   env HUB_BIN=$P/old-0.7.1/bin CLAUDE_ENV_FILE=$P/envfile CLAUDE_PLUGIN_ROOT=$(dirname $BP) PATH="$BP:$P/pybin" python3 $HOOKS/path_shadow.py < /dev/null;;
    CURRENT) env HUB_BIN=$BP CLAUDE_ENV_FILE=$P/envfile CLAUDE_PLUGIN_ROOT=$(dirname $BP) PATH="$BP:$P/pybin" python3 $HOOKS/path_shadow.py < /dev/null;;
    UNSET)   env -u HUB_BIN CLAUDE_ENV_FILE=$P/envfile CLAUDE_PLUGIN_ROOT=$(dirname $BP) PATH="$BP:$P/pybin" python3 $HOOKS/path_shadow.py < /dev/null;;
    NOFILE)  env -u CLAUDE_ENV_FILE HUB_BIN=$P/old-0.7.1/bin CLAUDE_PLUGIN_ROOT=$(dirname $BP) PATH="$BP:$P/pybin" python3 $HOOKS/path_shadow.py < /dev/null;;
  esac
}
hubbin STALE > $P/hb1.out; check $? 0 "HUB_BIN: a stale value (the daemon's)"
check "$(cat $P/envfile)" "export HUB_BIN=$BP" "…the env file now carries this plugin's bin/"
python3 -c 'import json,sys; c=json.load(open(sys.argv[1]))["hookSpecificOutput"]["additionalContext"]; assert c.count(chr(10))==0 and "old-0.7.1/bin" in c and sys.argv[2] in c, c' $P/hb1.out "$BP"; check $? 0 "…and one line says what it replaced"
hubbin CURRENT > $P/hb2.out; check "$(wc -c < $P/envfile | tr -d ' '):$(wc -c < $P/hb2.out | tr -d ' ')" "0:0" "negative: a current HUB_BIN — nothing written, nothing said"
ln -s $BP $P/link-bin; (rm -f $P/envfile; : > $P/envfile; env HUB_BIN=$P/link-bin CLAUDE_ENV_FILE=$P/envfile CLAUDE_PLUGIN_ROOT=$(dirname $BP) PATH="$BP:$P/pybin" python3 $HOOKS/path_shadow.py < /dev/null > $P/hb3.out)
check "$(wc -c < $P/envfile | tr -d ' '):$(wc -c < $P/hb3.out | tr -d ' ')" "0:0" "negative: …also when it is a symlink to this bin/"
hubbin UNSET > $P/hb4.out; check "$(cat $P/envfile):$(wc -c < $P/hb4.out | tr -d ' ')" "export HUB_BIN=$BP:0" "an unset HUB_BIN is set, without a notice (nothing was stale)"
hubbin NOFILE > $P/hb5.out; check "$?:$(wc -c < $P/hb5.out | tr -d ' ')" "0:0" "no CLAUDE_ENV_FILE (Codex): nothing to write, nothing said, no failure"
(export AGENT_HUB_HOME=$P/nohome2; hubbin STALE > $P/hb6.out; check "$(wc -c < $P/envfile | tr -d ' '):$(wc -c < $P/hb6.out | tr -d ' ')" "0:0" "negative: on a machine without a hub home the hook still writes nothing")
mkdir -p $P/shadow; printf '#!/bin/sh\n' > $P/shadow/hub; chmod +x $P/shadow/hub
env HUB_BIN=$P/old-0.7.1/bin CLAUDE_ENV_FILE=$P/envfile CLAUDE_PLUGIN_ROOT=$(dirname $BP) PATH="$P/shadow:$BP:$P/pybin" python3 $HOOKS/path_shadow.py < /dev/null > $P/hb7.out
python3 -c 'import json,sys; c=json.load(open(sys.argv[1]))["hookSpecificOutput"]["additionalContext"]; assert "HUB_BIN" in c and "`hub` is" in c, c' $P/hb7.out; check $? 0 "a stale HUB_BIN and a shadowing command: both lines, one hook output"

# The plugin whose hook runs decides, not a root the session inherited: a Claude worker started from a Codex host carries
# the host's PLUGIN_ROOT (an older copy) next to the correct HUB_BIN `agent spawn` set.
rm -rf $P/shadow; mkdir -p $P/oldroot; cp -R $BP $P/oldroot/bin
hb(){ env CLAUDE_ENV_FILE=$P/envfile PATH="$BP:$P/pybin" "$@" python3 $HOOKS/path_shadow.py < /dev/null; }
: > $P/envfile; hb HUB_BIN=$BP PLUGIN_ROOT=$P/oldroot CLAUDE_PLUGIN_ROOT=$(dirname $BP) > $P/hb8.out
check "$(wc -c < $P/envfile | tr -d ' '):$(wc -c < $P/hb8.out | tr -d ' ')" "0:0" "HUB_BIN: a correct value is not rewritten to an inherited PLUGIN_ROOT's older bin/"
: > $P/envfile; hb HUB_BIN=$P/old-0.7.1/bin PLUGIN_ROOT=$P/oldroot CLAUDE_PLUGIN_ROOT=$(dirname $BP) > $P/hb9.out
check "$(cat $P/envfile)" "export HUB_BIN=$BP" "…and a stale one is replaced with the bin/ of the hook that runs, not the inherited root's"
: > $P/envfile; hb HUB_BIN=$P/old-0.7.1/bin CLAUDE_PLUGIN_ROOT=$P/oldroot > $P/hb10.out
check "$(wc -c < $P/envfile | tr -d ' '):$(wc -c < $P/hb10.out | tr -d ' ')" "0:0" "negative: CLAUDE_PLUGIN_ROOT naming another copy than the hook's own — ambiguous, nothing is rewritten"
: > $P/envfile; hb HUB_BIN=$P/old-0.7.1/bin CLAUDE_PLUGIN_ROOT=$(dirname $BP) > $P/hb11.out
check "$(cat $P/envfile)" "export HUB_BIN=$BP" "positive control: with the two agreeing, a stale value is replaced"
exit $fail
