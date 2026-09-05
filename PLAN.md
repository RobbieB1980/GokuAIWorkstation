# GokuAI — Implementation Plan

## Goal

Build **GokuAI**, a new local-agent station where:

1. **Parent / main agent** = hosted **Grok 4.5** with **`reasoning_effort = medium`**
2. **Working agents** = local **EXL3** models (preferred over GGUF)
3. Subagents do the work; on failure Grok diagnoses and **retries the subagent** (does not redo the whole job in the parent)
4. Primary optimization target: **cut token burn and repeated large context inside GrokBuild’s parent session**

This is **not** a GGUF/llama.cpp fork of RBLocalLLM.

---

## Locked architecture

```
┌─────────────────────────────────────────────────────────────┐
│ GrokBuild parent (cloud)                                    │
│   model: grok-4.5                                           │
│   reasoning_effort: medium                                  │
│   job: plan → delegate → verify summary → recover/retry     │
│   MUST NOT: ingest large logs, full repos, raw MCP dumps    │
└───────────────────────────┬─────────────────────────────────┘
                            │ spawn_subagent (narrow prompt + file refs)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Local EXL3 workers (OpenAI /v1)                             │
│   Phase 1: MiaAI Qwen3.8-27B EXL3 kit on :11437             │
│   Later: goku-fast / code / heavy / research / reviewer     │
│   own context; tools; compact result contracts + file paths │
└─────────────────────────────────────────────────────────────┘
```

### Recovery loop (parent policy)

1. Parent assigns one scoped task to an EXL3 subagent with a **compact prompt** (goal, constraints, file/MCP pointers — not pasted evidence).
2. Subagent works in its own context; writes bulky output under `.gokuai/tasks/<id>/`.
3. Subagent returns a **short structured summary** (status, files, evidence paths, errors, confidence, next step).
4. On failure / low confidence / tool breakage:
   - Parent reads only the **summary + small error slice**
   - Produces a corrected brief
   - **Re-spawns or `resume_from`s** the same worker
5. Parent only does the task itself after the local retry budget is exhausted, then hands control back to EXL3 when possible.

---

## First test model (locked)

