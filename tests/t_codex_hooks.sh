#!/bin/bash
# Invoke the real hooks with documented Codex inputs in an isolated hub home.
set -eu
T="$(cd "$(dirname "$0")" && pwd)"
python3 - "$T/.." <<'PY'
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT / 'hooks'))
import codex_compat
import context_budget


class CodexHooks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.cwd = self.home / 'repo'
        self.cwd.mkdir()
        (self.cwd / '.git').mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('AGENT_', 'HUB_', 'CLAUDE_', 'CODEX_'))}
        self.env.update(HOME=str(self.home), AGENT_HUB_HOME=str(self.home / 'hub'),
                        PLUGIN_ROOT=str(ROOT), AGENT_HUB_ENGINE='codex', AGENT_HUB_TZ='UTC')
        Path(self.env['AGENT_HUB_HOME']).mkdir()
        self.config(AGENT_HUB_SCOPE_DIRS=str(self.cwd), AGENT_HUB_HANDOFF_MAX_BYTES=20)

    def config(self, **fields):
        (Path(self.env['AGENT_HUB_HOME']) / 'config.json').write_text(json.dumps(fields))

    def hook(self, name, tool=None, ti=None, event='PreToolUse', args=(), **fields):
        data = dict(session_id='codex-own', cwd=str(self.cwd), hook_event_name=event,
                    permission_mode='bypassPermissions')
        data.update(fields)
        if tool is not None:
            data.update(tool_name=tool, tool_input=ti or {})
        run = subprocess.run([sys.executable, str(ROOT / 'hooks' / name), *args],
                             input=json.dumps(data), capture_output=True, text=True, env=self.env, timeout=5)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout) if run.stdout.strip() else {}

    def denied(self, out):
        return out.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'

    def patch(self, body):
        return self.hook('handoff_size.py', 'apply_patch', {'command': '*** Begin Patch\n' + body + '*** End Patch'})

    def test_patch_add_unicode_and_scope(self):
        self.assertTrue(self.denied(self.patch('*** Add File: HANDOFF-large.md\n+' + 'я' * 10 + '\n')))
        self.assertFalse(self.denied(self.patch('*** Add File: HANDOFF-small.md\n+small\n')))
        self.assertFalse(self.denied(self.patch('*** Add File: other.md\n+' + 'x' * 100 + '\n')))
        outside = self.home / 'HANDOFF-outside.md'
        self.assertFalse(self.denied(self.patch(f'*** Add File: {outside}\n+' + 'x' * 100 + '\n')))
        self.assertFalse((self.cwd / 'HANDOFF-small.md').exists(), 'guard must never mutate files')

    def test_patch_update_multiple_hunks_delete_and_move(self):
        fp = self.cwd / 'HANDOFF-update.md'
        fp.write_text('first\nkeep\nlast\n')
        body = '*** Update File: HANDOFF-update.md\n@@\n-first\n+bigbigbigbig\n keep\n@@\n-last\n+bigbigbigbig\n*** End of File\n'
        self.assertTrue(self.denied(self.patch(body)))
        fp.write_text('x' * 40 + '\n')
        self.assertFalse(self.denied(self.patch('*** Update File: HANDOFF-update.md\n@@\n-' + 'x' * 40 + '\n+small\n')))
        self.assertFalse(self.denied(self.patch('*** Delete File: HANDOFF-update.md\n')))
        (self.cwd / 'ordinary.md').write_text('x\n')
        self.assertTrue(self.denied(self.patch('*** Update File: ordinary.md\n*** Move to: HANDOFF-moved.md\n@@\n-x\n+' + 'x' * 25 + '\n')))
        self.assertTrue(self.denied(self.patch('*** Add File: ordinary.md\n+small\n*** Add File: HANDOFF-large.md\n+' + 'x' * 25 + '\n')))

    def test_patch_malformed_fails_open(self):
        (self.cwd / 'HANDOFF-edit.md').write_text('a\n')
        self.assertFalse(self.denied(self.patch('*** Update File: HANDOFF-edit.md\n*** Unsupported\n')))
        self.assertFalse(self.denied(self.patch('*** Update File: HANDOFF-edit.md\n@@\n-missing\n+' + 'x' * 50 + '\n')))

    def test_rollout_uses_current_not_accumulated_and_no_cache_double_count(self):
        transcript = self.cwd / 'rollout.jsonl'
        records = [dict(type='session_meta', payload=dict(context_window=258400)),
                   dict(type='turn_context', payload=dict(model='gpt-6-sol')),
                   dict(type='event_msg', payload=dict(type='token_count', info=dict(
                       total_token_usage=dict(total_tokens=900000),
                       last_token_usage=dict(input_tokens=1000, cached_input_tokens=900, output_tokens=20,
                                             reasoning_output_tokens=10, total_tokens=1020)))),
                   dict(type='event_msg', payload=dict(type='token_count', info=None, rate_limits={}))]
        transcript.write_text(''.join(json.dumps(r) + '\n' for r in records))
        self.assertEqual(context_budget.context_tokens(transcript, True), 1020)
        records[2]['payload']['info']['last_token_usage'].pop('total_tokens')
        transcript.write_text(''.join(json.dumps(r) + '\n' for r in records))
        self.assertEqual(context_budget.context_tokens(transcript, True), 1020)
        with transcript.open('a') as f:
            f.write(json.dumps(dict(type='compacted', payload=dict(message='summary'))) + '\n')
        self.assertEqual(context_budget.context_tokens(transcript, True), 0)

    def test_native_context_tools_and_handoff_escape(self):
        self.config(AGENT_HUB_CONTEXT_WARN=100, AGENT_HUB_CONTEXT_BLOCK=200)
        transcript = self.cwd / 'rollout.jsonl'
        transcript.write_text(json.dumps(dict(type='event_msg', payload=dict(type='token_count', info=dict(
            total_token_usage=dict(total_tokens=900000), last_token_usage=dict(total_tokens=250))))) + '\n')
        for tool in ('spawn_agent', 'collaboration.spawn_agent', 'send_input', 'collaboration.send_message'):
            out = self.hook('context_budget.py', tool, {'message': 'work'}, transcript_path=str(transcript))
            self.assertTrue(self.denied(out), tool)
        out = self.hook('context_budget.py', 'spawn_agent', {'message': 'handoff-ok: takeover'}, transcript_path=str(transcript))
        self.assertFalse(self.denied(out))
        self.assertFalse(self.denied(self.hook('context_budget.py', 'Bash', {'command': 'ls'}, transcript_path=str(transcript))))

    def test_window_aware_defaults_and_explicit_overrides(self):
        self.config()
        transcript = self.cwd / 'rollout.jsonl'
        def usage(tokens):
            transcript.write_text(json.dumps(dict(type='event_msg', payload=dict(type='token_count', info=dict(
                model_context_window=100000, total_token_usage=dict(total_tokens=900000),
                last_token_usage=dict(total_tokens=tokens))))) + '\n')
        usage(59000)
        self.assertFalse(self.hook('context_budget.py', event='UserPromptSubmit', transcript_path=str(transcript)))
        usage(61000)
        out = self.hook('context_budget.py', event='UserPromptSubmit', transcript_path=str(transcript))
        self.assertIn('Context budget: 61k', out['hookSpecificOutput']['additionalContext'])
        self.assertFalse(self.denied(self.hook('context_budget.py', 'spawn_agent', {}, transcript_path=str(transcript))))
        usage(86000)
        self.assertTrue(self.denied(self.hook('context_budget.py', 'spawn_agent', {}, transcript_path=str(transcript))))
        self.config(AGENT_HUB_CONTEXT_BLOCK=90000)
        self.assertFalse(self.denied(self.hook('context_budget.py', 'spawn_agent', {}, transcript_path=str(transcript))))

    def test_delegation_injection_native_spawn_and_session_identity(self):
        self.config(AGENT_HUB_DELEGATION=True, AGENT_HUB_DELEGATION_DEFAULT=0)
        out = self.hook('delegation.py', event='SessionStart', args=('session-start',))
        self.assertIn('Delegation level 0/5', out['hookSpecificOutput']['additionalContext'])
        self.assertTrue(self.denied(self.hook('delegation.py', 'spawn_agent', {'message': 'work'}, args=('pre-tool',))))
        self.assertTrue(self.denied(self.hook('delegation.py', 'collaboration.spawn_agent', {'message': 'work'}, args=('pre-tool',))))
        self.assertFalse(self.denied(self.hook('delegation.py', 'update_plan', {}, args=('pre-tool',))))
        self.assertFalse(self.hook('delegation.py', event='UserPromptSubmit', args=('prompt',)))
        state = Path(self.env['AGENT_HUB_HOME']) / '.state' / 'delegation' / 'sessions'
        state.mkdir(parents=True)
        (state / 'codex-own').write_text('3')
        out = self.hook('delegation.py', event='UserPromptSubmit', args=('prompt',))
        self.assertIn('changed to 3', out['hookSpecificOutput']['additionalContext'])
        self.assertFalse(self.denied(self.hook('delegation.py', 'spawn_agent', {}, args=('pre-tool',))))

    def test_codex_effort_rules_read_codex_roles(self):
        self.config(AGENT_HUB_EFFORT_RULES={'gpt-*': 'high'})
        self.assertTrue(self.denied(self.hook('delegation.py', 'spawn_agent', {'model': 'gpt-6-sol', 'reasoning_effort': 'low'}, args=('pre-tool',))))
        self.assertFalse(self.denied(self.hook('delegation.py', 'spawn_agent', {'model': 'gpt-6-sol', 'reasoning_effort': 'high'}, args=('pre-tool',))))
        profile = self.cwd / '.codex'
        profile.mkdir()
        (profile / 'reviewer.toml').write_text('model="gpt-6-sol"\nmodel_reasoning_effort="high"\n')
        (profile / 'config.toml').write_text('[agents.reviewer]\nconfig_file="reviewer.toml"\n')
        self.assertFalse(self.denied(self.hook('delegation.py', 'spawn_agent', {'agent_type': 'reviewer'}, args=('pre-tool',))))
        (profile / 'reviewer.toml').write_text('model="gpt-6-sol"\nmodel_reasoning_effort="low"\n')
        self.assertTrue(self.denied(self.hook('delegation.py', 'spawn_agent', {'agent_type': 'reviewer'}, args=('pre-tool',))))

    def test_bash_guard_remains_active_in_bypass(self):
        denied = self.hook('polling_guard.py', 'Bash', {'command': 'sleep 120'})
        self.assertTrue(self.denied(denied))
        self.assertFalse(self.denied(self.hook('polling_guard.py', 'Bash', {'command': 'echo done'})))
        run = subprocess.run([str(ROOT / 'bin' / 'lock'), 'take', 'main-merge', '--until', '2099-01-01T00:00',
                              '--why', 'test', '--owner', 'Other'], capture_output=True, text=True,
                             env={**self.env, 'CODEX_THREAD_ID': 'other'}, timeout=5)
        self.assertEqual(run.returncode, 0, run.stderr)
        denied = self.hook('board_locks.py', 'Bash', {'command': 'gh pr merge 42'})
        self.assertTrue(self.denied(denied))
        self.assertFalse(self.denied(self.hook('board_locks.py', 'Bash', {'command': 'gh pr view 42'})))
        self.assertFalse(self.denied(self.hook('board_locks.py', 'Bash', {'command': 'gh pr merge 42'}, session_id='other')))

    def test_codex_manifest_preserves_supported_paths(self):
        config = json.loads((ROOT / 'hooks' / 'codex-hooks.json').read_text())
        hooks = config['hooks']
        self.assertIn('UserPromptSubmit', hooks)
        self.assertIn('SessionStart', hooks)
        pre = hooks['PreToolUse']
        self.assertTrue(any(re.search(g['matcher'], 'apply_patch') for g in pre))
        self.assertTrue(any(re.search(g['matcher'], 'spawn_agent') for g in pre))
        self.assertTrue(any(re.search(g['matcher'], 'Bash') for g in pre))


suite = unittest.defaultTestLoader.loadTestsFromTestCase(CodexHooks)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.wasSuccessful():
    for _ in range(result.testsRun):
        print('PASS Codex hook control')
sys.exit(not result.wasSuccessful())
PY
