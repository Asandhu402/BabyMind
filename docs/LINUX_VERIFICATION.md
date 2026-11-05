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
The authorized GitHub workflow-dispatch run `41917882980` on commit `ceaa3a9`
passed the build, source tests and synthetic llama.cpp integration, but failed
the GUI step with exit 134. The new check annotation identified its concrete
cause: Qt's `libqxcb.so` could not load `libxcb-shape.so.0`. CI had not
explicitly installed Ubuntu's `libxcb-shape0`, although the Ubuntu installer
already did. CI now installs that package and the other explicit XCB libraries
from the installer; a regression test compares the two package lists. The
updated Debian suite ran 316 tests without failures, with two skipped.

The missing-library failure was independently reproduced in the isolated Xvfb
fixture by removing `libxcb-shape.so.0` from a temporary library directory: Qt
reported the same missing library and aborted. Restoring the library made the
GUI test pass again. The isolated test used Python 3.11 and mixed third-party
libraries; it is not the GitHub runner. The earlier CI runs' log messages are
still inaccessible, so their exact root cause cannot be conclusively established
from the matching exit codes alone. At the time of this investigation no
second GitHub run had yet confirmed the corrected workflow; see the later
verification below.

## Post-merge verification (2026-11-04)

GitHub Actions run [41920452582](https://github.com/Asandhu402/BabyMind/actions/runs/41920452582)
completed successfully on merge commit `0870e66b20441a283c0f97f1ca403bd79e4678a3`.
It installed Linux test libraries on an Ubuntu 22.04 hosted runner, built the
portable package, passed the source suite, ran llama.cpp with an untrained
synthetic model, passed the Qt/Xvfb local-fixture test, checked package files
and desktop imports, and uploaded a build artifact. The PR run
[41919151229](https://github.com/Asandhu402/BabyMind/actions/runs/41919151229)
also passed. These runs did not execute `install-linux.sh` on a fresh Ubuntu
Desktop, download the production model, or test production inference.

The model publisher's [revision metadata](https://huggingface.co/api/models/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive/revision/c09cdbcdb1fefad6d335809d445621b5f5ba0c6e?blobs=true)
was retrieved through the page-fetch service. It lists the pinned Q4_K_M filename,
size 2,707,513,696 bytes and LFS SHA-256
`79e28ecacf84e75b6056cf4059636d435aa9eb67795780f7b7dbc7d32a962741`, matching
the application's pinned digest. The publisher's model card lists Apache-2.0.
This verifies metadata against the publisher, not the bytes or inference.

The current execution environment is headless Debian 12, not Ubuntu Desktop.
Its shell cannot connect to `huggingface.co` or `archive.ubuntu.com`
(`SSL_ERROR_SYSCALL`), and no installed graphical desktop or VM runtime was
available. It therefore could not download the real model, install real Ubuntu
packages, or perform the requested fresh-desktop end-to-end test. No new CI run,
model-inference result or 50-role contribution is claimed.

## Virtual-test attempt (2026-11-04)

For the follow-up request, the current environment was checked again: it has
no QEMU, Docker, Podman, Xvfb, `/dev/kvm`, Ubuntu desktop image or GGUF model.
A direct request to the installer's exact model URL failed with curl exit 35
(`SSL_ERROR_SYSCALL`); an Ubuntu archive request also failed. Running the
unmodified installer on the Debian host stopped at its Ubuntu version guard
with exit 1, before installing packages or changing user data. This is the
expected behavior on Debian, not an Ubuntu installation test. A virtual
Ubuntu Desktop, production-model download, actual GUI conversation, and the
requested fix-and-retest acceptance loop remain blocked. The earlier augmented
Ubuntu Base and synthetic model tests described above are not substitutes.

## Trained-model source-path test in isolated Ubuntu filesystem (2026-11-04)

This was a network-isolated Ubuntu 22.04 **Base chroot**, not a virtual machine,
Ubuntu Desktop, installed/frozen app, production model, or visual GUI test. It
used the third-party Base archive and Python described above (Canonical did not
sign or verify this copy), PyPI cryptography 50.0.2, cffi 2.1.1 and pycparser
3.11, the CPU llama-server built from the SHA-pinned b11960 source on Debian,
and a Debian libgomp copied into the disposable root. Network namespace allowed
loopback only; no host project, user data, or credentials were mounted. The
chroot and downloads are test artifacts and are not distributed.

A small **trained but not instruction-tuned** story model was taken from
`jayeshmahapatra/llama2.npy` commit `0687144b5483c1170a03e45639da8db0406c7a27`.
Its original `stories15M.bin` was 60,816,028 bytes with SHA-256
`cd590644d963867a2b6e5a1107f51fad663c41d79c149fbecbbb1f95fa81f49a`, matching
the [model author's metadata](https://huggingface.co/api/models/karpathy/tinyllamas/revision/0bd21da7698eaf29a0d7de3992de8a46ef624add?blobs=true).
The mirror's tokenizer had SHA-256
`50a52ef822ee9e83de5ce9d0be0a025a773d019437f58b5ff9dcafb063ece361`.
Llama.cpp's converter created a GGUF with SHA-256
`a4a429f2a6527275de0d53ffa5e3e8eabe320f618004120d51e1b1faae8bb567`.

The first source-provider run failed all three chat requests, one coding
request and all 50 mission roles with HTTP 400 because llama-server capped
requests at this converted model's declared 128-token context. For a separate
experimental run **only**, the GGUF's declared context metadata was changed
from 128 to 4096 (resulting SHA-256
`b40a0b2f0335c990c2fbb4044fe3197aacfc6e34e7e94bc5e9b308002fb20087`). This
model was not trained for this length; changing metadata does not increase its
trained context or make it an instruction model. BabyMind's production model
and hash were not changed, and the desktop's pinned-model check was not bypassed
or tested: this invoked the source provider directly.

With that experimental model, the real source backend `/api/chat` and coding
endpoint returned HTTP 200 but failed the content check. For example, “What is
2 plus 2?” returned repeated fragments including “The consequences”; the coding
request returned story fragments, not a Python function. In a separate live
mission all 50 role calls returned non-empty text, but the output was repetitive
and unusable, not evidence that the roles performed their jobs. This exposed a
misleading display: the backend counted any nonempty text as a contribution and
called the mission completed. The mission summary and UI now explicitly state
that completion is not verification, and the same live mission was rerun with
that warning present. The underlying classification still checks nonempty text,
not semantic quality. All roles use one model, not 50 independent agents.

A real-model self-edit request against a disposable project produced no JSON
patch, was recorded `no_change`, and left the file unchanged; it did not prove
model-driven code modification. Separately, 19 orchestration tests using fake
providers passed inside the Ubuntu filesystem, including a real disposable-file
patch, compile/test verification, rollback, and a second repair attempt. In
that isolated test, sandbox `auto` could fall back to execution inside the
existing chroot; no nested OS sandbox is claimed. The frozen desktop disables
self-edit and cannot presently satisfy the requested packaged self-upgrade.

After the display fix, the source unittest suite ran **321 tests, OK, 17
skipped** in this augmented Ubuntu Base environment. These tests use mocks and
fixtures extensively and do not prove production inference, visible desktop
operation, all-role competence, or autonomous self-upgrade. The 50 requested
specialist contributions were not independently verified and were not used to
claim this change was reviewed. A real Ubuntu Desktop installation and the
pinned Qwen model remain necessary before acceptance.

## Hosted Ubuntu real-model installer smoke (2026-11-04)

GitHub Actions [run 41925821283](https://github.com/Asandhu402/BabyMind/actions/runs/41925821283)
completed successfully for commit `655c95379aa94b531b8d8c406f67e5c400dd02cc` on
a fresh GitHub-hosted Ubuntu 22.04 VM. After installing Xvfb, xauth and the Python
WebSocket test dependency, the job ran the actual `install-linux.sh` in a
disposable home: Ubuntu package installation, production-model download and
SHA-256 verification, local build, and installed executable checks all passed.
The installed Qt app then started under Xvfb with its default WebEngine sandbox,
loaded the pinned real model, and answered “What is 2 + 2? Answer with the
number only.” with `4`; this response is recorded in the check-run annotation.

This is a single real inference smoke test on a hosted server VM with a virtual
X display. It does not establish behavior on a fresh Ubuntu **Desktop** session,
quality across topics, all-role competence, coding, self-edit, offline restart,
or cancellation. A follow-up opt-in test has been prepared to test additional
questions, role calls and source-only self-edit; no result is claimed until it
runs. The GUI automation enables Qt remote debugging on loopback **only in the
disposable test VM**, not in the application defaults.

## Self-development recovery fix

A regression test reproduced a partial-write error: an edit changed an earlier
file, a later write failed, and the old code claimed rollback without actually
restoring the first file. The transaction now backs up edited existing files
before writing, refuses an edit if the checkpoint could not contain its target,
restores successfully written targets on write or verification exceptions,
removes its newly created files, and reports a rollback failure instead of
claiming success. Automatic rollback is limited to the edited paths so it does
not undo unrelated concurrent edits. It also refuses to overwrite an edited
path that has changed again since the transaction wrote it, reporting that
manual recovery may be needed. New targets are published without overwriting
paths that appeared after preview. These checks do not eliminate all same-user
races, resource failures, or the need for independent backups.

The Ubuntu Base source-suite retest ran **328 tests, OK, 17 skipped**, using the
same augmented, network-isolated environment and fixtures noted above. The
real-model acceptance harness was also exercised on the Debian host with the
modified small story model: it correctly reported wrong chat answers, failed
coding tests and no valid self-edit, while recording all 50 role outputs.
Generated code was executed only after the namespace sandbox's four probes
passed, inside a disposable project. Those results are not production-model
results. The 50 specialist contributions requested for development work were
not independently verified for this fix.

After the follow-up check for changes made to an edited path during verification,
26 self-development tests passed in the isolated Ubuntu Base environment. The
Debian source suite then ran **330 tests, OK, 2 skipped**. These are not a new
hosted production-model result.

## Hosted production-model role and coding follow-up

[Run 41926959221](https://github.com/Asandhu402/BabyMind/actions/runs/41926959221)
on commit `a0a83fb1dfd21648cb4b07352e8fc1a9ac477a1d` passed the actual
installer and installed GUI arithmetic test again. Source-mode production-model
chat returned `4`, `Blue`, and a relevant one-sentence explanation of backups.
The coding response was `def add(a, b): return a + b` (formatted as a Python
code block). A sandboxed disposable source-fixture edit was recorded as applied,
and its baseline test passed. The report with independent behavioral test results
was uploaded as an artifact, but this environment could not download it because
GitHub's artifact storage host is inaccessible; do not assume those additional
tests passed from the annotation alone. The edited fixture is not the packaged
desktop or the real BabyMind core.

The run **failed overall**: its 50-role mission recorded nonempty output from 38
roles and deferred 12 after the 2,400-second time budget. Several role outputs
asserted implementation actions even though role passes had no tools and did
not perform those actions. The prompt has since been clarified to say that
roles can only propose work and prior text is unverified; this is an instruction,
not a guarantee against false claims. The next opt-in test was configured with
a 4,200-second mission budget and shorter responses, but it has not yet run.
The actual desktop default remains bounded and may also defer roles. All-role
competence and packaged self-upgrade remain unverified or unavailable.

## Follow-up acceptance-harness safeguards

A local harness audit found that a sandbox-probe exception previously stopped
all remaining role checks, and that an exception during the coding test could
leave generated fixture files in place for the later self-edit test. The harness
now treats probe exceptions as a failed sandbox check, does not execute generated
code without a verified sandbox, continues the read-only role checks, and
removes the coding fixture in a `finally` block. It also checks that the results
cover all distinct registered role IDs, not merely a count of 50. Mocked
regression tests cover these cases; they do not constitute a production-model
or Ubuntu Desktop test. The expanded 4,200-second hosted real-model test remains
unrun as of this update.

A subsequent source audit found three safety gaps. A partial mission could start
a self-edit, the self-edit verifier could accept an empty or interrupted test
run, and a Python environment under `/tmp` was exposed as a writable sandbox
bind. The source changes now skip mission self-edit when roles are incomplete
or cancelled, compare a fresh pre-edit test run against the post-edit run,
require the sandbox by default for self-development, and mount temporary
interpreter prefixes read-only. They also reject symbolic-link path components
before resolution and refuse requests to bypass test verification via the HTTP
apply endpoint. The sandbox self-test now probes an actual existing file outside
the workspace and compares network namespace identities instead of checking a
rewritten HOME path. Regression tests exercise the mount and namespace probes
on the local Debian host and the other guards using fixtures; this is not a
clean Ubuntu Desktop or a production-model result. Test counts cannot prove
unchanged test semantics, and code under test still has write access to the
designated project root. A later local follow-up also compares reported test
failure identities (so a new failure cannot replace a known one unnoticed),
uses unique sandbox-probe files, and requires the requested short arithmetic
and color answers rather than merely searching for expected words.

On the local Debian host, the revised verifier also copied the actual BabyMind
source into a disposable directory, passed the Linux namespace probes, and ran
a 50-role mission with a **fake provider**. The fake provider proposed a small
change to the copied `src/babymind/__init__.py`; the self-edit transaction
applied it after the copied project's suite passed (352 tests, 18 skipped), and
an independent sandboxed behavior test passed with the suite (354 tests, 18
skipped). This validates the integration and isolation path only: it is not
proof of real-model quality, useful specialist work, or packaged self-upgrade.
The revised opt-in hosted harness additionally attempts that real-source-copy
scenario with the production model; its result must be reported separately.

The local Debian source-suite follow-up ran **355 tests, OK, 2 skipped** after
these later changes. Its sandbox and model-verifier regression tests do not
substitute for the ongoing hosted production-model runs.
