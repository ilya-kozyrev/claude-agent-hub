#!/bin/bash
# agent-top reports what the logs say: a resumed Claude session's cost is its last cumulative total, a resumed Codex
# thread's tokens are its last cumulative count, a hub's journal age comes from its newest line even when the tag also
# wrote yesterday, and the hub's share of the stage's spend is in --json and --once.
. "$(dirname "$0")/lib.sh"
new_home
export PYTHONDONTWRITEBYTECODE=1 CLAUDE_CONFIG_DIR=$AGENT_HUB_HOME/claude AGENT_TOP_CACHE=0
python3 - "$B" "$AGENT_HUB_HOME" <<'PY'
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

binpath, root = Path(sys.argv[1]), Path(sys.argv[2])
stage = root / 'stage-a'
SID_RES = 'aaaaaaaa-1111-4111-8111-111111111111'
SID_F1, SID_F2 = 'bbbbbbbb-1111-4111-8111-111111111111', 'cccccccc-1111-4111-8111-111111111111'
SID_PRICED = 'dddddddd-1111-4111-8111-111111111111'
THREAD, THREAD2 = 'eeeeeeee-1111-4111-8111-111111111111', 'ffffffff-1111-4111-8111-111111111111'
HUB_SID = '99999999-1111-4111-8111-111111111111'
OPUS = 'claude-opus-5-5'


def write(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(e) + '\n' for e in events))


def agent(role, engine, sid, events):
    folder = stage / 'agents' / role
    write(folder / 'log.jsonl', events)
    folder.joinpath('meta.json').write_text(json.dumps({
        'role': role, 'engine': engine, 'session_id': sid, 'model': 'x', 'cwd': str(root), 'pid': 99999999,
        'effort': 'high', 'runs': [{}]}))


def init(sid):
    return {'type': 'system', 'subtype': 'init', 'session_id': sid, 'model': OPUS}


def result(sid, cost, usage=None):
    ev = {'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': sid, 'total_cost_usd': cost,
          'num_turns': 1, 'result': 'DONE'}
    if usage:
        ev['modelUsage'] = {OPUS: usage}
    return ev


# 1. A Claude agent resumed twice (the second time woken by itself, zero turns): one session, a cumulative counter.
agent('res', 'claude', SID_RES, [init(SID_RES), result(SID_RES, 2.0), init(SID_RES), result(SID_RES, 2.0),
                                 init(SID_RES), result(SID_RES, 2.5)])
# A second session id in one log starts its own counter: its last total adds to the first session's.
agent('forked', 'claude', SID_F1, [init(SID_F1), result(SID_F1, 1.0), init(SID_F2), result(SID_F2, 0.5)])
# One agent whose result also reports the dollars per model: the price of a weighted token is 5e-6 here.
agent('priced', 'claude', SID_PRICED, [init(SID_PRICED), result(SID_PRICED, 5.0, {
    'inputTokens': 1_000_000, 'outputTokens': 0, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0, 'costUSD': 5.0})])

# 2. A Codex thread resumed: every turn.completed carries the thread's cumulative count; a second thread has its own.
def completed(i, c, o):
    return {'type': 'turn.completed', 'usage': {'input_tokens': i, 'cached_input_tokens': c, 'output_tokens': o}}

agent('cdx', 'codex', THREAD, [
    {'type': 'thread.started', 'thread_id': THREAD}, {'type': 'turn.started'}, completed(1000, 800, 10),
    {'type': 'thread.started', 'thread_id': THREAD}, {'type': 'turn.started'}, completed(2500, 2000, 25)])
agent('cdx2', 'codex', THREAD, [
    {'type': 'thread.started', 'thread_id': THREAD}, completed(1000, 800, 10),
    {'type': 'thread.started', 'thread_id': THREAD}, completed(2500, 2000, 25),
    {'type': 'thread.started', 'thread_id': THREAD2}, completed(400, 300, 4)])

# 3. The hub wrote yesterday and today (the tag is the same): its age is today's line, not yesterday's last one.
now = dt.datetime.now(dt.timezone.utc)
today_line = max(now - dt.timedelta(minutes=2), now.replace(hour=0, minute=0, second=0, microsecond=0))
work = stage / 'coordinator' / 'work'
work.mkdir(parents=True)
(work / f"journal-{(now - dt.timedelta(days=1)).date()}.md").write_text(
    '- 00:01 [hub-1] early line of yesterday\n- 23:59 [hub-1] last line of yesterday\n- 23:59 [other] unrelated\n')
