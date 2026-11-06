"""Exercise repository exploration, verified edits, and repair without a model."""
import hashlib
import json
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babymind import coding_engine, selfdev


class FixtureProvider:
    def __init__(self, *, repair=False):
        self.calls = []
        self.submissions = 0
        self.repair = repair

    def complete(self, system, user):
        self.calls.append((system, user))
        if 'STEP 1 OF' in user:
            return json.dumps({'type': 'search', 'query': 'tests/test_ok.py test_ok'})
        if 'STEP 2 OF' in user:
            return json.dumps({'type': 'read', 'path': 'tests/test_ok.py', 'start_line': 1})
        if 'STEP 3 OF' in user:
            digest = re.search(r'"sha256": "([0-9a-f]{64})"', user).group(1)
            self.submissions += 1
            replacement = 'assertEqual(1, 2)' if self.repair and self.submissions == 1 else 'assertEqual(2, 2)'
            return json.dumps({'type': 'submit', 'edits': [{
                'path': 'tests/test_ok.py', 'sha256': digest,
                'search': 'assertEqual(1, 1)', 'replace': replacement}]})
        raise AssertionError(user)


class CodingEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'src/babymind').mkdir(parents=True)
        (self.root / 'tests').mkdir()
        (self.root / 'src/babymind/__init__.py').write_text('')
        (self.root / 'src/babymind/mod.py').write_text('VALUE = 1\n')
        self.test_file = self.root / 'tests/test_ok.py'
        self.original = ('import unittest\nclass Ok(unittest.TestCase):\n'
                         '    def test_ok(self):\n        self.assertEqual(1, 1)\n')
        self.test_file.write_text(self.original)
        self.env = patch.dict(os.environ, {'BABYMIND_DEV_ROOT': str(self.root),
                                          'BABYMIND_SELF_DEVELOPMENT_ENABLED': 'true',
                                          'BABYMIND_SANDBOX': 'off'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def edit(self, path='tests/test_ok.py', search='assertEqual(1, 1)', replacement='assertEqual(2, 2)'):
        data = (self.root / path).read_bytes()
        return {'path': path, 'search': search, 'replace': replacement,
                'sha256': hashlib.sha256(data).hexdigest()}

    def test_end_to_end_search_read_patch_and_real_verification(self):
        provider = FixtureProvider()
        result = coding_engine.develop(provider, 'Update tests/test_ok.py')
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(result['result']['tests']['summary']['ran'], 1)
        self.assertIn('assertEqual(2, 2)', self.test_file.read_text())
        self.assertIn('test_ok.py', provider.calls[1][1])
        self.assertIn('sha256', provider.calls[2][1])
        self.assertTrue(selfdev.verify_audit_chain()['valid'])

    def test_failed_test_rolls_back_then_model_repairs(self):
        provider = FixtureProvider(repair=True)
        result = coding_engine.develop(provider, 'Fix tests/test_ok.py')
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual([h['status'] for h in result['history']], ['rolled_back', 'applied'])
        self.assertIn('assertEqual(2, 2)', self.test_file.read_text())
        self.assertIn('FAILED', provider.calls[3][1])

    def test_rejects_stale_ambiguous_missing_and_duplicate_edits(self):
        good = self.edit()
        (self.root / 'src/babymind/mod.py').write_text('AAA = 1\n')
        overlap = self.edit('src/babymind/mod.py', 'AA', 'B')
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            selfdev.preview_edits([overlap])
        for bad in ({**good, 'sha256': '0' * 64}, {**good, 'search': 'self'},
                    {**good, 'search': ''}, {**good, 'path': '../outside.py'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                selfdev.preview_edits([bad])
        with self.assertRaisesRegex(ValueError, 'twice'):
            selfdev.preview_edits([good, good])
        with self.assertRaisesRegex(ValueError, 'Existing files require'):
            coding_engine._prepare_edits([{'path': 'tests/test_ok.py', 'content': ''}])
        self.assertEqual(self.test_file.read_text(), self.original)

    def test_file_changed_before_checkpoint_is_not_overwritten(self):
        edit = self.edit()
        def concurrent_change(*args):
            self.test_file.write_text(self.original + '# external change\n')
        with patch.object(selfdev, '_worktree_preverify', side_effect=concurrent_change):
            with self.assertRaisesRegex(selfdev.SelfDevError, 'changed after'):
                selfdev.apply_edits([edit])
        self.assertEqual(self.test_file.read_text(), self.original + '# external change\n')

    def test_multifile_search_edits_and_new_file_are_verified_together(self):
        mod = self.root / 'src/babymind/mod.py'
        edits = [self.edit(), self.edit('src/babymind/mod.py', 'VALUE = 1', 'VALUE = 2'),
                 {'path': 'src/babymind/new.py', 'content': 'VALUE = 3\n'}]
        result = selfdev.apply_edits(coding_engine._prepare_edits(edits))
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(mod.read_text(), 'VALUE = 2\n')
        self.assertEqual((mod.parent / 'new.py').read_text(), 'VALUE = 3\n')

    def test_create_only_refuses_file_that_appears_before_transaction(self):
        prepared = coding_engine._prepare_edits([{'path': 'src/babymind/new.py', 'content': 'new'}])
        target = self.root / 'src/babymind/new.py'
        target.write_text('external')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            selfdev.apply_edits(prepared)
        self.assertEqual(target.read_text(), 'external')

    def test_search_edit_preserves_crlf_outside_the_replacement(self):
        mod = self.root / 'src/babymind/mod.py'
        mod.write_bytes(b'ONE = 1\r\nTWO = 2\r\n')
        reviewed = selfdev.preview_edits([self.edit('src/babymind/mod.py', 'ONE = 1', 'ONE = 3')])
        self.assertEqual(reviewed[0]['content'], 'ONE = 3\r\nTWO = 2\r\n')

    def test_read_rejects_symlink_hidden_secrets_traversal_and_binary(self):
        (self.root / 'src/babymind/link.py').symlink_to(self.test_file)
        (self.root / 'src/babymind/credential.py').write_text('secret')
        (self.root / 'src/babymind/binary.py').write_bytes(b'bad\0data')
        for path in ('src/babymind/link.py', 'src/babymind/credential.py',
                     '../outside.py', '.git/config', 'src/babymind/binary.py'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                coding_engine._read_source(path, 1)
        for line in (0, True, '1', 10000):
            with self.subTest(line=line), self.assertRaises(ValueError):
                coding_engine._read_source('tests/test_ok.py', line)

    def test_invalid_action_can_recover_and_no_shell_runs(self):
        class Provider:
            def __init__(self): self.calls = []
            def complete(self, system, user):
                self.calls.append(user)
                if len(self.calls) == 1:
                    return json.dumps({'type': 'run_shell', 'command': 'touch owned'})
                return json.dumps({'type': 'finish', 'reason': 'Cannot safely proceed.'})
        provider = Provider()
        result = coding_engine.develop(provider, 'Do work')
        self.assertEqual(result['status'], 'unrepaired')
        self.assertEqual(result['history'][0]['status'], 'no_change')
        self.assertEqual(result['model_note'], 'Cannot safely proceed.')
        self.assertIn('Unknown action', provider.calls[1])
        self.assertFalse((self.root / 'owned').exists())

    def test_step_budget_and_malformed_json_never_modify_files(self):
        class LoopProvider:
            def complete(self, system, user):
                return json.dumps({'type': 'search', 'query': 'test_ok'})
        result = coding_engine.develop(LoopProvider(), 'Do work', attempts=1)
        self.assertEqual(result['history'][0]['status'], 'proposer_error')
        self.assertIn('step limit', result['history'][0]['detail'])
        class BrokenProvider:
            def complete(self, system, user):
                return '{"type":"finish","type":"submit"}'
        result = coding_engine.develop(BrokenProvider(), 'Do work', attempts=1)
        self.assertEqual(result['history'][0]['status'], 'proposer_error')
        self.assertEqual(self.test_file.read_text(), self.original)

    def test_no_op_rejected(self):
        with self.assertRaisesRegex(ValueError, 'must differ'):
            coding_engine._prepare_edits([self.edit(replacement='assertEqual(1, 1)')])

    def test_required_sandbox_unavailable_fails_without_writing(self):
        with patch.dict(os.environ, {'BABYMIND_SANDBOX': 'require'}), \
             patch('babymind.sandbox.self_test', return_value={'verified': False}):
            result = coding_engine.develop(FixtureProvider(), 'Fix tests/test_ok.py')
        self.assertEqual(result['status'], 'unrepaired')
        self.assertEqual(result['history'][0]['status'], 'rejected')
        self.assertEqual(self.test_file.read_text(), self.original)

    def test_cli_exposes_develop_command(self):
        from babymind.cli import build_parser
        args = build_parser().parse_args(['develop', 'Fix the bug', '--attempts', '3'])
        self.assertEqual((args.command, args.task, args.attempts), ('develop', 'Fix the bug', 3))

    def test_disabled_engine_never_calls_provider(self):
        with patch.dict(os.environ, {'BABYMIND_SELF_DEVELOPMENT_ENABLED': 'false'}):
            with self.assertRaises(selfdev.SelfDevError):
                coding_engine.develop(FixtureProvider(), 'Do work')


if __name__ == '__main__':
    unittest.main()
