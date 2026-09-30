#!/bin/bash
# Run every tests/t_*.sh with HOME and AGENT_HUB_HOME in throw-away directories, so no test can read or write a
# real hub home. Prints one summary line per script and exits non-zero if any script fails.
set -u
T="$(cd "$(dirname "$0")" && pwd)"; B="$(cd "$T/../bin" && pwd)"
OUT="${1:-$(mktemp -d)}"; mkdir -p "$OUT"
export HOME="$(mktemp -d)"; export AGENT_HUB_HOME="$HOME/hub-home"
# Positive control: the tools honour AGENT_HUB_HOME, and without it they fall back to $HOME/.claude/agent-hub —
# which is the throw-away HOME above, never the real one.
AGENT_HUB_TZ=UTC "$B/jlog" --stage stage-a --tag probe "env control" > /dev/null
ls "$AGENT_HUB_HOME"/stage-a/coordinator/work/journal-*.md > /dev/null 2>&1; ctl1=$?
( unset AGENT_HUB_HOME; AGENT_HUB_TZ=UTC "$B/jlog" --stage stage-a --tag probe "default control" > /dev/null )
ls "$HOME"/.claude/agent-hub/stage-a/coordinator/work/journal-*.md > /dev/null 2>&1; ctl2=$?
echo "control: AGENT_HUB_HOME honoured=$([ $ctl1 = 0 ] && echo yes || echo NO); default under the test HOME=$([ $ctl2 = 0 ] && echo yes || echo NO) ($HOME)"
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
