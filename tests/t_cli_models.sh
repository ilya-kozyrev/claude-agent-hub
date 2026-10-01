#!/bin/bash
# Latest models by default, through the CLI instead of pinned ids: the newer of `claude` on PATH and Claude Desktop's
# bundled CLI is started (and named); the id the run reports is recorded and shown (meta, status, the journal line,
# agent-top screen / --once / widget / --json); a CLI older than 2.1.285 is warned about once by spawn and hub start;
# `fable` is an alias like opus/sonnet/haiku, also for the effort rules and `hub reviewer`. Stand-in CLI: fake_claude.py.
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a HUB_TAG=hub-test
R=$AGENT_HUB_HOME; P=$(mktemp -d); W=$P/w; mkdir -p $W; echo "brief: do the thing" > $W/b.md
wait_dead(){ for i in $(seq 1 40); do $B/agent status $1 | grep -q 'ALIVE' || return 0; sleep 0.5; done; }
meta(){ python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(eval(sys.argv[2]))" $R/stage-a/agents/$1/meta.json "$2"; }

# ---- the newest CLI wins, and spawn says which one
FH=$P/fakehome; BD="$FH/Library/Application Support/Claude/claude-code"
mkdir -p "$BD/2.1.300/claude.app/Contents/MacOS" $P/pathbin
printf '#!/bin/sh\n[ "$1" = "--version" ] || echo bundle > "$PWD/which.log"\nexec python3 %s "$@"\n' $T/fake_claude.py > "$BD/2.1.300/claude.app/Contents/MacOS/claude"
printf '#!/bin/sh\n[ "$1" = "--version" ] || echo path > "$PWD/which.log"\nexec python3 %s "$@"\n' $T/fake_claude.py > $P/pathbin/claude
chmod +x "$BD/2.1.300/claude.app/Contents/MacOS/claude" $P/pathbin/claude
spawn_with(){ # spawn_with ROLE PATH-CLI-VERSION: no CLAUDE_BIN, HOME with the 2.1.300 bundle, a claude on PATH of that version
  rm -f $W/which.log
  (unset CLAUDE_BIN; HOME=$FH PATH=$P/pathbin:$PATH FAKE_VERSION=$2 $B/agent spawn --role $1 --cwd $W --model haiku --brief $W/b.md) > $P/$1.out 2>&1
  rc=$?; wait_dead $1; return $rc
}
spawn_with old 2.1.274; check $? 0 "spawn with an old claude on PATH and a newer Desktop bundle"
check "$(cat $W/which.log)" "bundle" "the newer bundled CLI is started, not the older claude on PATH"
grep -q "CLI .*2.1.300.*older" $P/old.out; check $? 0 "…and the spawn output names the CLI, its version and why"
spawn_with new 2.1.310; check $? 0 "a claude on PATH newer than the bundle"
check "$(cat $W/which.log)" "path" "negative: the newer claude on PATH is started"
grep -q "CLI .*pathbin/claude (2.1.310; claude on PATH" $P/new.out; check $? 0 "…and the output says PATH"
spawn_with tie 2.1.300; check $? 0 "a claude on PATH as new as the bundle"
check "$(cat $W/which.log)" "path" "negative: a tie keeps PATH"
spawn_with unk garbage; check $? 0 "a claude on PATH whose version cannot be read"
check "$(cat $W/which.log)" "path" "negative: an unreadable version keeps PATH"
rm -f $W/which.log
(unset CLAUDE_BIN; HOME=$FH PATH=$P/pathbin:$PATH FAKE_VERSION=2.1.274 CLAUDE_BIN=$P/pathbin/claude $B/agent spawn --role pin --cwd $W --model haiku --brief $W/b.md) > $P/pin.out 2>&1; wait_dead pin
check "$(cat $W/which.log)" "path" "negative: an explicit CLAUDE_BIN is never replaced by a newer CLI"
export CLAUDE_BIN=$T/fake_claude.py

# ---- the model the run reports is recorded and shown
spawn_out=$($B/agent spawn --role food --cwd $W --model sonnet --brief $W/b.md 2>&1); check $? 0 "spawn --model sonnet"
wait_dead food
check "$(meta food 'm["resolved_model"]')" "claude-sonnet-5-5" "meta records the id from the init event"
check "$(meta food 'm["model"]')" "sonnet" "…next to the alias that was asked for"
grep -q 'started headless agent food (claude-sonnet-5-5/high, asked for sonnet)' $(journal stage-a); check $? 0 "the start line shows the resolved id"
$B/agent status food > $P/st.out; grep -q '^food \[food\] claude-sonnet-5-5 (asked for sonnet): ' $P/st.out; check $? 0 "agent status shows the resolved id"
$B/agent spawn --role full --cwd $W --model claude-opus-5-5 --brief $W/b.md > /dev/null 2>&1; wait_dead full
grep -q 'started headless agent full (claude-opus-5-5/high)' $(journal stage-a); check $? 0 "negative: a full id needs no 'asked for'"
$B/agent status full | grep -q 'asked for'; check $? 1 "…nor does status"
AGENT_HUB_MODEL_MAP="sonnet=claude-sonnet-4-1" $B/agent spawn --role pinned --cwd $W --model sonnet --brief $W/b.md > /dev/null 2>&1; wait_dead pinned
check "$(meta pinned 'm["model"]')" "claude-sonnet-4-1" "AGENT_HUB_MODEL_MAP still pins an alias (opt-in)"
AGENT_TOP_AGENT_BIN=$B/agent $B/agent-top --once --stage stage-a --width 120 > $P/top.out 2>&1
grep -E '^. food ' $P/top.out | grep -q 'sonnet-5-5/hi'; check $? 0 "agent-top --once: MODEL shows sonnet-5-5"
grep -E '^. food ' $P/top.out | grep -Eq ' sonnet/hi'; check $? 1 "…not the bare alias"
$B/agent-top --widget --stage stage-a > $P/widget.html 2>&1; grep -q 'sonnet-5-5/hi' $P/widget.html; check $? 0 "agent-top widget shows sonnet-5-5"
$B/agent-top --json --stage stage-a > $P/top.json 2>&1
python3 -c 'import json,sys; a={x["role"]:x for x in json.load(open(sys.argv[1]))["agents"]}; assert a["food"]["model_id"]=="claude-sonnet-5-5" and a["food"]["model"]=="sonnet", a["food"]' $P/top.json; check $? 0 "agent-top --json: model_id next to model"
$B/agent-top --once --stage stage-a --agent food --width 120 > $P/card.out 2>&1; grep -q 'sonnet-5-5/hi' $P/card.out; check $? 0 "agent-top agent card shows sonnet-5-5"
# an agent started before this change has no resolved_model in its meta: the init event of its log says it
python3 - $R/stage-a/agents/food/meta.json <<'PY'
import json, sys
m = json.load(open(sys.argv[1])); m.pop("resolved_model"); json.dump(m, open(sys.argv[1], "w"))
PY
$B/agent-top --json --stage stage-a 2>/dev/null | python3 -c 'import json,sys; a={x["role"]:x for x in json.load(sys.stdin)["agents"]}; assert a["food"]["model_id"]=="claude-sonnet-5-5", a["food"]'; check $? 0 "agent-top falls back to the init event of the log"

# ---- an old CLI is warned about once, by spawn and by hub start; a current one is not
FAKE_VERSION=2.1.274 $B/agent spawn --role oldcli --cwd $W --model haiku --brief $W/b.md > $P/oldcli.out 2>&1; check $? 0 "spawn with CLI 2.1.274 still starts the agent"
wait_dead oldcli
[ "$(grep -c 'older than 2.1.285' $P/oldcli.out)" = 1 ]; check $? 0 "…with one warning"
grep -q 'update Claude Code; with an older CLI the aliases' $P/oldcli.out; check $? 0 "…that says to update and why"
$B/agent spawn --role newcli --cwd $W --model haiku --brief $W/b.md > $P/newcli.out 2>&1; wait_dead newcli
grep -q 'older than' $P/newcli.out; check $? 1 "negative: CLI 2.1.285 gets no warning"
H1=11111111-1111-4111-8111-111111111111
FAKE_VERSION=2.1.274 $B/hub start --stage web --session $H1 --dry-run > $P/start-old.out 2>&1; check $? 0 "hub start with CLI 2.1.274"
[ "$(grep -c 'older than 2.1.285' $P/start-old.out)" = 1 ] && grep -q '^ATTENTION: Claude Code 2.1.274' $P/start-old.out; check $? 0 "…warns once"
$B/hub start --stage web --session $H1 --dry-run > $P/start-new.out 2>&1
grep -q 'older than' $P/start-new.out; check $? 1 "negative: hub start with CLI 2.1.285 does not warn"

# ---- fable is an alias like the others
$B/agent spawn --role fab --cwd $W --model fable --brief $W/b.md > $P/fab.out 2>&1; check $? 0 "spawn --model fable is accepted"
wait_dead fab
grep -q -- '--model fable --effort high' $W/argv.log; check $? 0 "…passed to the CLI as is, with an effort"
check "$(meta fab 'm["resolved_model"]')" "claude-fable-5-1" "…and resolved to the latest fable"
mkdir -p $W/.git $W/.agent-hub
echo '{"AGENT_HUB_EFFORT_RULES": {"fable": "high|xhigh"}}' > $W/.agent-hub/config.json
$B/agent spawn --role fab2 --cwd $W --model fable --effort medium --brief $W/b.md > $P/fab2.out 2>&1; check $? 2 "the effort rules match the alias: fable at medium is denied"
grep -q 'fable runs only at effort high or xhigh' $P/fab2.out; check $? 0 "…naming the rule"
$B/agent spawn --role fab3 --cwd $W --model fable --effort xhigh --brief $W/b.md > /dev/null 2>&1; check $? 0 "positive control: fable at xhigh is allowed"
wait_dead fab3; rm $W/.agent-hub/config.json
AGENT_HUB_REVIEW_MODEL=fable $B/hub reviewer > $P/rev.out 2> $P/rev.err; check $? 0 "hub reviewer takes fable as AGENT_HUB_REVIEW_MODEL"
grep -q 'agent fable/high' $P/rev.out && ! grep -q 'using opus' $P/rev.err; check $? 0 "…and keeps it (no fallback to opus)"
grep -q -- '--model fable' $P/rev.out; check $? 0 "…and the start line names it"
AGENT_HUB_REVIEW_MODEL=gpt $B/hub reviewer > $P/rev2.out 2> $P/rev2.err
grep -q 'using opus' $P/rev2.err; check $? 0 "negative: a model that is no alias still falls back"
exit $fail
