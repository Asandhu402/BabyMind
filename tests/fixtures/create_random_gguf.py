"""Generate a tiny, deterministic, *untrained* GGUF for integration tests.

Requires numpy, PyYAML and llama.cpp's gguf-py on PYTHONPATH. This fixture is
not BabyMind's model and its output has no meaningful language capability.
"""
import sys

import numpy as np
from gguf import GGUFWriter


def main(path: str) -> None:
    rng = np.random.default_rng(42)
    chars = list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,!? :;_-\n")
    tokens = ["<unk>", "<s>", "</s>", "▁"] + chars + [f"<0x{i:02X}>" for i in range(256)]
    writer = GGUFWriter(path, "llama")
    writer.add_name("BabyMind test-only random weights")
    writer.add_context_length(4096)
    writer.add_embedding_length(32)
    writer.add_feed_forward_length(64)
    writer.add_block_count(1)
    writer.add_head_count(4)
    writer.add_head_count_kv(4)
    writer.add_layer_norm_rms_eps(1e-5)
    writer.add_tokenizer_model("llama")
    writer.add_token_list(tokens)
    writer.add_token_scores([0.0] * len(tokens))
    writer.add_token_types([2, 3, 3] + [1] * (1 + len(chars)) + [6] * 256)
    writer.add_bos_token_id(1)
    writer.add_eos_token_id(2)
    writer.add_unk_token_id(0)
    writer.add_add_bos_token(True)
    writer.add_chat_template(
        "{% for message in messages %}{{ message['role'] + ': ' + message['content'] + '\\n' }}"
        "{% endfor %}assistant: "
    )

    def tensor(name: str, shape: tuple[int, ...]) -> None:
        writer.add_tensor(name, rng.normal(0, 0.02, shape).astype(np.float32))

    def norm(name: str) -> None:
        writer.add_tensor(name, np.ones((32,), dtype=np.float32))

    tensor("token_embd.weight", (len(tokens), 32))
    norm("output_norm.weight")
    tensor("output.weight", (len(tokens), 32))
    norm("blk.0.attn_norm.weight")
    for part in ("q", "k", "v", "output"):
        tensor(f"blk.0.attn_{part}.weight", (32, 32))
    norm("blk.0.ffn_norm.weight")
    tensor("blk.0.ffn_gate.weight", (64, 32))
    tensor("blk.0.ffn_up.weight", (64, 32))
    tensor("blk.0.ffn_down.weight", (32, 64))
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: create_random_gguf.py OUTPUT.gguf")
    main(sys.argv[1])