**Deployment kit:** [MiaAI-Lab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw](https://github.com/MiaAI-Lab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw)

Important: that GitHub repo is a **launcher + OpenAI server**, not the weights alone.

| Piece | Source | Size / role |
|---|---|---|
| Target weights | HF `Mia-AiLab/Qwen3.8-27B-EXL3-3.5bpw` | ~14.2 GB EXL3 3.5bpw — the actual LLM |
| Draft weights (optional) | HF `Mia-AiLab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw` | ~1.4 GB DFlash2 speculative draft |
| Engine | [MiaAI-Lab/exllamav3](https://github.com/MiaAI-Lab/exllamav3) fork | DFlash2/MTP, NVFP4/FP8 KV, OpenAI tool calling |
| Server | `tools/serve_openai.py` | `/v1/chat/completions` (stream + tools), `/v1/models`, `/health` |
| Default kit port | `8888` | GokuAI will remap/proxy to **`11437`** |

### 4090 recipe (from kit docs)

```env
GPU_MEM_GB=22
CACHE_QUANT=nvfp4          # Ada 4090 supports this (sm >= 8.9)
CONTEXT_SIZE=65536         # start conservative for agent work; kit can do 262k
DRAFT=mtp                  # default: best context/GB, no extra draft download
# Later A/B: DRAFT=dflash2 for ~15% faster decode (uses the 5.0bpw draft)
```

**Phase 1 role mapping (single GPU, one resident model):**

| Goku alias | Points at |
|---|---|
| `goku-code` | Mia Qwen3.8-27B EXL3 3.5bpw (primary worker) |
| `goku-heavy` | same backend temporarily |
| `goku-research` | same backend temporarily (cap reported `context_window` in Grok config) |
| `goku-fast` / `goku-reviewer` | deferred until separate smaller EXL3 picks exist |

All `[subagents.models]` / coding roles → `goku-code` for the first smoke.

### Backend choice

GokuAI Phase 1 uses the **Mia kit server** (`serve_openai.py`) as the EXL3 backend.

| Phase | Backend |
|---|---|
| **Phase 1** | Mia `serve_openai.py` via Goku wrapper |

---

## Hardware baseline (this machine)

| Resource | Value | Implication |
|---|---|---|
| GPU | RTX 4090 **24 GB** | Fits 3.5bpw target + NVFP4 KV; one resident model |
| CPU / RAM | 9950X3D / ~93 GB | Good for build + downloads; CPU KV spill not required for v0 |
| Disk | Multi-TB free | Store weights on D/E/F under e.g. `D:\gokuai-models\` |
| CUDA driver | 616.56 / CUDA UMD 13.4 | Mia fork builds CUDA kernels (needs VS Build Tools / toolkit path on Windows) |

**Windows note:** kit ships `start.sh` (bash). GokuAI will provide `Start-GokuBackend.ps1` that either:
- runs under **WSL2/Git Bash**, or
- reimplements the bootstrap in PowerShell (venv, pip install Mia fork, HF download, launch `serve_openai.py`).

Prefer a PowerShell-native path for a Windows station product.

---

## Relationship to existing RBLocalLLM

| Keep as reference | Do **not** copy as GokuAI default |
|---|---|
| GrokBuild install/preserve | llama.cpp + GGUF |
| Compact persona / recover-retry policy | `mc-*` product identity |
| Single-GPU discipline | Port 11436 llama router |

**Default install root:** `C:\gokuai` (parallel to `C:\rmblocal_llm`). Unload RBLocalLLM’s GPU model before Goku sessions.

---

## GrokBuild configuration contract

```toml
[models]
default = "grok-4.5"
default_reasoning_effort = "medium"
stream_tool_calls = true

[model.goku-code]
model = "goku-code"   # router rewrites to Mia /v1/models id
base_url = "http://127.0.0.1:11437/v1"
name = "Goku Code - Qwen3.8-27B EXL3 3.5bpw (Mia)"
context_window = 65536
temperature = 0.10
max_completion_tokens = 8192   # leave room; Mia always emits reasoning_content from same budget
supports_reasoning_effort = false

[subagents]
enabled = true

[subagents.models]
explore = "goku-code"
plan = "goku-code"
"general-purpose" = "goku-code"
```

Launcher: `Start-GokuAI.ps1` → start Mia backend (+ thin alias proxy if needed) → `grok.exe -m grok-4.5 --cwd <project>`.

### Mia-specific client caveats (encode in AGENTS + router)

1. **Always-on reasoning:** server always fills `reasoning_content`; short `max_tokens` can yield empty `content`. Worker prompts / Grok `max_completion_tokens` must stay generous.
2. **Tool calling:** kit documents real OpenAI `tool_calls` — verify end-to-end with GrokBuild before declaring Phase 1 done.
3. **Model id:** response id may not match folder name; discover via `/v1/models` and alias in the Goku proxy.
4. **Batch-1:** concurrent subagents will queue on one GPU — parent should prefer sequential local workers unless a second GPU appears later.

---

## Token / context reduction policy

Encode in `templates/AGENTS-GokuAI.md` + `persona-goku-compact.toml`:

1. Parent never pastes large bodies when a path reference works.
2. Subagent prompts: task id, acceptance criteria, paths, small error excerpt only.
3. Fixed summary schema; bulky artifacts under `.gokuai/tasks/<id>/`.
4. Prefer `resume_from` so the **child** keeps context across retries.
5. Escalation budget: 2 local retries → Grok rebrief → 1 more local attempt → optional parent hotfix.
6. `[memory] enabled = false` initially.

---

## Deliverables by phase

### Phase 0 — Station scaffold (no weights yet)

| File | Purpose |
|---|---|
| `Install-GokuAI.ps1` | `C:\gokuai` dirs, GrokBuild, Python, config seed |
| `Start-GokuAI.ps1` | Backend health + parent `grok-4.5` medium |
| `Install-MiaExl3Kit.ps1` | Clone Mia kit + fork bootstrap (Windows) |
| `Start-GokuBackend.ps1` | Launch Mia server; health on `:11437` or `:8888`+proxy |
| `scripts/goku_alias_proxy.py` (optional) | Map `goku-code` → Mia model id; port normalize |
| `templates/config.toml.template` | Cloud parent + `goku-code` |
| `templates/AGENTS-GokuAI.md` | Delegate / compact / recover-retry |
| `models/code-selection.json` | Points at Mia target+draft HF ids (paths filled after download) |
| `Validate-GokuAI.ps1` | grok.exe, backend health, config aliases |

### Phase 1 — First EXL3 worker smoke (this model)

1. Install Mia kit + ExLlamaV3 fork on this 4090 (NVFP4, MTP).
2. Auto-download HF target (± draft if `DRAFT=dflash2`).
3. Prove: `/health`, `/v1/models`, chat completion, **structured tool_calls**, streaming.
4. Point all working subagent roles at `goku-code`.
5. Run one real delegated task from Grok parent; confirm parent context stays small and recover-retry works.
6. Optional A/B: `DRAFT=mtp` vs `DRAFT=dflash2` for tok/s vs VRAM.

### Phase 2 — Multi-role EXL3 expansion

- Add smaller fast/reviewer EXL3s
- Swap/unload strategy if more than one heavy model
- Decide when stock Tabby enters vs staying on Mia fork for all DFlash models

### Phase 3 — Optional domain packs

- Minecraft knowledge MCP as add-on, not core identity

---

## Explicit non-goals (v0)

- Replacing Grok 4.5 medium as the main agent
- GGUF/llama.cpp as default workers
- Full multi-model role matrix before the Mia Qwen3.8-27B smoke passes
- Merging into `C:\rmblocal_llm`

---

## Suggested first build slice (after approval)

1. Scaffold `C:\gokuai` + Grok 4.5 medium parent policy + `goku-code` alias.
2. Windows install path for [MiaAI-Lab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw](https://github.com/MiaAI-Lab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw) with 4090 `.env` (MTP + `nvfp4`).
3. Wire GrokBuild subagents to that OpenAI endpoint.
4. Smoke tool-calling + one recover-and-retry demo task.

---

## Open items (non-blocking)

- Prefer **MTP** (context) or **DFlash2** (speed) as the default draft mode for daily use
- Exact first `CONTEXT_SIZE` for agent workloads (64K vs 128K vs 262K)
- WSL vs native PowerShell for Mia `start.sh` bootstrap on this PC
