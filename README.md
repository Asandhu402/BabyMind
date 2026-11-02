# BabyMind

BabyMind is a modular personal-AI foundation with a fixed catalogue of exactly **50 agents**.

## Requirements
- Python 3.10 or newer
- No third-party packages required for the starter runtime

## Run
From the repository root:

    python -m pip install -e .
    babymind health
    babymind list
    babymind run BM-01 "Summarize this task"

## Current scope
This first foundation provides a validated 50-agent registry, stable IDs (BM-01 through BM-50), a dispatcher, a command-line interface, and automated tests.

The agents are currently role-aware scaffolds. They validate routing and return structured hand-off results; they do not claim to perform model inference yet. Model providers, persistent memory, permissions, tools, and the mobile interface will be added as separate modules after this foundation is verified.

## Fixed invariant
The application refuses to start if the registry contains anything other than 50 agents or contains duplicate IDs.
