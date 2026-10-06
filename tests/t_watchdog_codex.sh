#!/bin/bash
# Codex watchdog controls: real proxy grammar, safe queue, and forbidden native resume.
. "$(dirname "$0")/lib.sh"
new_home
C=$(mktemp -d)
export CODEX_HOME="$C/codex" CODEX_BIN="$C/codex.py" WATCHDOG_FIXTURE="$C" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$CODEX_HOME/sessions" "$AGENT_HUB_HOME/stage-a/agents"
cat > "$CODEX_BIN" <<'PY'
#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
root=Path(os.environ['WATCHDOG_FIXTURE']);args=sys.argv[1:]
if args==['app-server','proxy']:
 mode=(root/'mode').read_text().strip()
 if mode=='fail':sys.exit(1)
 first=json.loads(sys.stdin.readline());assert first['method']=='initialize'
 print(json.dumps({'id':first['id'],'result':{}}),flush=True)
 if mode=='hang':time.sleep(30);sys.exit(0)
 assert json.loads(sys.stdin.readline())['method']=='initialized'
 req=json.loads(sys.stdin.readline());assert req['method']=='thread/read'
 assert req['params']['includeTurns'] is False
 sid=req['params']['threadId']
 if mode=='malformed':print('not json',flush=True)
 elif mode=='error':print(json.dumps({'id':req['id'],'error':{'code':-1,'message':'fixture'}}),flush=True)
 else:
  status={'type': []} if mode=='badtype' else {'type':mode}
  print(json.dumps({'id':req['id'],'result':{'thread':{'id':sid if mode!='wrongid' else 'other','status':status}}}),flush=True)
 sys.stdin.read();sys.exit(0)
with (root/'mutations.jsonl').open('a') as f:f.write(json.dumps(args)+'\n')
if args[:1]==['queue']:
 assert len(args)==5 and args[1]=='--thread' and args[3]=='--message',args
 if (root/'queue-mode').read_text().strip()=='error':
  print('queue failed on fixture',file=sys.stderr);sys.exit(7)
 if (root/'queue-mode').read_text().strip()=='nonutf8':
  sys.stdout.buffer.write(b'Queued message \xff\n');sys.stdout.buffer.flush()
  sys.stderr.buffer.write(b'diagnostic \xfe\n');sys.stderr.buffer.flush();sys.exit(0)
 print('Queued message for thread '+args[2]);sys.exit(0)
if args[:2]==['exec','resume']:
 sys.exit('native resume forbidden by the watchdog contract')
sys.exit('unexpected mutation')
PY
chmod +x "$CODEX_BIN"
printf idle > "$C/mode"; printf ok > "$C/queue-mode"
python3 - "$B" "$C" <<'PY'
import hashlib, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import codex_rollouts as cr
import codex_sessions as cs
import hubcore as hc
import watchdog_codex as wc
root=Path(sys.argv[2]);home=Path(os.environ['AGENT_HUB_HOME']);codex=Path(os.environ['CODEX_HOME'])
sid='aaaaaaaa-1111-4111-8111-111111111111';other='bbbbbbbb-2222-4222-8222-222222222222'
rec={'engine':'codex','kind':'cli','host':'codex-app','session':sid,'tag':'hub-2','cwd':str(root)}
now=datetime(2026,10,7,0,0,tzinfo=timezone.utc);stamp=now.timestamp()-3600
p=codex/'sessions'/'rollout-fixture.jsonl'
p.write_text(json.dumps({'type':'session_meta','payload':{'id':sid,'source':'vscode'},'timestamp':now.isoformat()})+'\n')
os.utime(p,(stamp,stamp))
def mode(value): (root/'mode').write_text(value)
def calls():
 p=root/'mutations.jsonl';return [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []
def snapshot():
 return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for base in (home,codex) for p in base.rglob('*') if p.is_file()}
expected={'busy','last_activity','dead_turn','transport','why'}
mode('idle');got=wc.state('stage-a',rec,now)
assert set(got)==expected and got['busy'] is False and got['transport']=='codex-queue',got
assert got['last_activity']==datetime.fromtimestamp(stamp,timezone.utc)
assert got['dead_turn'] is None
assert calls()==[]
print('PASS idle confirmed app state and indexed rollout mtime, read-only')
# Dry run reads the proxy but never queues, writes a home file, or leaks full IDs in its plan.
before=snapshot();result=wc.wake('stage-a',rec,'stage-a: 2 lines wait',True)
assert set(result)=={'ok','how','detail'} and result['ok'],result
assert 'queue --thread aaaaaaaa --message' in result['how'] and sid not in result['how']
assert snapshot()==before and calls()==[]
print('PASS dry run plans same-thread queue with short ID and no writes')
text='stage-a: quoted "text"; $(touch SHOULD_NOT_EXIST)\nsecond line'
result=wc.wake('stage-a',rec,text,False)
assert result['ok'],result
assert calls()==[['queue','--thread',sid,'--message',text]],calls()
assert sid not in result['detail'] and not (root/'SHOULD_NOT_EXIST').exists()
print('PASS live fake queue uses exact registry UUID and one literal message argument')
# Re-read liveness on wake: no queue after an idle observation becomes active/unknown.
for value,busy in [('active',True),('notLoaded',None),('systemError',None),('error',None),('fail',None),('malformed',None),('wrongid',None),('badtype',None),('futureStatus',None)]:
 mode(value);before_calls=calls();got=wc.state('stage-a',rec,now)
 assert got['busy'] is busy and got['transport']=='notify' and got['dead_turn'] is None,(value,got)
 result=wc.wake('stage-a',rec,'must not wake',False)
 assert not result['ok'] and result['how']=='notify' and calls()==before_calls,(value,result,calls())
