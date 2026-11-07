# Tuning the local model

Written 2026-11-06. This page documents every supported dial for BabyMind's
local 4B model and what each one honestly buys you. It does not raise the
reasoning ceiling of the pinned model — nothing shipped does that.

## What is fixed (not tunable)

- **Engine:** `llama.cpp` only. There is no supported switch to another
  inference engine or to a hosted/API model; `BABYMIND_ENGINE` rejects anything
  else at startup.
- **Model:** `Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf`,
  SHA-256 pinned. The file's contents are verified on **every** launch, not
  just at download, and a mismatch is refused (the file is never deleted).
  `BABYMIND_GGUF_MODEL` may *relocate* the pinned file; it cannot substitute
  a different model.
- **Serving:** one inference slot (`--parallel 1`), loopback only, and hidden
  thinking/reasoning disabled for the Qwen chat template.

## Supported dials

All of these are environment variables, read at launch (context) or per
request (decoding). Invalid values now fail with a clear error naming the
variable instead of a silent mis-launch.

| Dial | Variable | Default | Accepted range | Honest effect |
| --- | --- | --- | --- | --- |
| Context window | `BABYMIND_CONTEXT_SIZE` | `4096` | whole number, `512`–`131072` | Room for longer inputs and answers. KV-cache memory grows with context; 8192 wants roughly 16 GB RAM. Does **not** improve reasoning quality. |
| Temperature | `BABYMIND_TEMPERATURE` | `0.4` | `0.0`–`2.0` | Lower = steadier, more exact answers (code, facts, arithmetic). Higher = more varied phrasing. `0.0` is the most deterministic. |
| Top-p | `BABYMIND_TOP_P` | `0.9` | `> 0.0`, `≤ 1.0` | Truncates the sampling tail. Rarely needs changing; lowering it also increases determinism. |
| Max tokens | `BABYMIND_MAX_TOKENS` | `2048` | `1`–`32768` | Length cap per reply. Raise it for long-form work; the 4B model does not gain quality from a bigger cap, only more room. |
| Port | `BABYMIND_LLAMA_PORT` | `1235` | `1`–`65535` | Only needed if 1235 is taken. BabyMind refuses an occupied port rather than adopt an unverified server. |

## Practical presets

These are starting points for a **16 GB+ machine**:

```sh
# Precision work (code, exact answers)
export BABYMIND_TEMPERATURE=0.2 BABYMIND_CONTEXT_SIZE=8192

# Long-form drafting
export BABYMIND_MAX_TOKENS=4096 BABYMIND_CONTEXT_SIZE=8192
```

On an 8 GB machine, leave the defaults alone — 4096 context is the safe floor.

## The other two "power" levers (no env vars involved)

- **Grounding beats 4B memory.** The built-in web research and GitHub research
  panels let BabyMind *look up* current or obscure facts instead of recalling
  them. For anything time-sensitive or niche, use them — this is the single
  biggest real-world lift available to a 4B model.
- **Roles and mission mode (since removed) changed framing, not capability.** All 50 roles were
  prompts over the same model. A mission gives you structured, multi-step
  output and an audit trail; it does not make the model reason better.
- **Opt-in memory** makes BabyMind personal over time, at the same per-answer
  quality.
- **Self-edit** (`POST /api/dev/repair`, or a mission with "Also apply one
  verified self-edit") patches BabyMind's *own* source behind checkpoint →
  compile → test → keep/rollback, verified only by BabyMind's own test suite.
  See [autonomy](AUTONOMY.md).

## What would require a fork (not supported here)

Loading a larger GGUF (8B/14B/32B) means changing the SHA-256 pin and rebuilding
the package, then re-verifying everything the pinned build claims. Adding a
remote engine means forking `providers.py` and giving up the local-first
privacy guarantee. Neither has been built or verified. The supported
configuration on the release target remains the pinned 4B on hosted
Ubuntu 26.04 LTS CI.
