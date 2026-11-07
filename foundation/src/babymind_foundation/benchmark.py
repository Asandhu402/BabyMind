"""Measure local CPU training throughput using synthetic token IDs only."""
from __future__ import annotations

import argparse
import time

import torch

from .model import BabyMindGPT, ModelConfig, count_parameters


def run_benchmark(
    steps: int = 20,
    batch_size: int = 2,
    sequence_length: int = 64,
    threads: int | None = None,
) -> dict[str, float | int | str]:
    if steps < 1 or batch_size < 1 or sequence_length < 2:
        raise ValueError("steps/batch-size must be positive and sequence-length >= 2")
    if threads is not None:
        if threads < 1:
            raise ValueError("threads must be positive")
        torch.set_num_threads(threads)

    device = torch.device("cpu")
    config = ModelConfig(
        vocab_size=512, block_size=sequence_length, n_layer=2, n_head=4,
        n_embd=128, dropout=0.0,
    )
    model = BabyMindGPT(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
    inputs = torch.randint(0, config.vocab_size, (batch_size, sequence_length))
    targets = torch.randint(0, config.vocab_size, (batch_size, sequence_length))

    model.train()
    start = time.perf_counter()
    loss_value = 0.0
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        _, loss = model(inputs, targets)
        assert loss is not None
        loss.backward()
        optimizer.step()
        loss_value = float(loss.detach())
    elapsed = time.perf_counter() - start
    tokens = steps * batch_size * sequence_length
    return {
        "device": "cpu",
        "parameters": count_parameters(model),
        "steps": steps,
        "tokens": tokens,
        "elapsed_seconds": round(elapsed, 3),
        "tokens_per_second": round(tokens / elapsed, 2),
        "last_loss": round(loss_value, 5),
        "torch_threads": torch.get_num_threads(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--sequence-length", type=int, default=64)
    parser.add_argument("--threads", type=int, default=None)
    args = parser.parse_args()
    result = run_benchmark(
        steps=args.steps, batch_size=args.batch_size,
        sequence_length=args.sequence_length, threads=args.threads,
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
