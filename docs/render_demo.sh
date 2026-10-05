#!/bin/bash
# Regenerates the README screens from synthetic data: docs/agent-top-once.txt.
set -eu
D="$(cd "$(dirname "$0")" && pwd)"; B="$D/../bin"
export AGENT_HUB_HOME="$(mktemp -d)" HOME="$(mktemp -d)" AGENT_HUB_TZ=UTC
S1=11111111-aaaa-4aaa-8aaa-111111111111; S2=22222222-bbbb-4bbb-8bbb-222222222222
python3 -c 'import time; time.sleep(120)' $S1 $S2 & SLEEPER=$!
trap 'kill $SLEEPER 2>/dev/null' EXIT
python3 "$D/demo/make_demo_home.py" "$AGENT_HUB_HOME" $SLEEPER $S1 $S2 > /dev/null
NO_COLOR=1 "$B/agent-top" --once --width 120 > "$D/agent-top-once.txt"
echo "written: docs/agent-top-once.txt"
