# BabyMind-100M

BabyMind-100M is an independent, from-scratch language-model research project.
It is separate from BabyMind's desktop application's bundled inference model.

## Non-negotiable rules

- Initialize every model parameter randomly. Never load pretrained weights.
- Do not distill from, fine-tune, or silently import weights from another model.
- Build and train our tokenizer from permitted project data.
- Record dataset sources, licenses, transformations, exclusions, and hashes.
- Keep benchmark/evaluation data separate from training data.
- Compare architectural ideas against a standard decoder-only Transformer using
  the same data, token budget, optimizer, and compute budget.
- Treat capability, safety, and consciousness claims as hypotheses to test;
  generated self-descriptions are not evidence of subjective experience.

## Languages and domains

The intended corpus covers English, Hindi, Sanskrit, programming languages,
mathematics, and carefully sourced scientific material. Actual proportions
will be chosen only after corpus audits; no language should be represented by
unverified or rights-unclear data.

## Staged plan

1. **CPU feasibility test:** train a tiny randomly initialized model on a
   generated toy corpus and measure tokens/second on the target laptop.
2. **Tokenizer:** train an original Unicode-aware tokenizer on permitted
   English, Hindi, Sanskrit, code, and math text. Validate round trips and
   per-language coverage.
3. **Baseline:** establish a reproducible decoder-only Transformer.
4. **Architecture experiments:** implement proposed BabyMind variants behind
   explicit config flags and compare them to the baseline under matched budgets.
5. **Scale-up gate:** estimate wall-clock time and memory from measured
   throughput before attempting the 100M configuration.
6. **Pretraining and evaluation:** use versioned, licensed data; checkpoint
   frequently; report held-out results and limitations.

## First run

Use a dedicated virtual environment. Install the CPU PyTorch build appropriate
for your Linux/Python combination, then install this project:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m babymind_foundation.benchmark --steps 20 --batch-size 2 --sequence-length 64
```

The benchmark uses random token IDs only. It does not download data, contact
model hubs, or load any pretrained checkpoint. Its result is a hardware
measurement, not a model-quality score.

## Current status

This first commit establishes the project boundary, a plain Transformer
baseline, and a CPU benchmark. It does **not** yet claim a trained tokenizer,
a completed 100M model, or useful language competence.
