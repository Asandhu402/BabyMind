# BabyMind Linux portable desktop

The supported desktop target is 64-bit x86 Linux with glibc 2.35 or newer (for
example Ubuntu 22.04 or later), a graphical X11/Wayland desktop, and standard
Qt WebEngine system libraries (NSS, XCB, xkbcommon, OpenGL/Mesa, ALSA). This is
not an AppImage and is not guaranteed to run on every Linux distribution.

Extract the **complete** release archive and double-click `BabyMind`, or run
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

The desktop defaults to `BABYMIND_SANDBOX=require`, which refuses command
execution because the frozen app cannot run the Python-based namespace launcher. Use a source checkout to access that backend, and do not override this for untrusted code. The portable build cannot run source-checkout self-development
tests or generated Python applications with its frozen executable; use a source
checkout and a real Python interpreter for that; portable self-development edits are disabled. Review and mission results
are model-generated and are not proof of independent work or security. On Linux
local encryption keys are files readable by your user account, not a hardware
keystore. See SECURITY.md and docs/KNOWN_LIMITATIONS.md in the source tree.

llama.cpp is MIT licensed; a copy is in licenses/. PySide6/Qt are LGPL/GPL
components; consult their upstream license terms before redistributing. The
model's terms must be reviewed on its Hugging Face model page before use or
redistribution. This app downloads the model rather than redistributing it. The BabyMind repository has no top-level license file; do not assume permission to redistribute it.
