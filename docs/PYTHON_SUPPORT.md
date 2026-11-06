# Python support

## Supported interpreters

| Python | Status | Notes |
| --- | --- | --- |
| 3.15 | **Current stable** (released 2026-10-09) | Built and tested in CI on Ubuntu 26.10. `cognee` has no 3.15 wheels yet, so the `knowledge-graph` extra is skipped. |
| 3.14 | Supported | Built and tested in CI on Ubuntu 26.10. Default `python3` on Ubuntu 26.10 (3.14.7). |
| 3.13 | **Minimum** | Built and tested in CI on Ubuntu 26.10. Debian 13 ships 3.13; on Ubuntu 24.04 install `python3.13` first. |
| 3.12 and older | Not supported | Python 3.10 reached end of life on 2026-10-01; 3.11/3.12 are not tested. |

`pyproject.toml` declares `requires-python = ">=3.13"`. Interpreter code,
`BabyMind` diagnostics and both Linux installers enforce the same minimum
(`babymind.MINIMUM_PYTHON`), so an unsupported interpreter fails early with an
explanatory message instead of a confusing dependency error.

## Pinned dependency set

| Package | Version | Why |
| --- | --- | --- |
| PySide6 | `>=6.12,<6.13` | Qt 6.12 is the current release and the first line that publishes `cp310-abi3` wheels usable on 3.13-3.15. Wheels need glibc 2.34 or newer on x86-64. |
| cryptography | `>=50.0.0,<51` | Unchanged; supports 3.15. |
| pyinstaller (`build` extra) | `>=6.22,<7` | Supports `requires-python <3.16`. |
| browser-use (`browser` extra) | `>=0.13` | Python 3.11+; the previous `python_version >= '3.11'` marker is no longer needed. |
| cognee (`knowledge-graph` extra) | `>=0.5.0` with `python_version < '3.15'` | Cognee currently declares `<3.15`. Keeping the marker means `.[all-integrations]` still installs on 3.15 instead of failing. |

## Platform consequences

* **glibc:** the portable archive produced by CI is built on Ubuntu 26.10 and
  therefore needs glibc 2.43 or newer (Ubuntu 26.04+). Qt 6.12 itself needs
  glibc 2.34 or newer, so Ubuntu 22.04 and 24.04 users cannot run it even with
  a newer Python; Debian 13 ships glibc 2.41, below the floor, so the portable
  archive targets glibc 2.43+ only. Source builds are unaffected.
* **Distributions whose default Python is below the floor** (Ubuntu 24.04 ships
  3.12): `bootstrap-linux.sh` searches for an installed `python3.15`,
  `python3.14` or `python3.13` (each one must also provide a shared libpython
  and `venv`), then tries that distribution's package, then builds the newest
  CPython release from python.org source into `~/.cache/babymind/python`.
  `install-linux.sh` alone only uses what is already installed and stops with a
  message naming the package to install.
* **Debian-based distributions that ship 3.13-3.15** (Debian 13 ships 3.13;
  Ubuntu 26.04 ships 3.14; Ubuntu 26.10 ships 3.14.7) need no extra Python step; the bootstrap reuses the
  installed interpreter.
* **Non-Debian distributions are rejected:** BabyMind's installers require a
  Debian-based distribution and APT. x86-64 is the only supported architecture.
* **Packaged app:** the portable build bundles its own interpreter, so end users
  of the release archive do not need Python installed at all.

## Verification

`.github/workflows/tests.yml` runs the full build, unit suite, llama.cpp
fixture and packaged-app checks on Ubuntu 26.10 for Python 3.13, 3.14 and 3.15,
and a source-only suite on Ubuntu 26.10 with Python 3.15 (build/test jobs; the
`bootstrap-plan` job needs a too-old distribution and runs on Ubuntu 24.04,
which ships Python 3.12).
`.github/workflows/release.yml` builds release artefacts with Python 3.15 on
Ubuntu 26.10.

## Upgrading again

1. Check `requires-python` support for every dependency (`python -m pip index
   versions` or the project metadata on PyPI).
2. Raise `requires-python`, `MINIMUM_PYTHON` in `src/babymind/__init__.py`, the
   CI matrix, `bootstrap-linux.sh` (`MIN_MINOR`/`MAX_MINOR`),
   `install-linux.sh`/`install-and-run-linux.sh` guards and this document
   together.
3. Rebuild the Linux package on the Ubuntu release matching the intended
   glibc floor. The package is currently built and tested on Ubuntu 26.10,
   which sets the floor at glibc 2.43; building on the oldest Ubuntu release
   you intend to support instead would lower the floor at the cost of an
   older toolchain.
