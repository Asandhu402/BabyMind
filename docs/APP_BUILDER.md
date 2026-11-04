# Local app builder

**Status: implemented and opt-in (disabled by default).** BabyMind can turn a short brief into a
small app, and write the files into one dedicated folder. In source mode it can run the Python entry point once; the portable app cannot run it. It uses the same local llama.cpp model as chat — no cloud model, no
extra account.

This is the only path in BabyMind that creates files and runs generated code. It is deliberately
narrow, and the rest of the workspace gates stay closed (see
`workspace_readiness()`).

## Enable it

Set two environment variables, then restart BabyMind:

```bash
export BABYMIND_APP_BUILDER_ENABLED=true
export BABYMIND_BUILDER_ROOT="$HOME/BabyMindApps"
```

`BABYMIND_BUILDER_ROOT` (or `BABYMIND_WORKSPACE_ROOT`) must already exist. Generated apps are
created under `<root>/apps/<app-slug>/`. Without both settings the builder reports `disabled` and
every builder endpoint refuses the request.

## How a build works

1. **Plan.** You describe the app. BabyMind asks its own local model for a JSON plan: a name, an
   entry point, and a list of text files. Nothing is written at this stage.
2. **Review.** The UI shows every path, its size, a preview, and a SHA-256 hash of the exact plan.
3. **Approve.** You approve *that hash*. In the API this is `POST /api/builder/build` with
   `{"plan_id": ..., "plan_hash": ...}`.
4. **Write + run.** BabyMind creates `<root>/apps/<slug>/`, writes each file with `O_EXCL` (an
   existing file is never overwritten), then, only in source mode, runs the entry point once:
   `<python interpreter> -u <entry>` in the app folder, no shell, scrubbed environment, 60-second
   limit, output captured and shown.

Plans are held in memory only, are single-use, and expire after 30 minutes. A plan that changed
after you reviewed it is rejected: the hash is recomputed from the file contents before anything
is written.

## Hard limits

| Limit | Value |
| --- | --- |
| Files per app | 40 |
| Bytes per file | 64 KB |
| Total plan size | 512 KB |
| Run timeout | 60 seconds |
| Plan lifetime | 30 minutes, single use |
| Allowed extensions | `.py .txt .md .json .csv .html .css .js .toml .ini .cfg .yaml .yml .svg` |
| Command execution | Python entry point only; never a shell |
| Write scope | `<root>/apps/<slug>/` |

Refused outright: absolute paths, drive letters (`C:...`), `..`, hidden files, symlinks, duplicate
paths, a non-`.py` entry point, and reusing an app name that already exists.

## What this is not

- **The app builder is not sandboxed.** In source mode it executes generated
  Python directly as your user, regardless of namespace availability. It can
  read private files or use the network. Do not execute untrusted generated code.
  In the portable app generated-code execution is disabled.
- **Not a full sandbox against a hostile model.** Generated code runs with your user account's privileges when no backend exists. It can read what you
  can read and use the network. The containment is the folder, the approval, and the review — not
  an operating-system boundary.
- **Not a shell.** There is no way to run a shell or an arbitrary program through
  this feature. Only the reviewed `.py` entry point runs.
- **Not an approval bypass.** The existing workspace file broker (`approval.py`) stays disabled;
  this is a separate, narrower capability with its own gate.
- **Not a guarantee the app is good.** A local 4B-class model writes the code. Read it before you
  run it again, and treat every generated file as untrusted.

## Prompt-injection note

If you paste third-party text, or leave web research on in the same session, that text is untrusted
data and may try to influence the plan. The defence is structural: you see the exact file list and
hash before anything is written, and the model cannot write outside the apps folder or run a shell.
Read the file list before approving. If a plan looks unrelated to your brief, discard it.

## Removing an app

Delete the app folder under `<root>/apps/`. BabyMind does not track or clean up generated apps, and
it never deletes them for you.
