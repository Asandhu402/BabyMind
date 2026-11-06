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
| PySide6 | `>=6.12,<6.13` | Qt 6.12 is the current release and the first line that publishes `cp310-abi3` wheels usable on 3.13-3.15. Wheels need glibc 2.34 or newer on x86-64. |
| cryptography | `>=50.0.0,<51` | Unchanged; supports 3.15. |
| pyinstaller (`build` extra) | `>=6.22,<7` | Supports `requires-python <3.16`. |
| browser-use (`browser` extra) | `>=0.13` | Python 3.11+; the previous `python_version >= '3.11'` marker is no longer needed. |
| cognee (`knowledge-graph` extra) | `>=0.5.0` with `python_version < '3.15'` | Cognee currently declares `<3.15`. Keeping the marker means `.[all-integrations]` still installs on 3.15 instead of failing. |

## Platform consequences

* **glibc:** the portable archive produced by CI is built on Ubuntu 24.04 and
  therefore needs glibc 2.39 or newer (Ubuntu 24.04+). Qt 6.12 itself needs
  glibc 2.34 or newer, so Ubuntu 22.04 users cannot run it even with a newer
  Python.
* **Ubuntu 24.04:** ships Python 3.12. `install-linux.sh` looks for
  `/usr/bin/python3.15`, `python3.14`, `python3.13` before falling back to
  `python3`, and tells you to install `python3.13` (plus its `-venv`/`-dev`
  packages) when none is new enough.
* **Ubuntu 26.04 and newer:** ships Python 3.14, so the one-command installer
  works without extra packages.
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
   CI matrix, `install-linux.sh`/`install-and-run-linux.sh` guards and this
   document together.
3. Rebuild the Linux package on the oldest Ubuntu release you intend to support
   so the artefact's glibc floor stays as low as possible.
