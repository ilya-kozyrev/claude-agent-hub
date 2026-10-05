#!/bin/bash
# The text-answer skill is discoverable by both hosts and its CLI examples execute.
. "$(dirname "$0")/lib.sh"
new_home
export PYTHONDONTWRITEBYTECODE=1 CODEX_HOME="$AGENT_HUB_HOME/codex" CLAUDE_CONFIG_DIR="$AGENT_HUB_HOME/claude"
python3 - "$B" "$AGENT_HUB_HOME" <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys

binpath, home = map(Path, sys.argv[1:])
root = binpath.parent
claude = json.loads((root / '.claude-plugin/plugin.json').read_text())
codex = json.loads((root / '.codex-plugin/plugin.json').read_text())
for manifest in (claude, codex):
    skills = root / manifest.get('skills', './skills/')
    text = (skills / 'status/SKILL.md').read_text()
    assert re.search(r'^name: status$', text, re.M)
    assert re.search(r'^description: .*what is running.*что сейчас работает', text, re.M)
    assert 'disable-model-invocation: true' not in text
    assert 'PLUGIN_ROOT' in text and 'CLAUDE_PLUGIN_ROOT' in text
    assert not (skills / 'agent-top').exists()
assert len(text) < 3500 and len(text) < len((root / 'skills/hub/SKILL.md').read_text()) / 4
print('PASS both hosts discover the short model-invoked status skill, without agent-top skill')

folder = home / 'stage-a/agents/status-fixture'
folder.mkdir(parents=True)
(folder / 'meta.json').write_text(json.dumps({
    'role': 'status-fixture', 'pid': os.getpid(), 'process_token': str(binpath), 'engine': 'codex',
    'started_at': datetime.now(timezone.utc).isoformat(),
}))
# The test process stays alive while the collector reads its fixture; no extra worker is launched.
events = [
    {'type': 'turn.started'},
    {'type': 'item.completed', 'item': {'id': 'message', 'type': 'agent_message', 'text': 'Fixture work'}},
    {'type': 'item.started', 'item': {'id': 'command', 'type': 'command_execution', 'command': 'fixture work'}},
]
(folder / 'log.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
cmd = [str(binpath / 'agent-top'), '--json']
# Extract every long option named by the skill, so new examples cannot evade this control.
flags = set(re.findall(r'--[a-z][a-z-]*', text))
help_result = subprocess.run([str(binpath / 'agent-top'), '--help'], capture_output=True, text=True, check=True)
assert flags <= set(re.findall(r'--[a-z][a-z-]*', help_result.stdout)), flags
assert '--not-a-real-status-flag' not in help_result.stdout  # negative control
for args in ([], ['--stage', 'stage-a'], ['--stage', 'stage-a', '--stage', 'empty-stage'],
             ['--all', '--stage', 'stage-a', '--agent', 'status-fixture', '--feed', '10']):
    result = subprocess.run(cmd + args, capture_output=True, text=True, timeout=30, check=True)
    snapshot = json.loads(result.stdout)
    agent = next(a for a in snapshot['agents'] if a['role'] == 'status-fixture')
    assert {'started_at', 'age_s', 'last_text', 'unread'} <= agent.keys(), agent
    assert agent['state'] == 'live' and agent['started_at'] and agent['last_text'] == 'Fixture work'
    assert isinstance(agent['action'], dict) and 'elapsed_s' in agent['action'], agent['action']
    assert 'locks' in snapshot and 'questions_ok' in snapshot
    if '--agent' in args:
        assert snapshot['feed']['agent'] == 'status-fixture'
invalid = subprocess.run(cmd + ['--not-a-real-status-flag'], capture_output=True, text=True)
assert invalid.returncode == 2
print('PASS status commands execute with JSON, stage, all, agent and feed; invalid option rejected')
print('PASS JSON fixture includes every status field, including nested action.elapsed_s')
PY
rc=$?
[ "$rc" = 0 ] || exit "$rc"
