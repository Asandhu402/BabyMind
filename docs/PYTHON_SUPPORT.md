# Python support

## Supported interpreters

| Python | Status | Notes |
| --- | --- | --- |
| 3.15 | **Current stable** (released 2026-10-09) | Built and tested in CI on Ubuntu 24.04, source-tested on Ubuntu 26.04. `cognee` has no 3.15 wheels yet, so the `knowledge-graph` extra is skipped. |
| 3.14 | Supported | Built and tested in CI on Ubuntu 24.04. Default `python3` on Ubuntu 26.04. |
| 3.13 | **Minimum** | Built and tested in CI on Ubuntu 24.04. Available as `python3.13` on Ubuntu 24.04. |
| 3.12 and older | Not supported | Python 3.10 reached end of life on 2026-10-01; 3.11/3.12 are not tested. |

`pyproject.toml` declares `requires-python = ">=3.13"`. Interpreter code,
`BabyMind` diagnostics and both Linux installers enforce the same minimum
(`babymind.MINIMUM_PYTHON`), so an unsupported interpreter fails early with an
explanatory message instead of a confusing dependency error.

## Pinned dependency set

| Package | Version | Why |
| --- | --- | --- |
| PySide6 | `>=6.8,<6.13` | A range rather than a single line, so pip picks the newest x86-64 wheel the host can actually load. 6.12 is the current release and publishes `manylinux_2_34`; 6.8 is the first line with `manylinux_2_28`, which is what lets glibc 2.28-2.33 hosts install at all. Both are `abi3` wheels usable on 3.13-3.15, and `desktop.py` only uses Qt 6 APIs present since 6.0. |
| cryptography | `>=50.0.0,<51` | Unchanged; supports 3.15. |
| pyinstaller (`build` extra) | `>=6.22,<7` | Supports `requires-python <3.16`. |
| browser-use (`browser` extra) | `>=0.13` | Python 3.11+; the previous `python_version >= '3.11'` marker is no longer needed. |
| cognee (`knowledge-graph` extra) | `>=0.5.0` with `python_version < '3.15'` | Cognee currently declares `<3.15`. Keeping the marker means `.[all-integrations]` still installs on 3.15 instead of failing. |

## Platform consequences

* **glibc:** two different floors apply, because they come from different
  artifacts. The portable archive built by CI inherits the glibc of its build
  host, Ubuntu 24.04, so it needs 2.39 or newer. The one-command installer
  builds on the user's machine and needs only what PySide6's wheel needs, which
  is glibc 2.28 on x86-64 (`manylinux_2_28`, published from PySide6 6.8). So
  Ubuntu 22.04 and Debian 11 users install with the one-command path and use the
  portable archive only on 24.04 or newer.
* **Distributions that ship an old Python** (Ubuntu 24.04 ships 3.12, Debian 13
  ships 3.13): `bootstrap-linux.sh` searches for an installed `python3.15`,
  `python3.14` or `python3.13` (each one must also provide a shared libpython
  and `venv`), then tries that distribution's package, then builds the newest
  CPython release from python.org source into `~/.cache/babymind/python`.
  `install-linux.sh` alone only uses what is already installed and stops with a
  message naming the package to install.
* **Distributions that ship 3.13-3.15** (Ubuntu 26.04 ships 3.14, Fedora and
  Arch ship current Python) need no extra Python step; the bootstrap reuses the
  installed interpreter.
* **Alpine/musl is rejected:** PySide6 publishes no musl wheels, so Qt cannot be
  installed there. The bootstrap stops on musl systems instead of half-installing.
* **Packaged app:** the portable build bundles its own interpreter, so end users
  of the release archive do not need Python installed at all.

## Verification

`.github/workflows/tests.yml` runs the full build, unit suite, llama.cpp
fixture and packaged-app checks on Ubuntu 24.04 for Python 3.13, 3.14 and 3.15,
and a source-only suite on Ubuntu 26.04 with Python 3.15.
`.github/workflows/release.yml` builds release artefacts with Python 3.15 on
Ubuntu 24.04.

## Upgrading again

1. Check `requires-python` support for every dependency (`python -m pip index
   versions` or the project metadata on PyPI).
2. Raise `requires-python`, `MINIMUM_PYTHON` in `src/babymind/__init__.py`, the
   CI matrix, `bootstrap-linux.sh` (`MIN_MINOR`/`MAX_MINOR`),
   `install-linux.sh`/`install-and-run-linux.sh` guards and this document
   together.
3. Rebuild the Linux package on the oldest Ubuntu release you intend to support
   so the artefact's glibc floor stays as low as possible.
