#!/bin/bash
# agent-top reports what the logs say: a resumed Claude session's cost is its last cumulative total, a resumed Codex
# thread's tokens are its last cumulative count, a hub's journal age comes from its newest line even when the tag also
# wrote yesterday, and the hub's share of the stage's spend is in --json and --once.
. "$(dirname "$0")/lib.sh"
new_home
export PYTHONDONTWRITEBYTECODE=1 CLAUDE_CONFIG_DIR=$AGENT_HUB_HOME/claude AGENT_TOP_CACHE=0
python3 - "$B" "$AGENT_HUB_HOME" <<'PY'
import datetime as dt
import importlib.machinery
import importlib.util
import json
import os
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
    if sid is None:
        del ev['session_id']
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

# A result that names no session belongs to the session of the latest init: two sessions, two counters.
agent('nosid', 'claude', SID_F1, [init(SID_F1), result(None, 1.0), init(SID_F2), result(None, 0.5)])
agent('nosid2', 'claude', SID_F1, [init(SID_F1), result(None, 1.0), init(SID_F1), result(None, 1.5)])

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

# A count read before any init (a log scanned from its tail) is of an unknown thread: it stays its own bucket, is in the
# total and marks it partial, whichever thread follows (the same one or another).
agent('cdx3', 'codex', THREAD, [completed(1000, 800, 10), {'type': 'thread.started', 'thread_id': THREAD}, completed(2500, 2000, 25)])
agent('cdx4', 'codex', THREAD2, [completed(1000, 800, 10), {'type': 'thread.started', 'thread_id': THREAD2}, completed(400, 300, 4)])

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
assert agents['cdx3']['usage_tokens']['input_tokens'] == 3500 and agents['cdx3']['usage_scope'] == 'partial', agents['cdx3']['usage_tokens']
assert agents['cdx4']['usage_tokens']['input_tokens'] == 1400 and agents['cdx4']['usage_scope'] == 'partial', agents['cdx4']['usage_tokens']
assert 'input usage ≈4k' in subprocess.run([str(binpath / 'agent-top'), '--once', '--all', '--stage', 'stage-a', '--agent', 'cdx3', '--width', '160'],
                                            capture_output=True, text=True, check=True).stdout
assert agents['nosid']['cost_usd'] == 1.5, agents['nosid']['cost_usd']       # the shared '' key said 0.5
assert agents['nosid2']['cost_usd'] == 1.5, agents['nosid2']['cost_usd']

roles = {r['role']: r for r in snap['roles']['stage-a']}
age = roles['hub']['journal_age_s']
assert age is not None and age < 1800, f'hub journal age {age}s is not from today\'s line'  # the old code said ~a day

# hub: m1 400k + 20k*5 = 500k weighted, m2 100k, the unpriced model is left out (and flagged) -> 600k * 5e-6 = $3.00
spend = snap['spend']['stage-a']
assert spend['agents_usd'] == 12.0, spend                                  # 2.5 + 1.5 + 5.0 + 1.5 + 1.5
assert spend['hub_usd'] == 3.0 and spend['hub_basis'] == 'estimate' and spend['hub_partial'] is True, spend
assert spend['hub_share'] == 0.2, spend                                    # 3 / (3 + 12)
once = subprocess.run([str(binpath / 'agent-top'), '--once', '--all', '--stage', 'stage-a', '--width', '160'],
                      capture_output=True, text=True, check=True).stdout
assert 'spend: hub ≈$3.00 + agents $12.00 — the hub is ≈20 % of the stage' in once, once

# A hub's archived predecessor (a headless folder of the same role) is an agent like the others: its dollars are the
# stage's, it is not the hub, and --all does not let it replace the current hub's estimate.
old_hub = 'a0a0a0a0-1111-4111-8111-111111111111'
agent('hub.20261001-120000', 'claude', old_hub, [init(old_hub), result(old_hub, 4.0)])
spend = json.loads(subprocess.run([str(binpath / 'agent-top'), '--json', '--all', '--stage', 'stage-a'],
                                  capture_output=True, text=True, check=True).stdout)['spend']['stage-a']
