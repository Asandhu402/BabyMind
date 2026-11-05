# BabyMind Linux portable desktop

The supported desktop target is 64-bit x86 Linux with glibc 2.35 or newer (for
example Ubuntu 22.04 or later), a graphical X11/Wayland desktop, and standard
Qt WebEngine system libraries (NSS, XCB, xkbcommon, OpenGL/Mesa, ALSA). This is
not an AppImage and is not guaranteed to run on every Linux distribution.

For Ubuntu 22.04+ x86-64, the repository includes `install-linux.sh`; the
single-command bootstrap is in the main README. The installer uses sudo for
system packages, builds in a temporary per-user cache, downloads and verifies
the pinned model, and creates a per-user application-menu entry. Reinstalling
retains prior application versions and never deletes the model or user data.
It installs the default model in `~/.babymind`; keep sufficient disk space for
Ubuntu packages, build tools, the model, and previous versions. Installing
requires network access to Ubuntu, GitHub, PyPI and Hugging Face. Python
packages are not hash-locked. Full clean-host installation is unverified.

Alternatively, extract the **complete** release archive and double-click `BabyMind`, or run
`./BabyMind` from a terminal. Keep the `_internal` and `llama.cpp` directories
beside it. The first launch asks before downloading the pinned model (about
2.71 GB; at least 4.5 GB free). Internet access to Hugging Face is required for
that download; the SHA-256 is verified before use. Later launches work without
the download. Model loading can take several minutes and needs substantial RAM;
CPU inference can be slow. Your data and model are stored in `~/.babymind`, not
in the application folder. Deleting the application does not delete your data.

To build from source, install Python 3.10+, venv/pip, a C++ compiler, CMake,
curl and tar, then run `./build-linux.sh`. The build downloads Python packages
and checksum-verifies the pinned llama.cpp source. It builds a generic x86-64
CPU runtime and packages Qt and Python with PyInstaller. Use a glibc 2.35 build
host for compatibility with Ubuntu 22.04; newer build hosts may produce binaries
that require newer glibc. The archive and build dependencies are not vendored.
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
redistribution. This app downloads the model rather than redistributing it. The BabyMind repository has no top-level license file; do not assume permission to redistribute it.
