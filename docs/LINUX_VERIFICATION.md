# Linux desktop verification (2026-11-04)

This work is **not release acceptance**. The 64-bit Linux portable path is a
work in progress, not yet demonstrated plug-and-play end to end.

- Linux x86-64, glibc 2.36, Python 3.11.2: 295 unittest tests ran successfully, with one GUI test skipped. Tests include
  an actual streamed download from a local HTTP fixture and checks that frozen
  builds refuse unsupported self-edit and generated-code execution. The fixture
  is not the model. The Qt GUI integration test is configured for Linux CI with
  Xvfb but has not run in this environment. Python, shell and JavaScript syntax checks also passed.
- The pinned b11960 llama.cpp source archive was downloaded from GitHub's
  codeload host, checked against the build-script SHA-256, compiled into a CPU
  `llama-server`, and its `--version` command ran. No model was loaded and no
  inference was performed. The local exploratory build inherited this
  repository's Git metadata when displaying the version; the build script now
  specifies b11960 explicitly and prevents this parent-repository lookup.
- A full `build-linux.sh` attempt failed at PyInstaller because this sandbox's
  system Python has no matching shared libpython. An exploratory build using a
  separately compiled upstream libpython produced an onedir tree, but the
  frozen process failed to boot (`_struct` was missing): that library did not
  match the sandbox's statically built Python. This is not a successful package
  smoke test, and the exploratory tree must not be distributed.
- Qt WebEngine import failed because this sandbox lacks `libGL.so.1` and many
  other Linux desktop libraries, and it has no display. No GUI startup,
  first-run consent/progress/cancellation, or window interaction was tested.
- This environment cannot reach Hugging Face or GitHub release-asset hosts. No
  real model download, independent validation of its pinned checksum, or
  end-to-end inference was tested. Model-license terms could not be independently
  checked here. The repository has no top-level project license; redistribution is not
  cleared. No release, tag, PR, or publication was performed.
- The 50 role-guided passes requested for major development were not executed:
  no working local model was available in this environment. No specialist
  contributions or verification records are claimed for this change.

## Ubuntu installer changes

The installer orchestrates real Ubuntu package installation, an isolated source
build, a terminal model download, and per-user launchers. Its automated tests
use fake package-manager and build commands in disposable homes; they do not
install Ubuntu packages or fetch the real model. The current environment is
Debian without a graphical desktop, and access to Ubuntu mirrors and Hugging
Face is blocked, so an actual clean Ubuntu installation is not verified.
The Linux CI runs for PR #46 and its merge both failed at the Qt GUI test;
detailed logs could not be retrieved from the restricted GitHub log host. This
is an unresolved blocker, not evidence that the GUI works.

Before calling this plug-and-play: build on a supported clean desktop Linux
host with a matching shared Python, review project/Qt/model redistribution
terms, run the packaged GUI and real first download and inference, test offline
restart and cancellation, and validate namespace/safety behavior and recovery
on target hardware. Check CPU/RAM requirements and portability on the actual
supported distributions. The CI Qt test serves real application assets with fixture APIs and the
headless package check does not load a model; neither substitutes for those
acceptance tests.

## Fresh Ubuntu 22.04 filesystem audit

A separate source-suite run used an isolated, unprivileged process inside an
Ubuntu 22.04 x86-64 root filesystem (glibc 2.35), with an isolated network
namespace and loopback enabled for local HTTP fixtures. It was **not** an Ubuntu
Desktop install, VM, or end-to-end test of the installer.

The Ubuntu base archive was obtained from the Git repository at
`biraj21/focker` commit `43a5aedae6acf06b9af326d95474cbd24f38c8a9`. Its
SHA-256 was `df6fe77cee11bd216ac532f0ee082bdc4da3c0cc1f1d9cb20f3f743196bc4b07`,
matching the independent published `tools.lock` reference in
`imjustadudegamer/VoyagerSP-Android` commit
`c73750361cfc22c1afb3a2c160fa9c5df57214db`. Canonical's checksum signature
could not be fetched or verified from this network; this is not an official
image verification. The base filesystem has no Python, so this test injected a
separately obtained third-party CPython 3.10.19 build from
`TCATools/linux-Python-v3.10.19` commit
`2464dbe519f8ced8dcd19284be432bf75575d5db`, plus PyPI `cryptography` 50.0.2,
`cffi` 2.0.0 and `pycparser` 2.23 wheels. This is not Ubuntu's packaged Python.
No unrelated host directories or credentials were mounted into the test.