assert spend['hub_usd'] == 3.0 and spend['hub_basis'] == 'estimate' and spend['agents_usd'] == 16.0, spend

# A headless hub logs exact dollars: they are the hub's, matched by the registered hub session, not an estimate, and
# not the agents'.
hub_sid = 'abababab-1111-4111-8111-111111111111'
agent('hub', 'claude', hub_sid, [init(hub_sid), result(hub_sid, 3.5)])
roles_file = stage / 'roles.json'
roles_data = json.loads(roles_file.read_text())
roles_data['roles']['hub']['cli_session_id'] = hub_sid
roles_file.write_text(json.dumps(roles_data))
spend = json.loads(subprocess.run([str(binpath / 'agent-top'), '--json', '--all', '--stage', 'stage-a'],
                                  capture_output=True, text=True, check=True).stdout)['spend']['stage-a']
assert spend['hub_usd'] == 3.5 and spend['hub_basis'] == 'logged' and spend['agents_usd'] == 16.0, spend
roles_data['roles']['hub']['cli_session_id'] = HUB_SID
roles_file.write_text(json.dumps(roles_data))

# No transcript and no log: the hub's cost is unknown, never a made-up number.
(root / 'claude' / 'projects' / 'proj' / f'{HUB_SID}.jsonl').unlink()
(stage / 'agents' / 'hub' / 'meta.json').unlink()
spend = json.loads(subprocess.run([str(binpath / 'agent-top'), '--json', '--all', '--stage', 'stage-a'],
                                  capture_output=True, text=True, check=True).stdout)['spend']['stage-a']
assert spend['hub_usd'] is None and spend['hub_share'] is None, spend
# What the list hides by age is spend all the same: the hub's share does not change with the filter. Stage b: a recent
# agent that also tells the price (1.5 $ for 300k weighted tokens: a price with cents), one finished two days ago
# (2.5 $), and a hub whose transcript is 200k weighted tokens (1.0 $): 1 / (1 + 4) with the old agent counted, 1 / (1 + 1.5) without.
stage_b, HUB_B = root / 'stage-b', '88888888-1111-4111-8111-111111111111'
for role, sid, cost, usage in (('recent', 'b1b1b1b1-1111-4111-8111-111111111111', 1.5, {
        'inputTokens': 300_000, 'outputTokens': 0, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0, 'costUSD': 1.5}),
        ('old', 'b2b2b2b2-1111-4111-8111-111111111111', 2.5, None)):
    folder = stage_b / 'agents' / role
    write(folder / 'log.jsonl', [init(sid), result(sid, cost, usage)])
    (folder / 'meta.json').write_text(json.dumps({'role': role, 'engine': 'claude', 'session_id': sid, 'model': 'x',
                                                 'cwd': str(root), 'pid': 99999999, 'runs': [{}]}))
two_days = dt.datetime.now().timestamp() - 2 * 86400
os.utime(stage_b / 'agents' / 'old' / 'log.jsonl', (two_days, two_days))
(stage_b / 'roles.json').write_text(json.dumps({'version': 1, 'roles': {
    'hub': {'kind': 'desktop', 'tag': 'hub-b', 'cli_session_id': HUB_B, 'engine': 'claude'}}}))
write(root / 'claude' / 'projects' / 'proj' / f'{HUB_B}.jsonl', [line('b1', 200_000, 0)])
by_filter = {}
for flag in ([], ['--all']):
    out = json.loads(subprocess.run([str(binpath / 'agent-top'), '--json', '--stage', 'stage-b', *flag],
                                    capture_output=True, text=True, check=True).stdout)
    by_filter[bool(flag)] = (out['spend']['stage-b'], sorted(a['role'] for a in out['agents']))
