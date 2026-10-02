#!/bin/bash
. "$(dirname "$0")/lib.sh"
new_home
export CODEX_HOME="$AGENT_HUB_HOME/codex" PYTHONDONTWRITEBYTECODE=1
python3 - "$B" "$AGENT_HUB_HOME" <<'PY'
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

b, root = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(b))
import codex_limits as limits
import codex_rollouts as rollouts
folder = Path(os.environ['CODEX_HOME']) / 'sessions/2026/10/02'
folder.mkdir(parents=True)

def write(name, events):
    path = folder / f'rollout-{name}.jsonl'
    meta = {'type': 'session_meta', 'payload': {'id': name, 'source': 'cli'}}
    path.write_text(''.join(json.dumps(e) + '\n' for e in [meta, *events]))
    return path

def event(percent, minutes=10080, stamp='2026-10-02T13:00:00Z', lid='codex'):
    return {'timestamp': stamp, 'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': {
        'limit_id': lid, 'primary': {'used_percent': percent, 'window_minutes': minutes, 'resets_at': 1791547735},
        'secondary': None}}}

r = limits.Reader()
assert r.snapshot() == {}, 'missing data is unknown'
older = write('old', [event(99, stamp='2026-10-02T12:00:00Z')])
newer = write('new', [event(6)])
other = write('other', [event(42, 300, lid='model-specific')])
# File activity must not override the actual observation timestamp.
os.utime(older, (time.time()+1000, time.time()+1000))
with newer.open('ab') as f:
    f.write(b'{"rate_limits": malformed}\n')
    f.write(json.dumps(event(80, stamp='2026-10-02T14:00:00Z')).encode())
rollouts.INDEX.checked = r.checked = None
data = r.snapshot()
assert data['codex']['info']['primary']['used_percent'] == 6
assert data['codex']['seen_at'] == rollouts.epoch('2026-10-02T13:00:00Z')
assert limits.windows(data['codex']['info']) == [{'label':'7d','used_percent':6,'resets_at':1791547735}]
assert limits.windows(data['model-specific']['info'])[0]['label'] == '5h'
assert len(data) == 2, 'separate buckets must not overwrite each other'
with newer.open('ab') as f: f.write(b'\n')
assert r.snapshot()['codex']['info']['primary']['used_percent'] == 6, 'poll cache'
r.checked = None
assert r.snapshot()['codex']['info']['primary']['used_percent'] == 80, 'completed write refreshed'

for invalid in (None, 'bad', {}, {'primary': []}, {'primary': {'used_percent': None}},
                {'primary': {'used_percent': True}}, {'primary': {'used_percent': float('nan')}},
                {'primary': {'used_percent': float('inf')}}, {'primary': {'used_percent': 10**1000}}):
    assert limits.windows(invalid) == [], invalid
assert limits.windows({'primary': {'used_percent': 0}})[0]['label'] == 'primary', 'unknown period not invented'
assert limits.windows({'primary': {'used_percent': 0, 'window_minutes': 30}})[0]['label'] == '30m'
assert limits.windows({'primary': {'used_percent': 12.5, 'window_minutes': 300},
                       'secondary': {'used_percent': 50, 'window_minutes': 10080}})[1]['label'] == '7d'
# A large rollout's tail is bounded; skip an incomplete leading record.
big = write('large', [])
with big.open('ab') as f:
    f.write(json.dumps({'type':'response_item','payload':{'text':'x'*(limits.TAIL_BYTES+1)}}).encode()+b'\n')
    f.write(json.dumps(event(7, stamp='2026-10-02T15:00:00Z')).encode()+b'\n')
rollouts.INDEX.checked = r.checked = None
assert r.snapshot()['codex']['info']['primary']['used_percent'] == 7

before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in folder.iterdir()}
snap = json.loads(subprocess.run([str(b/'agent-top'), '--json', '--stage', 'unrelated-stage'],
                                capture_output=True, text=True, check=True).stdout)
assert snap['codex_limits']['codex']['info']['primary']['used_percent'] == 7, 'account limits independent of stages'
view = subprocess.run([str(b/'agent-top'), '--once', '--width', '200', '--stage', 'unrelated-stage'],
                      capture_output=True, text=True, check=True).stdout
assert 'Codex 7d 7%' in view and 'Codex model-specific 5h 42%' in view, view
assert 'latest logged snapshot' in view and 'observed' in view and 'resets' in view
for p, fingerprint in before.items():
    assert (p.stat().st_mtime_ns, p.read_bytes()) == fingerprint, 'monitor changed rollout'
for p in folder.iterdir(): p.unlink()
rollouts.INDEX.checked = r.checked = None
assert r.snapshot() == {}, 'deleted source returns unknown'
empty = subprocess.run([str(b/'agent-top'),'--once','--stage','unrelated-stage'], capture_output=True,text=True,check=True).stdout
assert 'Codex 7d' not in empty, 'no invented zero usage'
print('PASS Codex account limits: windows, timestamps, buckets, torn writes, cache, bounds, missing and read-only')
PY
check $? 0 'Codex account limits integration controls'
exit $fail
