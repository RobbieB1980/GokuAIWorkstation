# GokuAI — continue point

## Status (models downloaded + backend up)

### Verified on disk (`C:\gokuai\models`)
| Pack | Path | Size |
|---|---|---:|
| Fast coder EXL3 | `EXL3\qwen3-coder-30b-a3b-exl3-4bpw` | 14.96 GB |
| Heavy Mia EXL3 | `EXL3\qwen3.8-27b-exl3-3.5bpw` | 14.31 GB |
| DFlash draft | `EXL3\qwen3.8-27b-dflash2-exl3-5bpw` | 1.37 GB |
| Text embed | `Embedding\qwen3-embedding-8b` | ~14 GB |
| Text rerank | `Reranker\qwen3-reranker-8b` | ~15 GB |
| VL assistant | `VL\qwen3-vl-8b-instruct` | ~16 GB |
| VL embed/rerank | under `VL\` | present |

### Role wiring (applied)
- **fast / code / general-purpose** → coder EXL3
- **heavy / research / plan** → Mia Qwen3.8 EXL3 (switch worker to load)
- Parent remains **Grok 4.5 medium**

### Backend
- Mia `serve_openai` on `http://127.0.0.1:8888`
- Alias proxy on `http://127.0.0.1:11437/v1`
- Default loaded worker: **fast coder** (`Switch-GokuWorker.ps1 -Worker fast`)

```powershell
cd C:\gokuai
.\Start-GokuBackend.ps1            # if not running
.\Switch-GokuWorker.ps1 -Worker heavy -Restart   # optional heavy swap
.\Start-GokuAI.ps1 -ProjectPath C:\gokuai\projects\demo
```

### Still Phase 2
- Embedding / reranker / VL **services** (weights are local; no OpenAI wrappers yet)

### Notes
- Empty leftover folder `AlexanderKyngqwen3-coder-...` can be deleted.
- Mia DeepSeek-V4 DSA import is patched optional on Windows so Qwen EXL3 loads.