assert by_filter[False][1] == ['recent'] and by_filter[True][1] == ['old', 'recent'], by_filter   # the filter did hide it
assert by_filter[False][0] == by_filter[True][0], by_filter
assert by_filter[True][0]['agents_usd'] == 4.0 and by_filter[True][0]['hub_usd'] == 1.0 and by_filter[True][0]['hub_share'] == 0.2

# A transcript line is read whole up to LINE_MAX, whatever the order of its fields: the same record, short and with 300 KB
# of content before or after its usage, gives the same totals. A line over the cap is skipped and the transcript is
# marked incomplete; an unterminated line is never passed: the offset stays before it and the transcript is incomplete.
sys.path.insert(0, str(binpath))
loader = importlib.machinery.SourceFileLoader('agent_top', str(binpath / 'agent-top'))
top = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(top)
use = {'input_tokens': 5, 'output_tokens': 7, 'cache_read_input_tokens': 11, 'cache_creation_input_tokens': 13}
want = {'input_tokens': 5, 'output_tokens': 7, 'cache_read_input_tokens': 11, 'cache_creation_input_tokens': 13}
for name, content in (('short', 'x'), ('long', 'z' * 300_000 + ' "usage": {"input_tokens": 999999999}')):
    for order in (('id', 'model', 'usage', 'content'), ('id', 'model', 'content', 'usage')):
        parts = {'id': 'msg_a', 'model': OPUS, 'usage': use, 'content': [{'type': 'text', 'text': content}]}
        record = {'type': 'assistant', 'message': {k: parts[k] for k in order}}
        tpath = root / f'order-{name}-{"-".join(order)}.jsonl'
        tpath.write_text(json.dumps(record) + '\n')
        tr = top.Transcript(tpath)
        tr.update(10**9)
        assert tr.complete and tr.totals() == {OPUS: want}, (name, order, tr.totals())

top.LINE_MAX = 4096
tpath = root / 'cap.jsonl'
tpath.write_text(json.dumps(line('s1', 1, 0)) + '\n' + json.dumps({'type': 'assistant', 'message': {
    'id': 'msg_big', 'model': OPUS, 'usage': use, 'content': [{'type': 'text', 'text': 'z' * 50_000}]}}) + '\n'
    + json.dumps(line('s2', 100, 0)) + '\n')
tr = top.Transcript(tpath)
tr.update(10**9)
assert tr.skipped == 1 and not tr.complete, (tr.skipped, tr.complete)                 # the offset is at the end: the skip is what says it
assert tr.offset == tr.size and tr.totals()[OPUS]['input_tokens'] == 101, tr.totals()   # the lines around it still count
tail = root / 'torn.jsonl'
whole = json.dumps(line('t1', 1, 0)) + '\n'
tail.write_text(whole + json.dumps(line('t2', 100, 0))[:-5])                              # the last line is still being written
tr = top.Transcript(tail)
tr.update(10**9)
assert tr.offset == len(whole) and not tr.complete and tr.totals()[OPUS]['input_tokens'] == 1, (tr.offset, tr.totals())
tail.write_text(whole + json.dumps(line('t2', 100, 0)) + '\n')
tr.update(10**9)
assert tr.complete and tr.totals()[OPUS]['input_tokens'] == 101
# an unterminated line over the cap is not passed either, and a long one in progress is not "read"
huge = root / 'huge.jsonl'
huge.write_text(whole + 'y' * 20_000)
tr = top.Transcript(huge)
tr.update(10**9)
assert tr.offset == len(whole) and not tr.complete and tr.skipped == 0, (tr.offset, tr.skipped)
# a small budget stops between lines, and the rest is read by the next calls
tr = top.Transcript(tpath)
tr.update(1)
assert 0 < tr.offset < tr.size and not tr.complete
tr.update(10**9)
assert tr.offset == tr.size
print('PASS honest agent-top: resumed Claude cost, resumed Codex tokens, two-day journal age, the hub\'s spend share')
PY
check $? 0 "honest agent-top fixtures"
exit $fail
