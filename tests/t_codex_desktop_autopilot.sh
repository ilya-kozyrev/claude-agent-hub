#!/usr/bin/env bash
# Desktop contracts at actual hub command seams; no native app calls or model requests.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK_TMP="$(mktemp -d)"
trap 'rm -rf "$TASK_TMP"' EXIT
python3 - "$ROOT" "$TASK_TMP" <<'PY'
import json, os, pathlib, shlex, subprocess, sys
root, tmp = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0, str(root/'bin'))
import autopilot as ap
import engines
old = '11111111-1111-4111-8111-111111111111'
real = '22222222-2222-4222-8222-222222222222'
client = 'client-new-thread:33333333-3333-4333-8333-333333333333'
other = '44444444-4444-4444-8444-444444444444'
env = {k:v for k,v in os.environ.items() if not k.startswith(('AGENT_HUB_','HUB_','CODEX_','CLAUDE_','AGENT_'))}
env.update(AGENT_HUB_TZ='UTC', AGENT_HUB_ENGINE='codex', CODEX_THREAD_ID=old,
           CODEX_INTERNAL_ORIGINATOR_OVERRIDE='Codex Desktop', CODEX_APP_TOOLS_PIPE_PATH='/never-connect',
           CODEX_BIN=str(tmp/'must-not-launch'), CLAUDE_BIN=str(tmp/'missing'), CODEX_HOME=str(tmp/'codex-home'))
repo=tmp/'repo'; repo.mkdir()
def git(*args): return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True)
git('init','-q','-b','main'); git('-c','user.email=t@t','-c','user.name=T','commit','--allow-empty','-qm','init')
actual=repo/'.worktrees/app'; git('worktree','add','-q','-b','app',str(actual))
link=tmp/'project-link'; link.symlink_to(repo, target_is_directory=True)
rollouts=tmp/'codex-home/sessions'; rollouts.mkdir(parents=True)
def rollout(sid, policy, model='gpt-6.1-sol', effort='high'):
    (rollouts/f'rollout-{sid}.jsonl').write_text(json.dumps({'type':'session_meta','payload':{'id':sid}})+'\n'+
        json.dumps({'type':'turn_context','payload':{'model':model,'effort':effort,'approval_policy':'never','sandbox_policy':policy}})+'\n')
rollout(old, {'type':'danger-full-access'})
def setup(name):
    home=tmp/name; stage=home/'stage-a'; stage.mkdir(parents=True)
    env['AGENT_HUB_HOME']=str(home); env['CODEX_THREAD_ID']=old
    (stage/'roles.json').write_text(json.dumps({'roles':{'hub':{'session':old,'cli_session_id':old,'tag':'hub-1','kind':'cli'}}}))
    handoff=stage/'HANDOFF-hub-test.md'
    handoff.write_text('# Handoff "Hub stage-a #1" → "Hub stage-a #2" — stage-a\n\n## 0. First steps\nTake over\n## 2. Queue\nWrite DONE and finish. No external work remains.\n')
    return home,stage,handoff

def hub(*args, cwd=repo, ok=True):
    r=subprocess.run([str(root/'bin/hub'),*map(str,args)],env=env,cwd=cwd,capture_output=True,text=True)
    if ok: assert r.returncode==0, (r.returncode,r.stdout,r.stderr)
    else: assert r.returncode!=0, r.stdout
    return r

def state(stage): return json.loads((stage/'auto-handoff.json').read_text())
def roles(stage): return json.loads((stage/'roles.json').read_text())['roles']['hub']
def prepare(handoff, *args): return hub('succeed','--stage','stage-a','--handoff',handoff,'--force',*args)
def request(req, path=link, pid='saved-project', ok=True):
    return hub('desktop-request','--stage','stage-a','--request',req,'--project-id',pid,'--project-path',path,ok=ok)
def bind(req, *args, ok=True): return hub('desktop-bind','--stage','stage-a','--request',req,*args,ok=ok)
def takeover(handoff, req, ok=True, **kwargs):
    return hub('takeover','--stage','stage-a','--session','self','--auto-handoff','--handoff',handoff,
               '--desktop-request',req,ok=ok,**kwargs)

