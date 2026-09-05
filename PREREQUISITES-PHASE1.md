# GokuAI Phase 1 prerequisites

## Locked choices

- Parent: Grok 4.5 medium
- Backend: **Mia `serve_openai.py`**
- Default worker: Mia Qwen3.8-27B EXL3 3.5bpw (+ optional DFlash2 draft)
- Challenger (later A/B): AlexanderKyng Qwen3-Coder-30B EXL3 4.0bpw
- **Model downloads are deferred** until you opt in (`-DownloadModels`)

## Runtime status (installed on this machine)

| Component | Status |
|---|---|
| VS Build Tools 2022 + C++ | Installed |
| CUDA Toolkit | 13.3 (`nvcc` OK) |
| Torch | `2.14.0+cu130` (GPU OK on RTX 4090) |
| Mia ExLlamaV3 | `1.4.2` compiled/importable |
| Model weights | Deferred for you |

## Weights (when you are ready)

Prefer one pack at a time on a slow link:

```powershell
cd C:\gokuai
.\Download-GokuModels.ps1 -Only primary    # ~14 GB Mia Qwen3.8-27B EXL3
# optional later:
.\Download-GokuModels.ps1 -Only draft
.\Download-GokuModels.ps1 -Only challenger
.\Start-GokuBackend.ps1
.\Start-GokuAI.ps1 -ProjectPath C:\gokuai\projects\demo
```

No HF token required for the current public Mia / AlexanderKyng repos.

