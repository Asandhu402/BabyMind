# BabyMind quality and security checks

Promptfoo is a local-only evaluation harness; it is not part of the runtime app
and does not add another model or agent. The included provider calls BabyMind's
loopback /api/chat endpoint and refuses non-loopback targets. The smoke tests
use deterministic string assertions and do not require a hosted grader.

## Run

1. Start BabyMind and wait for its local llama.cpp model to become ready.
2. Install Node.js 22.22+ and Promptfoo (npm install -g promptfoo), or use npx.
3. From the repository root:

   ```bash
   export PROMPTFOO_DISABLE_TELEMETRY=1
   export BABYMIND_EVAL_URL=http://127.0.0.1:8765
   npx promptfoo eval -c quality/promptfooconfig.yaml
   ```

The evaluation makes requests only to the local BabyMind server. Do not add
hosted graders or hosted attack-generation providers to this configuration.
Promptfoo red-team generation can use a remote model by default; it is not
enabled by this smoke suite. Use local attack providers only if you later add
red-team tests.
