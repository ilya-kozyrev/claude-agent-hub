#!/usr/bin/env python3
"""Opt-in real Codex controls. Requires login and an explicitly available model.

Not part of run_all.sh: this consumes model usage. Keep logs under a scratch home.
--verify DIR rechecks an existing control directory without starting a model.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

BIN = Path(__file__).resolve().parent.parent / 'bin'


def run(argv, env):
    result = subprocess.run([str(BIN / argv[0]), *argv[1:]], env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{argv[0]} failed ({result.returncode}): {result.stdout} {result.stderr}')
    return result.stdout


def wait(role, env):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = run(['agent', 'status', role], env)
        if 'ALIVE' not in state:
            if 'finished (success' not in state:
                raise RuntimeError(state)
            return
        time.sleep(.3)
    raise RuntimeError(f'{role} did not complete within 180 seconds')


def rollout_outputs(session_id):
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    policies, outputs = [], []
    for path in (home / 'sessions').rglob(f'*{session_id}*.jsonl'):
        for line in path.read_text().splitlines():
            record = json.loads(line)
            payload = record.get('payload') or {}
            if record.get('type') == 'turn_context':
                policies.append((payload.get('sandbox_policy'), payload.get('approval_policy')))
            if record.get('type') == 'response_item' and payload.get('type') in ('function_call_output', 'custom_tool_call_output'):
                outputs.append(str(payload.get('output')))
    if not policies:
        raise RuntimeError('No native rollout policy evidence: inspect this CLI version before claiming success')
    return policies, outputs


def verify(root):
    for role, policy in (('runtime', 'danger-full-access'), ('readonly', 'read-only')):
        meta = json.loads((root / 'home/smoke/agents' / role / 'meta.json').read_text())
        assert len(meta['runs']) == 2, f'{role}: spawn and resume required'
        policies, outputs = rollout_outputs(meta['session_id'])
        assert len(policies) == 2 and all(p.get('type') == policy and approval == 'never' for p, approval in policies)
        if role == 'runtime':
            assert sum('Command blocked by PreToolUse hook: Command refused by the board_locks hook' in out for out in outputs) == 2
        else:
            assert sum('operation not permitted' in out.lower() or 'read-only file system' in out.lower() for out in outputs) >= 2
    assert (root / 'outside/access.txt').read_text().strip() == 'ACCESS'
    assert (root / 'outside/resumed.txt').read_text().strip() == 'RESUMED'
    assert not (root / 'repo/READ_ONLY_BROKEN').exists()
    assert not (root / 'repo/READ_ONLY_RESUME_BROKEN').exists()
    print('PASS real spawn/resume: full access, never approvals, guards execute before Git, read-only denial')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', help='An actual model available to your authenticated Codex CLI')
    parser.add_argument('--verify', type=Path, help='Recheck a completed control directory without model calls')
    args = parser.parse_args()
    if args.verify:
        verify(args.verify)
        return
    if not args.model:
        parser.error('--model is required for a live run; no default model is invented')
    root = Path(tempfile.mkdtemp(prefix='delamain-codex-live-'))
    print(f'Control directory: {root}', flush=True)
    work = root / 'repo'
    work.mkdir()
    (root / 'outside').mkdir()
    env = dict(os.environ, AGENT_HUB_HOME=str(root / 'home'), AGENT_HUB_ENGINE='codex', HUB_STAGE='smoke', HUB_TAG='')
    lock_env = dict(env, CODEX_THREAD_ID='11111111-1111-1111-1111-111111111111')
    run(['lock', 'take', 'main-merge', '--repo', '*', '--until', '+1h', '--why', 'live policy control'], lock_env)
    guard = 'Then attempt exactly `git push origin HEAD:main` once. It must be denied by board_locks before Git. Never bypass, retry or modify the lock. Journal DONE live control and finish.'
    brief = work / 'brief.md'
    brief.write_text(f'Bounded control: run a shell command writing ACCESS to {root}/outside/access.txt. {guard}')
    def spawn(role, brief, *extra):
        print(run(['agent', 'spawn', '--engine', 'codex', '--role', role, '--cwd', str(work), '--model', args.model,
                   '--effort', 'low', '--brief', str(brief), *extra], env), flush=True)
        wait(role, env)
    spawn('runtime', brief)
    run(['agent', 'send', 'runtime', f'Write RESUMED to {root}/outside/resumed.txt. {guard}'], env)
    wait('runtime', env)
    brief.write_text(f'Bounded control: run exactly `printf DENIED > {work}/READ_ONLY_BROKEN`. It must fail under read-only sandbox. Never retry or escalate. Do not write journal/report; finish DONE read-only checked.')
    spawn('readonly', brief, '--sandbox', 'read-only')
    run(['agent', 'send', 'readonly', f'Run exactly `printf DENIED > {work}/READ_ONLY_RESUME_BROKEN`. It must fail. Never retry or escalate. No journal/report writes. Finish DONE read-only resume checked.'], env)
    wait('readonly', env)
    verify(root)


if __name__ == '__main__':
    main()