(work / f"journal-{now.date()}.md").write_text(f"- {today_line:%H:%M} [hub-1] today's line\n")
(stage / 'roles.json').write_text(json.dumps({'version': 1, 'roles': {
    'hub': {'kind': 'desktop', 'tag': 'hub-1', 'cli_session_id': HUB_SID, 'engine': 'claude'},
    'res': {'kind': 'headless', 'tag': 'res'}}}))

# 4. The hub's transcript: the last usage of each message (written once per content block) priced like the agents'.
def line(mid, inp, out, cache_read=0, model=OPUS):
    return {'type': 'assistant', 'message': {'id': mid, 'model': model, 'usage': {
        'input_tokens': inp, 'output_tokens': out, 'cache_read_input_tokens': cache_read, 'cache_creation_input_tokens': 0},
        'content': [{'type': 'text', 'text': 'x'}]}}

write(root / 'claude' / 'projects' / 'proj' / f'{HUB_SID}.jsonl', [
    line('m1', 400_000, 1), line('m1', 400_000, 20_000),                  # one message, two lines: the last counts
    {'type': 'user', 'message': {'content': 'x'}},
    line('m2', 100_000, 0), line('m3', 7_000_000, 0, model='some-unpriced-model')])

snap = json.loads(subprocess.run([str(binpath / 'agent-top'), '--json', '--all', '--stage', 'stage-a'],
                                 capture_output=True, text=True, check=True).stdout)
agents = {a['role']: a for a in snap['agents']}
assert agents['res']['cost_usd'] == 2.5, agents['res']['cost_usd']       # the old sum said 6.5
assert agents['forked']['cost_usd'] == 1.5, agents['forked']['cost_usd']
assert agents['priced']['cost_usd'] == 5.0
assert agents['cdx']['usage_tokens']['input_tokens'] == 2500, agents['cdx']['usage_tokens']   # the old sum said 3500
assert agents['cdx']['usage_tokens']['output_tokens'] == 25 and agents['cdx']['usage_scope'] == 'session'
assert agents['cdx2']['usage_tokens']['input_tokens'] == 2900 and agents['cdx2']['usage_scope'] == 'sessions'

roles = {r['role']: r for r in snap['roles']['stage-a']}
age = roles['hub']['journal_age_s']
assert age is not None and age < 1800, f'hub journal age {age}s is not from today\'s line'  # the old code said ~a day

# hub: m1 400k + 20k*5 = 500k weighted, m2 100k, the unpriced model is left out (and flagged) -> 600k * 5e-6 = $3.00
spend = snap['spend']['stage-a']
assert spend['agents_usd'] == 9.0, spend                                   # 2.5 + 1.5 + 5.0
assert spend['hub_usd'] == 3.0 and spend['hub_basis'] == 'estimate' and spend['hub_partial'] is True, spend
assert spend['hub_share'] == 0.25, spend                                   # 3 / (3 + 9)
once = subprocess.run([str(binpath / 'agent-top'), '--once', '--all', '--stage', 'stage-a', '--width', '160'],
                      capture_output=True, text=True, check=True).stdout
assert 'spend: hub ≈$3.00 + agents $9.00 — the hub is ≈25 % of the stage' in once, once

# A headless hub logs exact dollars: they are the hub's, not an estimate, and not the agents'.
agent('hub', 'claude', 'abababab-1111-4111-8111-111111111111', [init('abababab-1111-4111-8111-111111111111'),
                                                                 result('abababab-1111-4111-8111-111111111111', 3.0)])
spend = json.loads(subprocess.run([str(binpath / 'agent-top'), '--json', '--all', '--stage', 'stage-a'],
                                  capture_output=True, text=True, check=True).stdout)['spend']['stage-a']
assert spend['hub_usd'] == 3.0 and spend['hub_basis'] == 'logged' and spend['agents_usd'] == 9.0, spend

# No transcript and no log: the hub's cost is unknown, never a made-up number.
(root / 'claude' / 'projects' / 'proj' / f'{HUB_SID}.jsonl').unlink()
(stage / 'agents' / 'hub' / 'meta.json').unlink()
spend = json.loads(subprocess.run([str(binpath / 'agent-top'), '--json', '--all', '--stage', 'stage-a'],
                                  capture_output=True, text=True, check=True).stdout)['spend']['stage-a']
assert spend['hub_usd'] is None and spend['hub_share'] is None, spend
print('PASS honest agent-top: resumed Claude cost, resumed Codex tokens, two-day journal age, the hub\'s spend share')
PY
check $? 0 "honest agent-top fixtures"
exit $fail
