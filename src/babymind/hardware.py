"""Offline hardware detection and conservative local-model sizing.

Everything here is an estimate derived from the machine's own reported memory
and core count. It never downloads anything and never claims a capability the
hardware was not measured to support.
"""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

# (minimum RAM in GB, recommended parameter class, context, note)
TIERS = (
    (32, "7B–8B", 8192, "Comfortable for 7–8B Q4_K_M with a large context."),
    (16, "4B–7B", 8192, "4B Q4_K_M with an 8k context is the safe default."),
    (8, "2B–4B", 4096, "Use a 2–4B Q4 model and keep the context modest."),
    (0, "1B–2B", 2048, "Small models only; expect limited reasoning depth."),
)


def _ram_gb() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / (1024 ** 2), 1)
    except (OSError, ValueError, ImportError, AttributeError):
        return None
    return None


def _cpu_name() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except (OSError, ValueError, ImportError, AttributeError):
        pass
    return platform.processor() or platform.machine() or "unknown CPU"


def _gpu_hint() -> str:
    if shutil.which("nvidia-smi"):
        return "NVIDIA tooling detected. Verify a CUDA-enabled llama.cpp build before enabling GPU layers."
    return "No dedicated GPU tooling detected. CPU inference is the supported default."


def _recommend(ram_gb: float | None) -> dict:
    if ram_gb is None:
        return {"parameter_class": "2B–4B", "context_size": 4096,
                "note": "Available memory could not be measured; use the smallest model you can tolerate."}
    for threshold, parameter_class, context, note in TIERS:
        if ram_gb >= threshold:
            return {"parameter_class": parameter_class, "context_size": context, "note": note}
    return {"parameter_class": "1B–2B", "context_size": 2048, "note": TIERS[-1][3]}


def hardware_report(data_home: str | Path | None = None) -> dict:
    ram = _ram_gb()
    cores = os.cpu_count() or 1
    home = Path(data_home) if data_home else Path.home() / ".babymind"
    free_disk = None
    try:
        home.mkdir(parents=True, exist_ok=True)
        free_disk = round(shutil.disk_usage(home).free / (1024 ** 3), 1)
    except OSError:
        free_disk = None
    recommendation = _recommend(ram)
    # Leave one core for the UI and OS; llama.cpp threads are CPU-bound.
    threads = max(1, min(cores - 1, 8))
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": _cpu_name(),
        "logical_cores": cores,
        "recommended_threads": threads,
        "ram_gb": ram,
        "free_disk_gb": free_disk,
        "gpu": _gpu_hint(),
        "recommended": recommendation,
        "llama_cpp_flags": [
            "--threads", str(threads),
            "--ctx-size", str(recommendation["context_size"]),
            "--n-gpu-layers", "0",
        ],
        "model_download_needs": "at least 4.5 GB free for a 4B Q4_K_M model plus workspace",
        "disclaimer": (
            "These are estimates from reported memory and core count. Actual speed depends on the "
            "llama.cpp build, quantization, and memory bandwidth. BabyMind never claims capabilities "
            "the hardware was not measured to support."
        ),
    }
