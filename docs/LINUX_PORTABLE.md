# BabyMind Linux portable desktop

The supported desktop target is Debian-based Linux on 64-bit x86 (AMD64), with glibc 2.43 or newer (for
example Ubuntu 26.04+; Debian 13 ships glibc 2.41 and is below the floor for the portable archive, though
source builds work there), a graphical X11/Wayland desktop, and standard
Qt WebEngine system libraries (NSS, XCB, xkbcommon, OpenGL/Mesa, ALSA). This is
not an AppImage and is not guaranteed to run on every Linux distribution.

On Debian-based x86-64 Linux, the main README has one self-provisioning command. It runs
`bootstrap-linux.sh`, which uses APT to install any missing tool, and selects the newest supported Python (an existing 3.13-3.15
interpreter, a distribution package, or the newest CPython release built from
python.org source into `~/.cache/babymind/python`). It then runs
`install-linux.sh`, which uses sudo for your distribution's Qt/WebEngine
libraries, builds in a temporary per-user directory, downloads and verifies the
pinned model, and creates a per-user application-menu entry. The documented
one-liner ends with `BABYMIND_LAUNCH_AFTER_INSTALL=1`, so it also starts
BabyMind; use `=0` to install without starting it. Reinstalling
retains prior application versions and never deletes the model or user data.
It installs the default model in `~/.babymind`; keep sufficient disk space for
distribution packages, build tools, the model, and previous versions.
Installing requires network access to your distribution's mirrors, python.org,
GitHub, PyPI and Hugging Face (python.org is skipped when a suitable Python is
already installed). Python packages are not hash-locked. Bootstrap preparation and the APT installation path are exercised in CI configured for Ubuntu 26.10 (a self-hosted runner is required until GitHub publishes a hosted `ubuntu-26.10` label; see [testing on Ubuntu 26.10](UBUNTU_26_10_TESTING.md)). Debian and Ubuntu derivatives are the only supported distribution family.

Alternatively, extract the **complete** release archive and double-click `BabyMind`, or run
`./BabyMind` from a terminal. Keep the `_internal` and `llama.cpp` directories
beside it. The first launch asks before downloading the pinned model (about
2.71 GB; at least 4.5 GB free). Internet access to Hugging Face is required for
that download; the SHA-256 is verified before use. Later launches work without
the download. Model loading can take several minutes and needs substantial RAM;
CPU inference can be slow. Your data and model are stored in `~/.babymind`, not
in the application folder. Deleting the application does not delete your data.

To build from source, install Python 3.13+ (tested on 3.13, 3.14 and 3.15),
venv/pip, a C++ compiler, CMake, curl and tar, then run `./build-linux.sh`. The build downloads Python packages
and checksum-verifies the pinned llama.cpp source. It builds a generic x86-64
CPU runtime and packages Qt 6.12 and Python with PyInstaller. The release is built and tested on Ubuntu 26.10,
which sets the artifact's glibc floor at 2.43 (Ubuntu 26.04+); building on an older host would lower that floor
at the cost of an older toolchain. The archive and build dependencies are not vendored.
The first model download has not been verified in restricted/offline networks. See docs/LINUX_VERIFICATION.md in the source tree for the actual test status.

The portable build includes a Python helper and bundled source seed. It can stage
source edits under `~/.babymind/development-source`, with checkpointing and tests
in a required Linux namespace sandbox. **Staged changes do not rebuild, replace,
or update the running packaged application.** The sandbox must be available and
its boundary probes must pass; there is no unsandboxed fallback for packaged
self-edits. A workspace from a different package version is left untouched.
Generated Python application execution remains unavailable in the frozen app.
Review and mission results are model-generated and are not proof of independent
work or security. On Linux
local encryption keys are files readable by your user account, not a hardware
keystore. See SECURITY.md and docs/KNOWN_LIMITATIONS.md in the source tree.

llama.cpp is MIT licensed; a copy is in licenses/. PySide6/Qt are LGPL/GPL
components; consult their upstream license terms before redistributing. The
model's terms must be reviewed on its Hugging Face model page before use or
redistribution. This app downloads the model rather than redistributing it. The BabyMind repository itself is MIT licensed (see the top-level LICENSE and NOTICE files); bundled and referenced third-party components keep their own upstream license terms.
