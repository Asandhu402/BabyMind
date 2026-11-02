# BabyMind

BabyMind is a modular personal-AI foundation with a fixed catalogue of exactly **50 agents**. All roles share one assistant identity and one configured model provider; role-specific instructions change the specialist perspective, not the underlying model.

## Requirements

- Python 3.10 or newer
- LM Studio (free local model runner) for local AI responses
- No third-party Python packages are required by the runtime

## Install

From the repository root:

    python -m pip install -e .

## Start the local model

1. Open LM Studio and download a model that fits your computer's memory.
2. Load that model in the Chat / Developer interface.
3. Start the local server. The default address is `http://127.0.0.1:1234/v1`.
4. Keep LM Studio's server running while using BabyMind.

BabyMind asks LM Studio for the loaded model ID automatically. To override the server or model, set:

- `BABYMIND_BASE_URL` — defaults to `http://127.0.0.1:1234/v1`
- `BABYMIND_MODEL` — optional; defaults to the first model reported by LM Studio
- `BABYMIND_API_KEY` — optional, only if your local server requires one
- `BABYMIND_HOME` — optional folder for BabyMind's local data

## Commands

    babymind health
    babymind list
    babymind run BM-01 "Route this task without calling a model"
    babymind ask BM-02 "Research this question using the local model"
    babymind ask BM-01 "Remember this preference" --remember
    babymind ask BM-02 "Use relevant context from before" --use-memory
    babymind memory list
    babymind memory clear

- `run` tests role routing only; it does not call a model.
- `ask` sends the request to the single model served by LM Studio, with the selected agent's specialist instructions.
- Memory is local SQLite and opt-in: nothing is saved unless `--remember` is supplied. Previous notes are not included unless `--use-memory` is supplied.
- `memory clear` deletes saved BabyMind memory records from its SQLite database.

## Architecture in this increment

- **50 role agents:** the canonical BM-01 through BM-50 registry remains unchanged and validated.
- **One identity / coordinator:** `BabyMindCoordinator` maintains one assistant personality and applies the selected role's specialty.
- **Model adapter:** `LMStudioProvider` uses LM Studio's OpenAI-compatible local API.
- **Shared local memory:** `LocalMemory` stores explicitly saved task/response pairs in SQLite.
- **CLI:** health, list, scaffold routing, local-model ask, and memory management.

## Honest capability boundary

The 50 entries are role definitions, not 50 separate autonomous models. This version connects all 50 roles to one shared local model. It does not yet give agents independent tools, background autonomy, web access, or permission to take actions. The model's quality and speed depend on the model you load and your computer's available memory.

## Fixed invariant

The application refuses to start if the registry contains anything other than 50 agents or contains duplicate or non-sequential IDs.
