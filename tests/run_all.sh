#!/bin/bash
# Run every tests/t_*.sh with HOME and AGENT_HUB_HOME in throw-away directories, so no test can read or write a
# real hub home. Prints one summary line per script and exits non-zero if any script fails.
set -u
T="$(cd "$(dirname "$0")" && pwd)"; B="$(cd "$T/../bin" && pwd)"
OUT="${1:-$(mktemp -d)}"; mkdir -p "$OUT"
export HOME="$(mktemp -d)"; export AGENT_HUB_HOME="$HOME/hub-home"
# Positive control: the tools honour AGENT_HUB_HOME, and without it they fall back to $HOME/agent-hub — of a throw-away
# HOME, never the real one; a HOME of its own, run from it (no repository's .agent-hub/ around): a stage in the test
# HOME's ~/agent-hub would make every test's stage-a "a stage in another home".
AGENT_HUB_TZ=UTC "$B/jlog" --stage stage-a --tag probe "env control" > /dev/null
ls "$AGENT_HUB_HOME"/stage-a/coordinator/work/journal-*.md > /dev/null 2>&1; ctl1=$?
CTL_HOME="$(mktemp -d)"
( unset AGENT_HUB_HOME; cd "$CTL_HOME" && HOME="$CTL_HOME" AGENT_HUB_TZ=UTC "$B/jlog" --stage stage-a --tag probe "default control" > /dev/null )
ls "$CTL_HOME"/agent-hub/stage-a/coordinator/work/journal-*.md > /dev/null 2>&1; ctl2=$?
echo "control: AGENT_HUB_HOME honoured=$([ $ctl1 = 0 ] && echo yes || echo NO); default ~/agent-hub under a test HOME=$([ $ctl2 = 0 ] && echo yes || echo NO) ($CTL_HOME)"
total=0; failed=0; [ $ctl1 = 0 ] && [ $ctl2 = 0 ] || failed=1
for t in "$T"/t_*.sh; do
  name=$(basename "$t" .sh)
  bash "$t" > "$OUT/$name.log" 2>&1; rc=$?
  p=$(grep -c '^PASS' "$OUT/$name.log"); f=$(grep -c '^FAIL' "$OUT/$name.log")
  total=$((total + p + f))
  echo "$name: exit=$rc pass=$p fail=$f"
  [ $rc = 0 ] && [ $f = 0 ] || failed=1
done
echo "checks: $total; logs: $OUT"
exit $failed
