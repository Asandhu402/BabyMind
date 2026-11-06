"""Fixture tests for bootstrap-linux.sh, without touching the real machine.

Every package manager, interpreter and downloader is a stub on PATH; nothing
here installs software, downloads a model or needs network access.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "bootstrap-linux.sh"

PYTHON_STUB = """#!/bin/bash
# Answers the probes bootstrap-linux.sh and install-linux.sh make.
case "$*" in
  *'version_info[:3]'*) echo "{version}" ;;
  *'version_info >= (3, 13)'*) exit 0 ;;
  *LIBDIR*) echo "$FAKE_PY_LIBDIR" ;;
  *LDLIBRARY*) echo "{ldlibrary}" ;;
  *'import venv, ensurepip'*) exit 0 ;;
  *) exec {real_python} "$@" ;;
esac
"""


class BootstrapFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.lib = self.root / "python-lib"
        self.lib.mkdir()
        self.source = self.root / "checkout"
        (self.source / "src/babymind").mkdir(parents=True)
        (self.source / "pyproject.toml").write_text("[project]\nname = 'babymind'\n")
        (self.source / "build-linux.sh").write_text("#!/bin/sh\nexit 0\n")
        (self.source / "src/babymind/install_model.py").write_text("# fixture\n")
        self.installer = self.source / "install-linux.sh"
        self.installer.write_text(
            '#!/bin/bash\necho "install-linux ${BABYMIND_BUILD_PYTHON:-none}" >> "$FAKE_LOG"\n'
        )
        self.installer.chmod(0o755)
        self.log = self.root / "commands.log"
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        # Interpreter discovery must not depend on what the test host has in
        # /usr/bin, so the fixture points it at an empty directory.
        self.system_python_dir = self.root / "system-python"
        self.system_python_dir.mkdir()
        self._stub("sudo", '#!/bin/bash\necho "sudo $*" >> "$FAKE_LOG"\nexec "$@"\n')
        self._stub("apt-cache", "#!/bin/sh\nexit 1\n")
        self._stub("apt-get", '#!/bin/bash\necho "apt-get $*" >> "$FAKE_LOG"\nexit 0\n')
        self._stub("uname", '#!/bin/sh\ncase "$1" in -m) echo x86_64 ;; *) echo Linux ;; esac\n')
        self._stub("ldd", '#!/bin/sh\necho "ldd (Debian GLIBC 2.36-9+deb12u14) 2.36"\n')
        self._stub("nproc", "#!/bin/sh\necho 2\n")
        self._stub("curl", '#!/bin/bash\necho "curl $*" >> "$FAKE_LOG"\nexit 1\n')
        self.python = self._python_stub("python3", "3.13.5")
        env = {
            "HOME": str(self.home),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "TMPDIR": str(self.tmpdir),
            "PATH": f"{self.bin}:{self._runtime_tools()}",
            "FAKE_LOG": str(self.log),
            "FAKE_PY_LIBDIR": str(self.lib),
            "BABYMIND_BOOTSTRAP_SOURCE": str(self.source),
            "BABYMIND_GITHUB_REPO": "Asandhu402/BabyMind",
            "BABYMIND_GITHUB_REF": "main",
            "BABYMIND_BOOTSTRAP_SYSTEM_PYTHON_DIR": str(self.system_python_dir),
        }
        self.env = {**os.environ, **env}
        for name in ("BABYMIND_BOOTSTRAP_PYTHON", "BABYMIND_BOOTSTRAP_PM",
                     "BABYMIND_BOOTSTRAP_DRY_RUN", "BABYMIND_BOOTSTRAP_PREPARE_ONLY",
                     "BABYMIND_BOOTSTRAP_PYTHON_VERSION", "BABYMIND_BOOTSTRAP_PYTHON_PREFIX"):
            self.env.pop(name, None)

    def _stub(self, name: str, content: str) -> Path:
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)
        return path

    RUNTIME_TOOLS = ("bash", "sh", "awk", "grep", "sed", "sort", "tail", "tr", "head",
                     "cut", "mktemp", "rm", "mkdir", "cat", "cp", "mv", "chmod", "env",
                     "tar", "gzip", "dirname", "basename", "ln", "touch", "sleep",
                     "setsid", "true", "id")

    def _runtime_tools(self) -> Path:
        """PATH for the test: the utilities the bootstrap needs, no interpreters.

        Pointing PATH at a curated directory (rather than /usr/bin) keeps the
        test independent of the Python versions installed on the test host.
        """
        runtime = self.root / "runtime"
        runtime.mkdir(exist_ok=True)
        for tool in self.RUNTIME_TOOLS:
            found = shutil.which(tool, path="/usr/bin:/bin")
            if found and not (runtime / tool).exists():
                (runtime / tool).symlink_to(found)
        return runtime

    def _python_stub(self, name: str, version: str, *, shared: bool = True) -> Path:
        if shared:
            (self.lib / "libpython3.13.so.1.0").write_text("")
        return self._stub(name, PYTHON_STUB.format(
            version=version, ldlibrary="libpython3.13.so.1.0" if shared else "",
            real_python=sys.executable))

    def run_bootstrap(self, *arguments: str, **env: str):
        return subprocess.run(
            ["bash", str(SCRIPT), *arguments],
            cwd=self.root, env={**self.env, **env}, text=True,
            capture_output=True, timeout=120,
        )

    def log_text(self) -> str:
        return self.log.read_text() if self.log.exists() else ""


class CommandTests(BootstrapFixture):
    def test_documented_command_is_a_single_self_provisioning_line(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Install on Linux with one command", 1)[1]
        command = section.split("```bash\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(command.count("\n"), 0, "the one-command installer must stay a single line")
        for fragment in ("curl", "wget", "apt-get", "bootstrap-linux.sh"):
            self.assertIn(fragment, command)
        self.assertNotIn("git clone", command, "the bootstrap downloads its own source")
        for unsupported in ("dnf", "pacman", "zypper"):
            self.assertNotIn(unsupported, command)

    def test_script_is_executable_and_syntactically_valid(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_downloads_retry_transfer_failures_and_stay_compatible_with_old_curl(self):
        # curl's --retry covers timeouts and 4xx/5xx only. A transfer failure
        # such as an HTTP/2 stream error (curl exit 92) aborted a hosted
        # portable build outright, so the real detection block is extracted and
        # run here against both a modern and an old curl.
        for name in ("bootstrap-linux.sh", "build-linux.sh"):
            text = (REPO / name).read_text(encoding="utf-8")
            block = re.search(r"(?ms)^[ \t]*(\w+)=''\n[ \t]*if curl --help all .*?^[ \t]*fi\n", text)
            self.assertIsNotNone(block, f"{name} does not feature-detect --retry-all-errors")
            variable = block.group(1)
            downloads = re.findall(r"(?m)^.*\bcurl .*--retry 3.*$", text)
            self.assertTrue(downloads, f"{name} has no curl download line")
            for line in downloads:
                self.assertIn(f"${variable}", line, f"{name} does not use the detected flag: {line}")
            with tempfile.TemporaryDirectory() as directory:
                stub = Path(directory) / "curl"
                env = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"}
                probe = block.group(0) + f'printf "%s\\n" "${variable}"\n'
                stub.write_text("#!/bin/sh\necho ' --retry-all-errors  Retry even on transient errors'\n")
                stub.chmod(0o755)
                modern = subprocess.run(["bash", "-c", probe], env=env, capture_output=True, text=True)
                self.assertEqual(modern.returncode, 0, modern.stderr)
                self.assertEqual(modern.stdout.strip(), "--retry-all-errors --retry-delay 2")
                # An older curl must not be handed a flag it would reject with
                # "option --retry-all-errors: is unknown".
                stub.write_text("#!/bin/sh\necho 'Usage: curl [options...] <url>'\n")
                legacy = subprocess.run(["bash", "-c", probe], env=env, capture_output=True, text=True)
                self.assertEqual(legacy.returncode, 0, legacy.stderr)
                self.assertEqual(legacy.stdout.strip(), "")


class HostTests(BootstrapFixture):
    def test_refuses_musl_systems(self):
        self._stub("ldd", '#!/bin/sh\necho "musl libc (x86_64)"\n')
        result = self.run_bootstrap("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Alpine/musl is unsupported", result.stderr)

    def test_refuses_architectures_other_than_x86_64(self):
        self._stub("uname", '#!/bin/sh\ncase "$1" in -m) echo aarch64 ;; *) echo Linux ;; esac\n')
        result = self.run_bootstrap("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("needs 64-bit x86", result.stderr)

    def test_refuses_an_unknown_package_manager(self):
        result = self.run_bootstrap("--dry-run", BABYMIND_BOOTSTRAP_PM="portage")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported package manager", result.stderr)


class PrepareTests(BootstrapFixture):
    def test_dry_run_reports_the_plan_and_changes_nothing(self):
        result = self.run_bootstrap("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Plan (dry run, nothing was changed)", result.stdout)
        self.assertIn("Package manager: apt-get", result.stdout)
        self.assertIn(str(self.python), result.stdout)
        self.assertNotIn("apt-get install", self.log_text())
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_installs_a_downloader_when_none_exists(self):
        curl = self.bin / "curl"
        curl.unlink()
        # The package-manager stub provides curl on request, like a real install.
        self._stub("apt-get", f'''#!/bin/bash
echo "apt-get $*" >> "$FAKE_LOG"
if [[ $* == *install* && $* == *curl* ]]; then
  printf '#!/bin/sh\\necho "https://www.python.org/ftp/python/"\\n' > "{self.bin}/curl"
  chmod 755 "{self.bin}/curl"
fi
exit 0
''')
        result = self.run_bootstrap("--prepare-only")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self.log_text()
        self.assertIn("install -y", log)
        self.assertIn("curl", log)
        self.assertIn("ready for BabyMind", result.stdout)

    def test_prefers_the_newest_ready_interpreter(self):
        self._python_stub("python3.13", "3.13.9")
        newest = self._python_stub("python3.14", "3.14.4")
        result = self.run_bootstrap("--prepare-only")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(newest), result.stdout)

    def test_skips_interpreters_without_a_shared_library(self):
        self._python_stub("python3.15", "3.15.2", shared=False)
        usable = self._python_stub("python3.13", "3.13.9")
        result = self.run_bootstrap("--prepare-only")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(usable), result.stdout)
        self.assertNotIn("python3.15", result.stdout)

    def test_explains_distribution_and_source_fallbacks_when_nothing_is_ready(self):
        self._python_stub("python3", "3.11.2")
        result = self.run_bootstrap("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Would try the distribution's Python 3.15 packages", result.stdout)
        self.assertIn("would build CPython", result.stdout)
        self.assertIn("from source into", result.stdout)

    def test_finds_a_distribution_interpreter_installed_in_the_system_directory(self):
        system_python = self._python_stub("python3.14-system", "3.14.4")
        (self.system_python_dir / "python3.14").symlink_to(system_python)
        for stub in ("python3", "python3.13", "python3.15"):
            (self.bin / stub).unlink(missing_ok=True)
        result = self.run_bootstrap("--prepare-only")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(self.system_python_dir / "python3.14"), result.stdout)

    def test_uses_an_explicitly_requested_interpreter(self):
        chosen = self._python_stub("python3.14-custom", "3.14.0")
        result = self.run_bootstrap("--prepare-only", BABYMIND_BOOTSTRAP_PYTHON=str(chosen))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(chosen), result.stdout)

    def test_rejects_an_explicit_interpreter_that_is_too_old(self):
        stale = self._python_stub("python3.10", "3.10.19")
        result = self.run_bootstrap("--dry-run", BABYMIND_BOOTSTRAP_PYTHON=str(stale))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a supported Python", result.stderr)


class InstallTests(BootstrapFixture):
    def test_hands_over_to_the_installer_with_the_selected_interpreter(self):
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"install-linux {self.python}", self.log_text())
        self.assertIn("Installing BabyMind", result.stdout)

    def test_prepare_only_never_runs_the_installer(self):
        result = self.run_bootstrap("--prepare-only")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("install-linux", self.log_text())
        self.assertIn("ready for BabyMind", result.stdout)

    def test_downloads_the_source_into_a_temporary_directory_and_cleans_up(self):
        archive = self.root / "repo.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.installer, arcname="BabyMind-main/install-linux.sh")
            tar.add(self.source / "pyproject.toml", arcname="BabyMind-main/pyproject.toml")
            tar.add(self.source / "build-linux.sh", arcname="BabyMind-main/build-linux.sh")
            tar.add(self.source / "src", arcname="BabyMind-main/src")
        self._stub("curl", f'''#!/bin/bash
echo "curl $*" >> "$FAKE_LOG"
previous=
for argument in "$@"; do
  if [[ $previous == --output ]]; then cp -a "{archive}" "$argument"; exit 0; fi
  previous=$argument
done
echo "curl $*" >&2
exit 1
''')
        for name in ("BABYMIND_BOOTSTRAP_SOURCE",):
            self.env.pop(name, None)
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Downloading the newest Asandhu402/BabyMind (main)", result.stdout)
        self.assertIn("install-linux", self.log_text())
        self.assertEqual(list(self.tmpdir.iterdir()), [], "the downloaded source must be cleaned up")


if __name__ == "__main__":
    unittest.main()