home,stage,handoff=setup('desktop')
r=prepare(handoff)
p=state(stage)['pending']; req=p['request_id']
assert p['surface']=='desktop' and p['kind']=='desktop' and p['phase']=='prepared' and not p.get('id')
assert state(stage)['chain']==1 and not (stage/'agents').exists()
assert 'prepared' in r.stdout and 'Full Access' in r.stdout and 'list_projects' in r.stdout
assert roles(stage)['session']==old
# Execute the printed waiter, including its since format, against the actual journal seam.
waiter=next(line.strip() for line in r.stdout.splitlines() if line.strip().startswith(str(root/'bin/jwait')))
assert '--since '+p['at'][:16] in waiter
subprocess.run([str(root/'bin/jlog'),'--stage','stage-a','--tag','hub-2','start: waiter-control'],env=env,check=True,capture_output=True)
w=subprocess.run(shlex.split(waiter),env=env,cwd=repo,capture_output=True,text=True,timeout=5)
assert w.returncode==0 and 'start: waiter-control' in w.stdout,(w.returncode,w.stdout,w.stderr)
hub('desktop-status' ,'--stage','stage-a','--request',req,'--verified',ok=False)
print('PASS app markers prepare a desktop request without launching a CLI or changing hub identity')
prepare(handoff, '--again'); assert state(stage)['pending']['request_id']==req and state(stage)['chain']==1
hub('succeed','--stage','stage-a','--handoff',handoff,'--force',ok=False)
assert state(stage)['chain']==1
# Changing the named successor/handoff or surface cannot replace an unfinished desktop reservation.
alternate=stage/'HANDOFF-hub-alternate.md'
alternate.write_text('# Handoff "Hub stage-a #1" → "Hub stage-a #7" — stage-a\n')
saved=state(stage)
for extra in ([], ['--again'], ['--surface','cli']):
    hub('succeed','--stage','stage-a','--handoff',alternate,'--force',*extra,ok=False)
    assert state(stage)==saved and not (stage/'agents').exists()
request(req,path=tmp,ok=False); assert state(stage)['pending']['phase']=='prepared'
payload=json.loads(request(req).stdout)
args=payload['create_thread']
assert not payload['already_dispatched']
assert args['target']=={'type':'project','projectId':'saved-project','environment':{'type':'worktree'}}
assert args['model']=='gpt-6.1-sol' and args['thinking']=='high'
assert '--desktop-request '+req in args['prompt'] and 'finite' in args['prompt'] and '--for 9m' not in args['prompt']
assert 'sandbox' not in args and 'approval' not in args
assert json.loads(request(req).stdout)['already_dispatched']
assert state(stage)['chain']==1
print('PASS same normalized main project, default worktree branch, actual model/thinking fields and dispatch retry guard')
bind(req,'--client-thread-id',client,'--project-id','saved-project')
assert state(stage)['pending']['client_thread_id']==client and not state(stage)['pending'].get('id')
bind(req,'--thread-id',client,ok=False)
env['CODEX_THREAD_ID']=client; rollout(client,{'type':'danger-full-access'})
takeover(handoff,req,ok=False,cwd=actual); assert roles(stage)['session']==old
env['CODEX_THREAD_ID']=old
bind(req,'--thread-id',real,'--project-id','saved-project'); bind(req,'--thread-id',real)
bind(req,'--thread-id',other,ok=False); bind('stale-token','--thread-id',real,ok=False)
saved=state(stage)
hub('succeed','--stage','stage-a','--fallback','--force',ok=False)
assert state(stage)==saved
assert state(stage)['chain']==1 and not state(stage)['pending'].get('taken_over')
hub('desktop-fail','--stage','stage-a','--request',req,'--why','cannot claim failure','--no-thread-created',ok=False)
print('PASS client IDs never become sessions; bind is repeatable and rejects stale/conflicting identity')
env['CODEX_THREAD_ID']=real
hub('takeover','--stage','stage-a','--session','self','--auto-handoff','--handoff',handoff,'--desktop-request',req,'--n','9',ok=False,cwd=actual)
assert roles(stage)['session']==old
rollout(real,{'type':'workspace-write','writable_roots':[str(actual)],'network_access':False})
takeover(handoff,req,ok=False,cwd=actual)
assert roles(stage)['session']==old and not state(stage)['pending'].get('taken_over')
rollout(real,{'type':'danger-full-access'},model='observed-model',effort='medium')
takeover(handoff,req,cwd=actual); p=state(stage)['pending']
assert roles(stage)['session']==real and roles(stage)['surface']=='desktop'
assert p['id']==real and p['cwd']==str(actual.resolve()) and p['project_id']=='saved-project'
assert p['observed']['model']=='observed-model' and p['observed']['effort']=='medium'
assert p['requested']['model']=='gpt-6.1-sol' and p['requested']['sandbox_policy']['type']=='danger-full-access'
assert p['observed']['sandbox_policy']['type']=='danger-full-access' and p['taken_over'] and state(stage)['chain']==1
assert json.loads(hub('desktop-status','--stage','stage-a','--request',req,'--verified').stdout)['verified']
bind(req,'--thread-id',real); takeover(handoff,req,cwd=actual)
assert state(stage)['chain']==1
print('PASS restricted home access leaves predecessor active; actual takeover reconciles identity/cwd and records observed settings separately')

home,stage,handoff=setup('takeover-first'); prepare(handoff); req=state(stage)['pending']['request_id']; request(req)
env['CODEX_THREAD_ID']=real; takeover(handoff,req,cwd=actual)
env['CODEX_THREAD_ID']=old; bind(req,'--thread-id',real)
assert state(stage)['pending']['taken_over'] and state(stage)['chain']==1
(stage/'roles.json').write_text(json.dumps({'roles':{'hub':{'session':other,'cli_session_id':other,'tag':'hub-9','kind':'cli'}}}))
bind(req,'--thread-id',real,ok=False); env['CODEX_THREAD_ID']=real; takeover(handoff,req,ok=False,cwd=actual)
assert roles(stage)['session']==other
print('PASS takeover-before-bind race, late confirmation and repeats preserve chain; later hubs cannot be overwritten')

