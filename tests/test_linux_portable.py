"""Safety checks for features that cannot work inside a frozen interpreter."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind import builder, runner, sandbox, selfdev


class FrozenSafetyTests(unittest.TestCase):
    def test_no_generated_code_execution(self):
        with tempfile.TemporaryDirectory() as root, patch.object(sys, 'frozen', True, create=True):
            result = builder._run_entry(Path(root), 'main.py')
        self.assertFalse(result['ran'])
        self.assertIn('portable', result['reason'])

    def test_no_frozen_interpreter_for_source_checks(self):
        with patch.object(sys, 'frozen', True, create=True):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                runner.venv_python()

    def test_namespace_launcher_not_claimed_available(self):
        with patch.object(sys, 'frozen', True, create=True):
            self.assertFalse(sandbox.backend().available)

    def test_self_edit_refused_before_files_touched(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(selfdev, 'dev_root') as root:
            with self.assertRaisesRegex(selfdev.SelfDevError, 'portable app'):
                selfdev.apply_edits([])
            root.assert_not_called()

class ModelDownloadSafetyTests(unittest.TestCase):
    def test_download_never_overwrites_existing_model_or_part(self):
        import hashlib
        import io
        from babymind import first_run

        class Response(io.BytesIO):
            headers = {"Content-Length": "3"}

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'model.gguf'
            path.write_bytes(b'keep')
            part = Path(str(path) + '.part')
            part.write_bytes(b'also keep')
            with patch.object(first_run, 'MODEL_SHA256', hashlib.sha256(b'new').hexdigest()), \
                 patch.object(first_run.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 9_000_000_000})()), \
                 patch.object(first_run.urllib.request, 'urlopen', return_value=Response(b'new')):
                with self.assertRaisesRegex(RuntimeError, 'not overwritten'):
                    first_run._download_model(path)
            self.assertEqual(path.read_bytes(), b'keep')
            self.assertEqual(part.read_bytes(), b'also keep')
            self.assertEqual(sorted(p.name for p in Path(root).iterdir()), ['model.gguf', 'model.gguf.part'])

    def test_verified_download_is_published(self):
        import hashlib
        import io
        from babymind import first_run

        class Response(io.BytesIO):
            headers = {"Content-Length": "3"}

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'model.gguf'
            with patch.object(first_run, 'MODEL_SHA256', hashlib.sha256(b'new').hexdigest()), \
                 patch.object(first_run.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 9_000_000_000})()), \
                 patch.object(first_run.urllib.request, 'urlopen', return_value=Response(b'new')):
                first_run._download_model(path)
            self.assertEqual(path.read_bytes(), b'new')
            self.assertEqual([p.name for p in Path(root).iterdir()], ['model.gguf'])

    def test_wrong_hash_removes_partial_without_publishing(self):
        import io
        from babymind import first_run

        class Response(io.BytesIO):
            headers = {}

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'model.gguf'
            with patch.object(first_run.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 9_000_000_000})()), \
                 patch.object(first_run.urllib.request, 'urlopen', return_value=Response(b'bad')):
                with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                    first_run._download_model(path)
            self.assertEqual(list(Path(root).iterdir()), [])
