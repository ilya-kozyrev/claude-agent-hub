#!/usr/bin/env bash
# Runtime, identity and reviewer-budget controls: fake homes/caches, no model or native app calls.
set -euo pipefail
PARITY_ROOT="${BIN:-$(cd "$(dirname "$0")/../bin" && pwd)}"
PARITY_TMP="$(mktemp -d)"
trap 'rm -rf "$PARITY_TMP"' EXIT
python3 - "$PARITY_ROOT" "$PARITY_TMP" <<'PY'
import importlib.machinery, importlib.util, json, os, pathlib, shutil, subprocess, sys
bins, tmp = (pathlib.Path(p).resolve() for p in sys.argv[1:])
sys.path.insert(0, str(bins))
import hubcore as hc
loader = importlib.machinery.SourceFileLoader('parity_hub', str(bins/'hub'))
spec = importlib.util.spec_from_loader(loader.name, loader)
hub = importlib.util.module_from_spec(spec); loader.exec_module(hub)
case = os.environ.get('PARITY_CASE', 'all')
env = {k:v for k,v in os.environ.items() if not k.startswith(('AGENT_', 'HUB_', 'CODEX_', 'CLAUDE_', 'PLUGIN_'))}
env.update(AGENT_HUB_HOME=str(tmp/'home'), AGENT_HUB_STATE_DIR=str(tmp/'state'), HOME=str(tmp/'user'),
           CLAUDE_CONFIG_DIR=str(tmp/'claude'), CODEX_HOME=str(tmp/'codex'), CLAUDE_BIN=str(tmp/'no-cli'),
           AGENT_HUB_TZ='UTC', AGENT_HUB_NO_PROJECT='1', AGENT_HUB_NO_NAMING='1')
os.environ.clear(); os.environ.update(env)
old = '11111111-1111-4111-8111-111111111111'
new = '22222222-2222-4222-8222-222222222222'
stage = tmp/'home/stage-a'; stage.mkdir(parents=True)
record = {'session':old, 'cli_session_id':old, 'tag':'hub-1', 'kind':'cli', 'engine':'codex'}
(stage/'roles.json').write_text(json.dumps({'roles':{'hub':record}}))

def call(b, *args, extra=None):
    return subprocess.run([str(b), *args], env=env | (extra or {}), cwd=tmp, text=True, capture_output=True, timeout=30)

if case in ('all', 'identity'):
    for identity in ('CODEX_THREAD_ID', 'AGENT_SESSION_ID', 'CLAUDE_CODE_SESSION_ID'):
        os.environ.pop('CODEX_THREAD_ID', None); os.environ.pop('AGENT_SESSION_ID', None)
        os.environ.pop('CLAUDE_CODE_SESSION_ID', None)
        os.environ['AGENT_HUB_ENGINE'] = 'claude' if identity.startswith('CLAUDE') else 'codex'
        os.environ[identity] = old
        rows = hub.hub_sessions('stage-a', 'self', {'cli':new})
        assert rows[0][0] == old and rows[0][1]['tag'] == 'hub-1', rows
    # A worker's own UUID has priority over an inherited Claude identity.
    os.environ.update(AGENT_HUB_ENGINE='codex', CODEX_THREAD_ID=new, AGENT_SESSION_ID=old,
                      CLAUDE_CODE_SESSION_ID=old)
    assert hc.session_id() == new
    for key in ('CODEX_THREAD_ID', 'AGENT_SESSION_ID', 'CLAUDE_CODE_SESSION_ID'):
        os.environ.pop(key, None)
    try: hub.hub_sessions('stage-a', 'self', {'cli':old})
    except hc.UsageError: pass
    else: raise AssertionError('unresolved self borrowed the registered hub identity')
    print('PASS self resolves both hosts and worker identity with registry ownership; missing identity refuses')
    for engine, key in (('codex', 'CODEX_THREAD_ID'), ('codex', 'AGENT_SESSION_ID'), ('claude', 'CLAUDE_CODE_SESSION_ID')):
        path=tmp/f'HANDOFF-{engine}-{key}.md'
        r=call(bins/'hub', 'handoff', '--stage','stage-a','--session','self','--out',str(path),
               extra={'AGENT_HUB_ENGINE':engine, key:old})
        assert r.returncode == 0, (r.stdout, r.stderr)
        text=path.read_text()
        if engine == 'codex':
            assert 'yielded shell session' in text and 'at most 60 s' in text and 'run_in_background' not in text
        else:
            assert 'Bash `run_in_background: true`' in text and 'yielded shell session' not in text
    print('PASS generated handoff wait procedure follows Claude, Codex and detached Codex hosts')