print('PASS active, notLoaded, errors and malformed/unknown statuses never wake or resume')
# A silent proxy must respect the read deadline; missing CLI is unknown too.
mode('hang');before_calls=calls();started=time.monotonic()
got=wc.state('stage-a',rec,now)
elapsed=time.monotonic()-started
assert got['busy'] is None and got['transport']=='notify' and elapsed<7,(got,elapsed)
assert calls()==before_calls
print('PASS hanging proxy returns unknown within 7 seconds without a mutation')
with patch.dict(os.environ,{'CODEX_BIN':'/nonexistent'}):
 got=wc.state('stage-a',rec,now)
 assert got['busy'] is None and got['transport']=='notify',got
 result=wc.wake('stage-a',rec,'must not wake without CLI',False)
 assert not result['ok'] and result['how']=='notify' and calls()==before_calls,result
print('PASS missing Codex binary returns unknown and notify wake without a mutation')
mode('idle')
for changes in ({'host':'codex-cli'},{'host':None},{'kind':'desktop'},{'session':'local_scratch','cli_session_id':sid}):
 before_calls=calls();got=wc.state('stage-a',{**rec,**changes},now)
 assert got['transport']=='notify' and got['busy'] is False,(changes,got)
 assert not wc.wake('stage-a',{**rec,**changes},'no',False)['ok'] and calls()==before_calls
print('PASS terminal, Desktop and legacy unknown hosts remain notify-only, even with vscode provenance')
for bad in ('','--last','an exact thread name','../other',None):
 before_calls=calls();got=wc.state('stage-a',{**rec,'session':bad},now)
 assert got['busy'] is None and got['transport']=='notify'
 assert not wc.wake('stage-a',{**rec,'session':bad},'no',False)['ok'] and calls()==before_calls
print('PASS missing or non-UUID identity never selects a name, --last or successor')
# CLI id is the actual writer identity, with no fallback to a different registry id.
cr.INDEX.checked=None
q=codex/'sessions'/'rollout-newer.jsonl'
q.write_text(json.dumps({'type':'session_meta','payload':{'id':other,'source':'vscode'}})+'\n')
os.utime(q,(stamp+20,stamp+20))
result=wc.wake('stage-a',{**rec,'cli_session_id':other},'same CLI id',False)
assert result['ok'] and calls()[-1][2]==other
assert wc.state('stage-a',{**rec,'cli_session_id':'invalid'},now)['busy'] is None
print('PASS CLI session id takes precedence and invalid CLI id never falls back')
# A new rollout is not a global lock, and error/aborted-looking records cannot trigger R4.
for ending in ({'type':'turn_aborted','reason':'interrupted'}, {'type':'error','message':'API failed'}, {'type':'task_complete'}):
 with p.open('a') as f:f.write(json.dumps({'type':'event_msg','payload':ending})+'\n')
 cr.INDEX.checked=None
 assert wc.state('stage-a',rec,now)['dead_turn'] is None
print('PASS interrupted and API-error-looking rollout records never infer a Codex dead turn')
missing={**rec,'session':'cccccccc-3333-4333-8333-333333333333'}
assert wc.state('stage-a',missing,now)['last_activity'] is None
assert wc.state('stage-a',missing,now)['transport']=='notify'
assert not wc.wake('stage-a',missing,'no',False)['ok']
meta=home/'stage-a/agents/old-hub/meta.json'
meta.parent.mkdir();meta.write_text(json.dumps({'engine':'codex','role':'old-hub','session_id':sid}))
assert wc.state('stage-a',rec,now)['transport']=='notify'
meta.unlink()
print('PASS no rollout and detached identity defer to notify or core agent-send')
(root/'queue-mode').write_text('nonutf8');before_calls=len(calls())
result=wc.wake('stage-a',rec,'non-UTF-8 output',False)
assert result['ok'] and result['detail']=='Queued message \ufffd',result
assert len(calls())==before_calls+1
print('PASS delivered queue remains successful with non-UTF-8 stdout and stderr')
(root/'queue-mode').write_text('error');before_calls=len(calls())
result=wc.wake('stage-a',rec,'failure',False)
assert not result['ok'] and result['detail']=='queue failed on fixture',result
assert len(calls())==before_calls+1
with patch.object(wc.subprocess,'run',side_effect=subprocess.TimeoutExpired('queue',20)):
 # Mock the read-only liveness query separately from the queue's process harness.
 with patch.object(wc.codex_sessions,'runtime_status',return_value='idle'):
  result=wc.wake('stage-a',rec,'timeout',False)
  assert not result['ok'] and result['detail']=='queue outcome unknown: TimeoutExpired',result
assert all(a[:1]==['queue'] for a in calls())
assert not any(a[:2]==['exec','resume'] for a in calls())
print('PASS failed queue and unknown timeout outcome have no exec resume, new thread or fallback')
# Evidence that the native resume fixture would detect an accidentally added fallback.
r=subprocess.run([str(root/'codex.py'),'exec','resume',sid,'-'],input='control',capture_output=True,text=True)
assert r.returncode!=0 and 'forbidden' in r.stderr
assert calls()[-1][:2]==['exec','resume']
print('PASS negative-control fixture detects forbidden native exec resume')
PY
check $? 0 'watchdog Codex interface, fake queue and proxy controls'
exit $fail
