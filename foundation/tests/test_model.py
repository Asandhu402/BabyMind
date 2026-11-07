import pytest
import torch

from babymind_foundation.model import BabyMindGPT, ModelConfig, count_parameters


def test_forward_and_loss() -> None:
    config = ModelConfig(vocab_size=64, block_size=16, n_layer=2, n_head=2, n_embd=32)
    model = BabyMindGPT(config)
    tokens = torch.randint(0, 64, (2, 12))
    logits, loss = model(tokens, tokens)
    assert logits.shape == (2, 12, 64)
    assert loss is not None and torch.isfinite(loss)


def test_backward_updates_randomly_initialized_weights() -> None:
    model = BabyMindGPT(ModelConfig(vocab_size=32, block_size=8, n_layer=1, n_head=2, n_embd=16))
    before = model.token_embedding.weight.detach().clone()
    tokens = torch.randint(0, 32, (2, 8))
    _, loss = model(tokens, tokens)
    assert loss is not None
    loss.backward()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    optimizer.step()
    assert not torch.equal(before, model.token_embedding.weight.detach())


def test_invalid_head_dimensions_rejected() -> None:
    with pytest.raises(ValueError):
        ModelConfig(n_embd=30, n_head=4)


def test_parameter_counter_positive() -> None:
    model = BabyMindGPT(ModelConfig(vocab_size=32, n_layer=1, n_head=2, n_embd=16))
    assert count_parameters(model) > 0
