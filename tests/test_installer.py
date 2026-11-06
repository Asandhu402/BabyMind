"""Disposable-home tests of installer orchestration, without apt or downloads."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind import install_model


class TerminalModelTests(unittest.TestCase):
    def test_existing_model_is_checked_without_downloading(self):
        with tempfile.TemporaryDirectory() as home, \
             patch.dict(os.environ, {"BABYMIND_HOME": home}, clear=True), \
             patch.object(install_model, "_ensure_model") as ensure:
            self.assertEqual(install_model.main(), 0)
            self.assertEqual(ensure.call_args.args[0], Path(home) / "models" / install_model.MODEL_FILENAME)
            self.assertTrue(callable(ensure.call_args.kwargs["downloader"]))

    def test_downloads_and_verifies_fixture_over_http(self):
        import hashlib
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from babymind import first_run
        data = b"fixture, not model weights" * 1000
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as home, \
                 patch.dict(os.environ, {"BABYMIND_HOME": home}, clear=True), \
                 patch.object(first_run, "MODEL_URL", f"http://127.0.0.1:{server.server_address[1]}/fixture"), \
                 patch.object(first_run, "MODEL_SHA256", hashlib.sha256(data).hexdigest()), \
                 patch.object(first_run.shutil, "disk_usage", return_value=type("Usage", (), {"free": 9_000_000_000})()):
                self.assertEqual(install_model.main(), 0)
                self.assertEqual((Path(home) / "models" / install_model.MODEL_FILENAME).read_bytes(), data)
        finally:
            server.shutdown()
            server.server_close()

    def test_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as home, \
             patch.dict(os.environ, {"BABYMIND_HOME": home}, clear=True), \
             patch.object(install_model, "_ensure_model", side_effect=RuntimeError("hash mismatch")):
            self.assertEqual(install_model.main(), 1)


@unittest.skipUnless(sys.platform.startswith("linux") and os.geteuid() != 0, "needs an unprivileged Linux user")
class InstallerShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.source = self.root / "checkout"
        (self.source / "src/babymind").mkdir(parents=True)
        (self.source / "src/babymind/install_model.py").write_text("# fixture\n")
        (self.source / "pyproject.toml").write_text("# fixture\n")
        repo_script = Path(__file__).resolve().parents[1] / "install-linux.sh"
        # Simulate the supported OS without modifying the machine or changing
        # the commands under test.
        release = self.root / "os-release"
        release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n')
        script = (repo_script.read_text().replace('/etc/os-release', str(release))
                  .replace('python=/usr/bin/python3', f'python={self.root}/bin/python3')
                  # Keep interpreter discovery hermetic: the test must not pick up
                  # a newer Python installed on the machine running the tests.
                  .replace('for candidate in /usr/bin/python3.15 /usr/bin/python3.14 /usr/bin/python3.13 /usr/bin/python3; do',
                           'for candidate in /nonexistent/python3.15 /nonexistent/python3.14 /nonexistent/python3.13; do'))
        self.script = self.source / "install-linux.sh"
        self.script.write_text(script)
        self.script.chmod(0o755)
        build = self.source / "build-linux.sh"
        build.write_text('''#!/bin/bash
set -e
[[ ${FAIL_BUILD:-0} != 1 ]] || exit 42
[[ $BABYMIND_BUILD_PYTHON == "$EXPECTED_PYTHON" ]] || exit 44
mkdir -p dist/BabyMind/llama.cpp
printf '#!/bin/sh\\nexit 0\\n' > dist/BabyMind/BabyMind
printf '#!/bin/sh\\n[ "${FAIL_RUNTIME:-0}" != 1 ]\\n' > dist/BabyMind/llama.cpp/llama-server
chmod +x dist/BabyMind/BabyMind dist/BabyMind/llama.cpp/llama-server
''')
        build.chmod(0o755)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self._stub('sudo', '#!/bin/sh\necho "$*" >> "$FAKE_LOG"\nexit 0\n')
        self._stub('apt-cache', '#!/bin/sh\nexit 1\n')
        self._stub('python3', f'''#!/bin/bash
if [[ ${{1:-}} == -c && ${{2:-}} == *version_info* ]]; then
  [[ ${{OLD_PYTHON:-0}} != 1 ]] || exit 1
  exit 0
fi
if [[ ${{1:-}} == -m && ${{2:-}} == babymind.install_model ]]; then
  echo "model" >> "$FAKE_LOG"
  [[ ${{FAIL_MODEL:-0}} != 1 ]] || exit 1
  exit 0
fi
exec '{sys.executable}' "$@"
''')
        # A different Python on PATH must not override the selected system Python.
        path_python = self.root / 'path-python'
        path_python.mkdir()
        (path_python / 'python3').write_text('#!/bin/sh\necho "wrong Python" >&2\nexit 45\n')
        (path_python / 'python3').chmod(0o755)
        self.log = self.root / 'commands.log'
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), XDG_DATA_HOME=str(self.home / '.local/share'),
                        PATH=f"{path_python}:{self.bin}:{os.environ['PATH']}", FAKE_LOG=str(self.log),
                        TMPDIR=str(self.root), EXPECTED_PYTHON=str(self.bin / 'python3'))
        self.env.pop('BABYMIND_GGUF_MODEL', None)

    def _stub(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_installer(self, **env):
        return subprocess.run(['bash', str(self.script)], env={**self.env, **env},
                              text=True, capture_output=True, timeout=30)

    def test_install_and_repeat_keep_previous_version(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        root = self.home / '.local/share/babymind'
        current = root / 'current'
        first = current.resolve()
        self.assertTrue((current / 'BabyMind').is_file())
        self.assertEqual(os.readlink(self.home / '.local/bin/babymind'), str(current / 'BabyMind'))
        desktop = (self.home / '.local/share/applications/babymind.desktop').read_text()
        self.assertIn('X-BabyMind-Installer=true', desktop)
        self.assertIn(f'Exec="{current}/BabyMind"', desktop)
        log = self.log.read_text()
        self.assertIn('model', log)
        for package in ('libxkbfile1', 'libxcb-xinerama0', 'libfontconfig1', 'libfreetype6'):
            self.assertIn(package, log)
        self.assertFalse((self.source / 'dist').exists(), 'installer must not build in the checkout')
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(first, current.resolve())
        self.assertTrue(first.is_dir(), 'previous version must remain recoverable')

    def test_failed_reinstall_keeps_current_version(self):
        self.assertEqual(self.run_installer().returncode, 0)
        current = self.home / '.local/share/babymind/current'
        original = current.resolve()
        result = self.run_installer(FAIL_BUILD='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(current.resolve(), original)
        self.assertTrue((current / 'BabyMind').is_file())

    def test_failed_runtime_check_keeps_current_version(self):
        self.assertEqual(self.run_installer().returncode, 0)
        current = self.home / '.local/share/babymind/current'
        original = current.resolve()
        result = self.run_installer(FAIL_RUNTIME='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(current.resolve(), original)
        self.assertTrue((current / 'BabyMind').is_file())

    def test_foreign_launcher_is_never_overwritten(self):
        launcher = self.home / '.local/bin/babymind'
        launcher.parent.mkdir(parents=True)
        launcher.write_text('not BabyMind')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(launcher.read_text(), 'not BabyMind')
        self.assertFalse(self.log.exists(), 'must fail before apt')

    def test_failed_model_does_not_publish_or_build(self):
        result = self.run_installer(FAIL_MODEL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / '.local/share/babymind/current').exists())

    def test_python_older_than_3_13_is_rejected_before_model_or_build(self):
        result = self.run_installer(OLD_PYTHON='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Python 3.13 or newer', result.stderr)
        log = self.log.read_text() if self.log.exists() else ''
        self.assertNotIn('model', log)
        self.assertFalse((self.home / '.local/share/babymind/current').exists())

    def test_existing_unmanaged_install_root_is_untouched(self):
        root = self.home / '.local/share/babymind'
        root.mkdir(parents=True)
        (root / 'important.txt').write_text('keep')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((root / 'important.txt').read_text(), 'keep')
        self.assertFalse(self.log.exists())

    def test_documented_one_command_bootstraps_and_cleans_up(self):
        import re
        readme = (Path(__file__).resolve().parents[1] / 'README.md').read_text()
        command = re.search(r'## Install on Ubuntu with one command.*?```bash\n([^\n]+)\n```',
                            readme, flags=re.S).group(1)
        self._stub('git', '#!/bin/bash\nset -e\ncp -a -- "$FAKE_REPO/." "${@: -1}"\n')
        env = {**self.env, 'FAKE_REPO': str(self.source)}
        result = subprocess.run(['bash', '-c', command], env=env, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.home / '.local/share/babymind/current/BabyMind').is_file())
        self.assertFalse(list(self.root.glob('tmp.*')), 'bootstrap checkout must be cleaned')


class InstallAndRunScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.script = self.root / 'install-and-run-linux.sh'

    def test_script_exists_and_is_executable(self):
        self.assertTrue(self.script.is_file())
        self.assertTrue(os.access(self.script, os.X_OK))

    def test_script_passes_bash_syntax_check(self):
        result = subprocess.run(['bash', '-n', str(self.script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_script_covers_detect_install_build_run(self):
        text = self.script.read_text(encoding='utf-8')
        for stage in ('apt-get', 'dnf', 'pacman', 'install-linux.sh', 'babymind'):
            self.assertIn(stage, text)
        # It must hand over to the reviewed installer and then launch the app.
        self.assertIn('exec "$launcher"', text)
