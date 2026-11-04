# Test report

Recorded after the autonomous-development implementation on branch
`arena/d4fae001-babymind`.

## Environment actually used

| Item | Value |
| --- | --- |
| OS | Linux container (Debian, `Linux ... x86_64`) |
| Python | 3.11.2 |
| Virtualenv | isolated venv with `cryptography` installed |
| Command | `PYTHONPATH=src python -m unittest discover -s tests` |
| Model server | none (tests use stub providers; no GGUF was loaded) |
| GPU | none detected |
| Windows | **not tested in this report** |

## Result

```
Ran 237 tests in 40.155s

FAILED (errors=1)
```

**236 passed. 1 error, and it is environmental:**

```
ERROR: test_existing_model_is_rehashed_even_when_marker_matches
  (test_first_run.FirstRunSetupTests...)
ModuleNotFoundError: No module named 'tkinter'
```

`first_run._ensure_model` imports `tkinter` to show first-run progress. This
container's Python is built without Tk. Windows Python and the portable build
ship Tk, where the same test is expected to pass — but that has not been
executed here, so it is reported as an error, not as passing.

## Tests by module

| Module | Tests | Covers |
| --- | ---: | --- |
| `test_agents` | 8 | Registry completeness, unique IDs/names, playbooks |
| `test_orchestrator` | 16 | All 50 roles recorded, phase order, provider failure, empty output, cancellation, stats |
| `test_selfdev` | 15 | Checkpoints, apply, verify, auto-rollback, baseline handling, rollback, traversal, permissions, audit tamper detection |
| `test_runner` | 8 | Allowlist, timeout, output cap, cwd boundary, env scrubbing, isolation honesty |
| `test_mission_api` | 10 | Mission endpoints, role catalogue, activity, dev endpoints, Host rejection |
| `test_hardware` | 4 | Report shape, tiering, unknown-memory fallback, thread sizing |
| `test_research` | 16 | Existing SSRF guards + GitHub metadata and licence policy (mocked) |
| `test_builder` / `test_builder_api` | 25 | App builder (previous phase) |
| `test_server` / `test_server_lan_bind` | 50 | Existing HTTP, backup, tasks, approvals, LAN bind |
| others | 86 | Coordinator, providers, memory, integrations, diagnostics, backup, TLS |

## Live acceptance exercise (not a unit test)

Executed against this repository with the real self-development engine
(`verify=True`, full suite each time):

| Step | Result |
| --- | --- |
| Read own source (`src/babymind/orchestrator.py`) | 19,239 bytes returned |
| Create `src/babymind/_acceptance_probe.py` | `applied`, suite baseline 1 problem |
| Modify the same file | `applied` |
| Deliberately break `tests/test_agents.py` | `rolled_back`, reason `test suite regressed: 2 problems (baseline 1)` |
| File restored byte-for-byte after that rollback | yes |
| Roll back the pre-create checkpoint | probe file removed |
| Audit chain integrity | `{"valid": true, "entries": 8}` |
| Leftover files after exercise | none (`git status` showed only intended edits) |

The earlier iteration of this exercise exposed two real defects, both fixed:

1. A SQLite connection leak in `MissionStore` (`OSError: Too many open files`
   after ~50 missions in one process).
2. Stale-bytecode verification: a same-size edit within one second was verified
   against the previous `.pyc`. The engine now purges bytecode before compile and
   test runs, and the test runner sets `PYTHONDONTWRITEBYTECODE=1`.

## OS sandbox

`sandbox.self_test()` on this machine returned:

```json
{"verified": true, "backend": "linux-namespaces",
 "checks": {"network": "BLOCKED OSError", "host_secret": "BLOCKED",
            "system_write": "BLOCKED OSError", "workspace_write": "WRITABLE"}}
```

The full suite was executed **inside** the sandbox and outside it, with the same
result (`Ran 260 tests`, one environment error for the missing `tkinter`). The
sandbox is covered by thirteen tests: the self-test contract, blocked TCP, blocked
DNS, unreadable `~/.babymind/memory.key`, read-only `/usr`, writable workspace,
timeout enforcement, child reaping, `require`-mode refusal without a backend,
`auto`-mode fallback reporting `sandbox: "unavailable"`, and `off` mode.

### Real coding task executed by the engine

A genuine two-file change (`POST /api/dev/repair` in `server.py` plus its two
tests) was applied through `selfdev.apply_edits` on this checkout:

| Step | Result |
| --- | --- |
| Checkpoint | `20261104-185316-db131d` |
| Files written | `src/babymind/server.py`, `tests/test_mission_api.py` |
| Compile + full suite inside the sandbox | `259 ran, 0 failures, 1 error` (the known `tkinter` one) |
| Outcome | `applied` (`sandboxed: true`) |
| Audit chain after the change | intact |

The patch text was authored by the assistant, not by a model: there is no GGUF on
this machine. Everything the engine contributes — checkpointing, policy checks,
compilation, sandboxed verification, rollback, audit — ran for real.

The self-edit loop is covered by eight tests: accepted patch applied and
verified, failing patch rolled back, malformed model output changing nothing,
empty proposal, protected-path rejection, disabled-engine skip, and no loop
without the flag.

## Not executed

- Windows 10/11 runtime, DPAPI key handling, `taskkill /T`, portable packaging.
- A real llama.cpp server with a real GGUF model; all model calls in tests are
  stubs.
- Browser-driven UI interaction (HTML/JS were syntax-checked and served by the
  test server; no headless browser was available).
- Windows/macOS sandbox backends: none exist, so `require` mode is untested there.
- A model-authored patch: the repair loop is tested with scripted providers.
- Model download and SHA-256 verification against Hugging Face.
- C#/Java/Rust/Go/Android/iOS toolchains.

Anything in that list is unverified, not "working".