if case in ('all', 'runtime'):
    runtime=tmp/'runtime'; shutil.copytree(bins, runtime/'bin', ignore=shutil.ignore_patterns('__pycache__'))
    for engine in ('claude', 'codex'):
        manifest=runtime/f'.{engine}-plugin/plugin.json'; manifest.parent.mkdir()
        manifest.write_text(json.dumps({'name':'agent-hub','version':'0.9.0' if engine=='claude' else '0.8.0'}))
    def cache(engine, folder, version=None):
        path=tmp/engine/'plugins/cache/market/agent-hub'/folder
        (path/'bin').mkdir(parents=True)
        if version is not None:
            manifest=path/f'.{engine}-plugin/plugin.json'; manifest.parent.mkdir()
            manifest.write_text(json.dumps({'version':version}))
        return path/'bin'
    cache('claude', '0.8.1'); cache('codex', '0.7.1'); cache('codex', 'unknown', 'bad')
    high=cache('claude', '0.10.0'); low=cache('codex', '0.8.0')
    for engine, expected in (('claude','0.9.0'), ('codex','0.8.0')):
        extra={'AGENT_HUB_ENGINE':engine, 'CODEX_THREAD_ID':old} if engine=='codex' else {'AGENT_HUB_ENGINE':engine,'CLAUDE_CODE_SESSION_ID':old}
        r=call(runtime/'bin/agent', 'status','--stage','stage-a', extra=extra)
        assert r.returncode==0, r.stderr
        assert f'agent-hub {expected} ({engine}; {runtime}/bin)' in r.stdout, r.stdout
        assert ('newer' in r.stdout) == (engine=='claude'), r.stdout
    cache('codex', '0.9.2'); cache('codex', '0.9.1')
    for engine in ('claude','codex'):
        extra={'AGENT_HUB_ENGINE':engine, 'CODEX_THREAD_ID':new} if engine=='codex' else {'AGENT_HUB_ENGINE':engine,'CLAUDE_CODE_SESSION_ID':new}
        r=call(runtime/'bin/hub','takeover','--stage','stage-a','--session','self','--dry-run', extra=extra)
        assert r.returncode==0, (r.stdout,r.stderr)
        assert 'Plugin runtime: agent-hub' in r.stdout and str(runtime/'bin') in r.stdout, r.stdout
        expected='0.9.2' if engine=='codex' else '0.10.0'
        assert f'newer {engine} plugin {expected}' in r.stdout, r.stdout
        digest=r.stdout[r.stdout.index('DIGEST'):]
        assert len(digest.encode()) <= 3072
        assert ('yielded shell session' in digest) == (engine=='codex')
    # An unreadable runtime version cannot honestly be ordered against the caches.
    (runtime/'.claude-plugin/plugin.json').write_text('{}'); (runtime/'.codex-plugin/plugin.json').write_text('{}')
    r=call(runtime/'bin/agent','status','--stage','stage-a',extra={'AGENT_HUB_ENGINE':'codex'})
    assert r.returncode==0 and 'version unknown' in r.stdout and 'newer' not in r.stdout
    print('PASS actual bin manifests, same-engine fake caches, semantic ordering, unknown versions and bounded takeover digest')

if case in ('all', 'helpers'):
    os.environ.pop('AGENT_HUB_REVIEW_HELPER_LINES', None)
    assert hc.review_helper_lines() == 300
    repo=tmp/'repo'; repo.mkdir(); (repo/'.agent-hub').mkdir()
    subprocess.run(['git','init','-q',str(repo)],check=True,capture_output=True)
    homeconfig=tmp/'home/config.json'; homeconfig.write_text(json.dumps({'AGENT_HUB_REVIEW_HELPER_LINES':180}))
    os.chdir(repo); hc._CONFIG_CACHE.clear()
    assert hc.review_helper_lines() == 180
    (repo/'.agent-hub/config.json').write_text(json.dumps({'AGENT_HUB_REVIEW_HELPER_LINES':90}))
    hc._CONFIG_CACHE.clear()
    assert hc.review_helper_lines() == 90
    os.environ['AGENT_HUB_REVIEW_HELPER_LINES']='0'
    assert hc.review_helper_lines() == 0
    os.environ['AGENT_HUB_REVIEW_HELPER_LINES']='invalid'
    try: hc.review_helper_lines()
    except hc.UsageError: pass
    else: raise AssertionError('bad threshold accepted')
    r=call(bins/'hub','reviewer','--for','docs','--json',extra={'AGENT_HUB_REVIEW_HELPER_LINES':'77'})
    assert json.loads(r.stdout)['helper_threshold'] == 77, (r.stdout,r.stderr)
    print('PASS helper threshold defaults/layers/env/zero/invalid controls and reviewer JSON expose the configured cap')
PY