- Initial run: **304 tests, 7 failures, 15 errors, 9 skipped**. The failures and
  errors all traced to the runner rejecting its own executable when named
  `python3.10`. The fix permits only the active interpreter's actual file,
  not arbitrary binaries named like versioned Python.
- After the fix: **306 tests, 9 skipped, no failures**. Eight skips were Linux
  namespace boundary tests because nested namespaces were unavailable inside
  this isolated environment; the other skip was the Qt GUI test.
- A fresh Debian host run passed **306 tests, 1 skipped**. Shell, Python,
  JavaScript and patch whitespace checks passed there.
- The bare Ubuntu image did not contain sudo, CMake, Xvfb or the desktop
  libraries. Running the installer on it stopped at the missing-sudo check.
  Ubuntu Desktop installations commonly include sudo, but this does not
  establish package-install behavior. Installer orchestration tests replace
  apt, build, model and bootstrap network operations with fixtures.
- The real Ubuntu package installation, GUI, portable build, real model
  download and inference were not tested. This environment cannot reach Ubuntu
  package mirrors, Hugging Face or GitHub Actions log storage. The previous
  Ubuntu GitHub CI runs for PR #46 and its merge failed at the Qt GUI test;
  detailed logs remained inaccessible. No new GitHub Actions run or release
  was initiated by this audit.

## Pinned model cross-check

For the one-command installer, the model revision was aligned to
`c09cdbcdb1fefad6d335809d445621b5f5ba0c6e`. Two independent public model
catalogs list that revision, the exact GGUF filename and the same pinned
SHA-256: `kotamochi/lumocord` at commit
`2b1785668e0206b96276109f6e33ec66f2023427` (`model-lock.json`) and
`sayrias/Kayriva` at commit `3d8d72a3c0620448200982afb5ce11b0e47b45ed`
(`models/catalog.json`). These are secondary sources, not verification from
Hugging Face. The real file and model-host access remain untested.

## Single-command bootstrap fixture on Ubuntu

The exact README command was exercised in the same isolated Ubuntu 22.04 root
filesystem using the separately supplied Python described above. The command's
shell, terminal model downloader, SHA-256 verification, per-user installation
and desktop-entry creation ran there. The model bytes came from a real local
HTTP fixture and the model URL and expected digest were changed **only in the
isolated test copy**. Git clone, sudo/apt operations and the desktop/runtime
build were simulated. The fixture passed, including verification of the saved
bytes and both launchers. It does not prove that the actual model URL, Ubuntu
packages, built application, Qt GUI or inference work.

Both previous Ubuntu GitHub Actions runs completed the portable-build and
source-test steps, then failed the Qt GUI test; packaging checks and artifact
upload were skipped. No passing Linux artifact was produced by those runs.

Latest installer changes: 307 tests ran with no failures in both environments:
9 were skipped in the isolated Ubuntu filesystem (GUI plus eight nested-
namespace tests) and one GUI test was skipped on the Debian host. The exact
bootstrap was rerun against a local HTTP fixture after the dependency-list
changes; sudo/apt, Git clone and the build were still simulated. The installer
now explicitly includes additional Qt/X11 libraries, but their installation
and a functioning GUI remain unverified on a real Ubuntu desktop.

## Follow-up installer and runtime fixes

The Ubuntu installer now selects `/usr/bin/python3` after installing Ubuntu's
Python packages, and passes that same interpreter to the isolated build. This
avoids accidentally using an unrelated Python earlier on PATH. A fixture checks
the selected interpreter and build invocation; the real apt installation and
frozen build are still untested here.

Model startup now checks for an occupied TCP port rather than interpreting
unsuccessful HTTP health responses as a free port. Invalid ports fail clearly,
and startup timeout cleanup reaps a terminated or killed subprocess. Tests use
an actual listening socket and a mocked subprocess; they do not load a model.
The port probe is released before the model process binds, so a race remains and
this check does not authenticate the server or defend against a hostile local
process. Real inference and the failed Qt CI test remain unverified.

On Debian, **309 tests ran without failures, one GUI test skipped** after these
changes. Python, shell and JavaScript syntax and patch whitespace checks also
passed. The 50 role-guided passes were not executed.

## Headless GUI and synthetic-model follow-up

