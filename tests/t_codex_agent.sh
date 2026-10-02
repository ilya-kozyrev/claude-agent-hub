#!/bin/bash
. "$(dirname "$0")/lib.sh"
new_home; export HUB_STAGE=stage-a HUB_TAG=hub-test CODEX_BIN=$T/fake_codex.py
W=$AGENT_HUB_HOME/repo; mkdir -p "$W"; echo 'do a bounded task' > "$W/brief.md"
spawn(){ "$B/agent" spawn --engine codex --role "$1" --cwd "$W" --brief "$W/brief.md" "${@:2}"; }
wait_done(){ python3 - "$B" "$1" <<'PY'
import subprocess,sys,time
end=time.monotonic()+15
while time.monotonic()<end:
 r=subprocess.run([sys.argv[1]+'/agent','status',sys.argv[2]],capture_output=True,text=True)
 if r.returncode==0 and 'ALIVE' not in r.stdout:break
 time.sleep(.15)
else:sys.exit('agent did not finish')
PY
}
FAKE_CODEX_HOLD=2 spawn worker --model gpt-fixture > "$AGENT_HUB_HOME/spawn.out"; check $? 0 'Codex detached spawn'
"$B/agent" status worker | grep -Eq 'ALIVE'; check $? 0 'generated session ID does not break liveness'
"$B/agent" send worker 'queued control' >/dev/null; check $? 0 'alive Codex inbox'
wait_done worker; check $? 0 'Codex process exits'
"$B/agent" status worker | grep -Eq 'finished \(success.*unread inbox messages 1'; check $? 0 'Codex success + unread messages'
SID=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["session_id"])' "$AGENT_HUB_HOME/stage-a/agents/worker/meta.json")
"$B/agent" send worker 'resume control' >/dev/null; check $? 0 'resume Codex'
wait_done worker
python3 - "$W" "$SID" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);rows=[json.loads(l) for l in (p/'codex-argv.jsonl').read_text().splitlines()]
assert rows[1][:3]==['exec','resume',sys.argv[2]],rows[1][:3]
for row in rows:
 assert '--dangerously-bypass-approvals-and-sandbox' in row
 assert '--dangerously-bypass-hook-trust' in row
 assert '--enable' in row and 'hooks' in row
 assert any(x.startswith('hooks.PreToolUse=') for x in row)
 assert not any(x in row for x in ('--session-id','--effort','--permission-mode','--output-format'))
assert 'queued control' in (p/'codex-prompts.log').read_text()
for env in map(json.loads,(p/'codex-env.jsonl').read_text().splitlines()):
 assert env['AGENT_HUB_ENGINE']=='codex'
 assert not env['CODEX_THREAD_ID'] and not env['CLAUDE_CODE_SESSION_ID']
PY
check $? 0 'resume actual ID, full access and guards on both launches, no host identity leak'
spawn restricted --sandbox read-only --model gpt-fixture >/dev/null; check $? 0 'explicit restricted spawn'
wait_done restricted
"$B/agent" send restricted 'continue restricted' >/dev/null; check $? 0 'restricted resume'
wait_done restricted
python3 - "$W" <<'PY'
import json,sys
from pathlib import Path
rows=[json.loads(l) for l in (Path(sys.argv[1])/'codex-argv.jsonl').read_text().splitlines()][-2:]
for row in rows:
 assert 'sandbox_mode="read-only"' in row and 'approval_policy="never"' in row
 assert '--dangerously-bypass-approvals-and-sandbox' not in row
PY
check $? 0 'restricted sandbox and never policy persist on resume'
FAKE_CODEX_HOLD=30 spawn stoppable >/dev/null; check $? 0 'Codex uses configured CLI default without invented model'
"$B/agent" stop stoppable >/dev/null; check $? 0 'Codex stop'
"$B/agent" send stoppable 'bad' >/dev/null 2>&1; check $? 1 'retired Codex cannot resume'
FAKE_CODEX=die spawn rejected >/dev/null 2>&1; check $? 1 'CLI rejection fails spawn'
"$B/roles" get rejected >/dev/null 2>&1; check $? 1 'rejected launch never registered'
FAKE_CODEX=hang AGENT_INIT_TIMEOUT=1 spawn hanging >/dev/null 2>&1; check $? 1 'init deadline kills hanging CLI'
FAKE_CODEX=error spawn errored >/dev/null; check $? 0 'started thread recorded before API failure'
wait_done errored
"$B/agent" status errored | grep -Eq 'finished \(error, error'; check $? 0 'API failure reported as error'
grep -Eq 'EXIT errored: error' "$(journal stage-a)"; check $? 0 'API failure wakes journal waiter'
spawn badmode --permission-mode auto >/dev/null 2>&1; check $? 2 'unsupported interactive permission mode refused'
spawn both --sandbox read-only --permission-mode bypassPermissions >/dev/null 2>&1; check $? 2 'conflicting policy rejected'
spawn alias --model opus >/dev/null 2>&1; check $? 2 'Claude aliases not silently used for Codex'
AGENT_HUB_CODEX_MODEL_MAP='judge=gpt-fixture' spawn mapped --model judge >/dev/null; check $? 0 'separate Codex model map'
wait_done mapped
CODEX_THREAD_ID=22222222-2222-2222-2222-222222222222 AGENT_HUB_ENGINE=codex "$B/lock" take main-merge --until +1h --why identity >/dev/null; check $? 0 'Codex owns locks under actual thread ID'
CODEX_THREAD_ID=22222222-2222-2222-2222-222222222222 AGENT_HUB_ENGINE=codex "$B/lock" release main-merge >/dev/null; check $? 0 'Codex releases its own lock'

POLICY='{"type":"workspace-write","network_access":false,"exclude_tmpdir_env_var":true,"exclude_slash_tmp":true,"writable_roots":["/tmp/preserved-root"]}'
spawn policy --sandbox-policy "$POLICY" >/dev/null; check $? 0 'structured sandbox policy'
wait_done policy
"$B/agent" send policy 'same restrictions' >/dev/null; check $? 0 'structured sandbox resume'
wait_done policy
python3 - "$W" <<'PY2'
import json,sys
from pathlib import Path
for row in [json.loads(l) for l in (Path(sys.argv[1])/'codex-argv.jsonl').read_text().splitlines()][-2:]:
 assert 'sandbox_workspace_write.network_access=false' in row
 assert 'sandbox_workspace_write.exclude_tmpdir_env_var=true' in row
 assert 'sandbox_workspace_write.exclude_slash_tmp=true' in row
 assert any(x.startswith('sandbox_workspace_write.writable_roots=') and '/tmp/preserved-root' in x for x in row)
 assert '--dangerously-bypass-approvals-and-sandbox' not in row
PY2
check $? 0 'network/temp/root policy preserved on spawn and resume'
spawn unknown --sandbox-policy '{"type":"externalSandbox"}' >/dev/null 2>&1; check $? 2 'unsupported sandbox type refused'
spawn nested --sandbox-policy '{"type":"workspace-write","writable_roots":[{"root":"/tmp","excluded_subpaths":["secret"]}]}' >/dev/null 2>&1; check $? 2 'nested restrictions never silently flattened'
spawn invalid --sandbox-policy '["read-only"]' >/dev/null 2>&1; check $? 2 'policy must be an object'

exit $fail