# Parallel prepares reserve one request. Parallel late bind and takeover converge on the same actual UUID.
home,stage,handoff=setup('parallel')
cmd=[str(root/'bin/hub'),'succeed','--stage','stage-a','--handoff',str(handoff),'--force']
procs=[subprocess.Popen(cmd,env=env,cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
for proc in procs: proc.communicate(timeout=10)
assert sorted(p.returncode for p in procs)==[0,1] and state(stage)['chain']==1
req=state(stage)['pending']['request_id']; request(req)
successor_env=dict(env,CODEX_THREAD_ID=real)
commands=[([str(root/'bin/hub'),'desktop-bind','--stage','stage-a','--request',req,'--thread-id',real],env,repo),
          ([str(root/'bin/hub'),'takeover','--stage','stage-a','--session','self','--auto-handoff','--handoff',str(handoff),'--desktop-request',req],successor_env,actual)]
procs=[subprocess.Popen(cmd,env=e,cwd=c,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for cmd,e,c in commands]
for proc in procs:
    out,err=proc.communicate(timeout=10)
    assert proc.returncode==0,(out,err)
assert state(stage)['chain']==1 and state(stage)['pending']['taken_over'] and roles(stage)['session']==real
print('PASS concurrent prepares and bind/takeover reserve/migrate once under the state lock')

home,stage,handoff=setup('observed-restricted'); prepare(handoff); req=state(stage)['pending']['request_id']; request(req)
env['CODEX_THREAD_ID']=real
rollout(real,{'type':'workspace-write','writable_roots':[str(home)],'network_access':False})
takeover(handoff,req,cwd=actual)
p=state(stage)['pending']
assert p['requested']['sandbox_policy']['type']=='danger-full-access'
assert p['observed']['sandbox_policy']['type']=='workspace-write'
assert json.loads(hub('desktop-status','--stage','stage-a','--request',req,'--verified').stdout)['verified']
rollout(real,{'type':'danger-full-access'},model='observed-model',effort='medium')
print('PASS explicit writable stage root permits actual workspace policy without claiming requested Full Access')

home,stage,handoff=setup('retry'); prepare(handoff); req=state(stage)['pending']['request_id']; request(req)
hub('desktop-fail','--stage','stage-a','--request',req,'--why','unknown result')
prepare(handoff,'--again'); assert state(stage)['pending']['phase']=='uncertain'
assert json.loads(request(req).stdout)['already_dispatched']
hub('desktop-fail','--stage','stage-a','--request',req,'--why','create API rejected before creating','--no-thread-created')
prepare(handoff,'--again'); assert state(stage)['pending']['phase']=='prepared'
assert state(stage)['pending']['request_id']==req and state(stage)['chain']==1
assert not json.loads(request(req).stdout)['already_dispatched']
print('PASS uncertain launch never duplicates; confirmed no-create failure retries same reservation and chain')

home,stage,handoff=setup('branch'); prepare(handoff,'--surface','desktop','--branch','main')
req=state(stage)['pending']['request_id']
assert json.loads(request(req).stdout)['create_thread']['target']['environment']['startingState']=={'type':'branch','branchName':'main'}
home,stage,handoff=setup('missing-branch'); hub('succeed','--stage','stage-a','--handoff',handoff,'--force','--surface','desktop','--branch','missing',ok=False)
assert not (stage/'auto-handoff.json').exists()
home,stage,handoff=setup('dry'); prepare(handoff,'--dry-run')
assert not (stage/'auto-handoff.json').exists() and not (stage/'coordinator/work/hub-2-takeover-brief.md').exists()
hub('succeed','--stage','stage-a','--handoff',handoff,'--force','--surface','desktop','--headless',ok=False)
hub('succeed','--stage','stage-a','--handoff',handoff,'--force','--engine','claude','--surface','desktop',ok=False)
print('PASS explicit existing branch validated; missing branch and dry run create no reservation')

# Detection and child-env controls exercise both direct worker spawn and autopilot stripping.
saved=dict(os.environ); os.environ.clear(); os.environ.update(env)
assert engines.codex_desktop()
os.environ['AGENT_ROLE']='worker'; assert not engines.codex_desktop(); os.environ.pop('AGENT_ROLE')
os.environ.pop('CODEX_APP_TOOLS_PIPE_PATH'); os.environ.pop('CODEX_INTERNAL_ORIGINATOR_OVERRIDE')
assert not engines.codex_desktop()  # CODEX_THREAD_ID alone is a real console control.
os.environ.update(CODEX_INTERNAL_ORIGINATOR_OVERRIDE='Codex Desktop',CODEX_APP_TOOLS_PIPE_PATH='/never-connect')
assert not any(k in ap.child_env() for k in engines.CODEX_APP_ENV)
ag=ap._agent_module(); assert not any(k in ag.child_env('stage-a','worker') for k in engines.CODEX_APP_ENV)
os.environ.clear(); os.environ.update(saved)
print('PASS console/thread-id-only and inherited-worker controls; detached child environments strip app markers')
PY