A later experiment ran the source Qt smoke test successfully under Xvfb in the
isolated Ubuntu 22.04 Base filesystem described above. The UI DOM and navigation
fixture passed, but Xvfb reported missing OpenGL/RHI support: this does not
establish that pixels render on a normal desktop. It used PySide6 6.8.3 from
PyPI; a mixture of Ubuntu Base libraries, host GLib libraries, third-party
libraries from `eXtern-OS/eXternOS-Base` commit
`ec0e026a2b09225b5a85369c3627aedaf6dc2a5f`, and the Xvfb/library bundle in npm
`pdf-poppler-binaries-linux` 0.1.0-beta. XKB data and xkbcomp were taken from
`fonghuiyue/aws-lambda-xvfb` commit `f6cf914540cd69d0e184d2d249bc72875a931785`.
The test ran in a network-isolated user/mount/PID namespace, with the Qt
WebEngine sandbox disabled **only for this fixture**. These third-party
components were not added to the installer or distributed. The original GitHub
CI failure still has no accessible traceback, so its cause is not established.

A separate test compiled llama.cpp b11960 and a PyInstaller package on the
Debian host using the third-party Python 3.10.19. Its initial build was not
Ubuntu-compatible: its bundled libstdc++ and libexpat required glibc 2.36.
For a **test-only** run in Ubuntu Base, those two files were replaced with an
Ubuntu-base libstdc++ and the third-party bundle's libexpat; libgomp was also
supplied from the eXtern OS tree. The test package was separately rebuilt with
its pinned model hash changed to a 132 KB deterministic, randomly initialized
GGUF generated using the pinned llama.cpp's `gguf-py`, NumPy 2.2.6 and PyYAML
6.0.3. The production model hash was not changed. Under offscreen Qt with
WebEngine sandbox disabled only for this isolated test, the frozen app started
its real llama-server, served its real web assets, reported model health ready,
and returned a chat response. That response was meaningless random-weight
output, not an evaluation of BabyMind's model or chat quality. OpenGL/Vulkan
warnings were present; no actual visible desktop or pixel rendering was tested.
The real model host, model file and production inference remain unverified.

The first chat attempt exceeded the synthetic model's 1,024-token *training*
context cap. Raising that synthetic fixture's cap to 4,096 enabled the chat
check. Independently, BabyMind now explicitly requests one llama-server slot,
matching its serialized inference policy and avoiding context division across
multiple slots. An opt-in integration test generates an untrained fixture,
checks the server's advertised 4,096-token context and runs a real completion;
CI is configured to run it, but no new CI run was initiated here. The installer
also runs `llama-server --version` before publishing, and preserves the prior
version if that check fails. The GUI test imports WebEngineWidgets before
creating QApplication and CI declares the complete tested Qt/X11 library list;
these changes are not proof of the original CI failure's cause.

The latest source suite on Debian ran **312 tests without failures, two skipped**
(the GUI and opt-in runtime test). The optional real runtime test passed
separately in the isolated Ubuntu filesystem. Fresh Ubuntu
Desktop package installation, production model download, production inference,
normal GUI rendering and all 50 role-guided passes remain unverified.

## GitHub GUI abort investigation

The GitHub check-run annotations for the failed PR and merge runs report
`Process completed with exit code 134`, indicating an abort rather than a
normal unittest assertion failure. They contain no native traceback; the
underlying Actions log download still redirects to an inaccessible host.
The original, unchanged GUI test passed 20 consecutive isolated Xvfb runs with
PySide6 6.8.3 and third-party Python 3.10, and also passed on a copied host
Python 3.11. Neither environment matched the GitHub runner's installed desktop
stack or graphics capabilities, so these runs do not reproduce or explain the
abort.

The test now imports QtWebEngineWidgets before creating QApplication and passes
an explicit application name instead of an empty argument list. CI now installs
additional Qt/X11 dependencies, enables Qt plugin and Python fault diagnostics,
and includes bounded failure excerpts in GitHub check annotations while
preserving the test's original exit code. The updated test passed ten times
with the copied host Python 3.11 in the isolated Xvfb environment. A simulated
workflow abort confirmed that exit code 134 is preserved and the error appears
in a check annotation. The Debian suite ran 314 tests without failures, with
two skipped; the added workflow-diagnostic regression also passed separately.
These are preventative changes and an improved diagnostic path, not proof that
the GitHub abort is fixed. A new GitHub Actions run on these changes is needed
to confirm.
