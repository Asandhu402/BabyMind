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

Before calling this plug-and-play: build on a supported clean desktop Linux
host with a matching shared Python, review project/Qt/model redistribution
terms, run the packaged GUI and real first download and inference, test offline
restart and cancellation, and validate namespace/safety behavior and recovery
on target hardware. Check CPU/RAM requirements and portability on the actual
supported distributions. The CI Qt test serves real application assets with fixture APIs and the
headless package check does not load a model; neither substitutes for those
acceptance tests.
