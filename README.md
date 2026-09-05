# GokuAI

Local EXL3 worker station with **GrokBuild** as the cloud parent orchestrator.

| Role | Model |
|---|---|
| Parent / main agent | **Grok 4.5** (`reasoning_effort = medium`) |
| Working agents | Local **llama.cpp** (`kat-reap50` GGUF, reasoning off) |
| Default worker | `kat-reap50-Q6_K.gguf` @ 32k (`goku-code`) |
| Optional A/B | `kat-reap50-Q8_0.gguf` @ 16k |

## Goals

- Subagents do the heavy work in their own context windows.
- Parent only plans, delegates, verifies compact summaries, and recovers.
- On worker failure: Grok rebriefs → retry / `resume_from` the subagent.
- Reduce token burn and repeated large context in the parent session.

## Layout

```
C:\gokuai\
  grok-home\          GrokBuild home (config, sessions, bin)
  runtime\            llama.cpp / routing JSON
  models\             Selection JSON + optional weight mounts
  scripts\            Alias proxy, Sync-LegacyConverterWorkspace, helpers
  tooling\            Tracked tool overlays (not gitignored)
    legacy-converter-workspace-overlay\   Fix-in-Grok skills/agents
  templates\          Config / AGENTS / persona seeds
  logs\               Backend and install logs
  projects\           Optional workspaces (gitignored — local only)
```

## Workspace launcher + migration skills (do not lose)

| Tool | Path | Purpose |
|---|---|---|
| Desktop launcher | `Open-GokuAIWorkspace.cmd` / `.ps1` | GUI open/create workspace |
| Sync skills | `scripts\Sync-LegacyConverterWorkspace.ps1` | Copy migration `.grok` skills into any workspace |
| Tracked overlay | `tooling\legacy-converter-workspace-overlay\` | Skills/agents survive `projects/` wipe |
| Start Grok | `Start-GokuAI.ps1` | Used by Fix-in-Grok + launcher |
| Backend | `Start-GokuBackend.ps1` | llama.cpp worker |

The launcher **RB Legacy Converter repair** preset opens `projects\RB-Legacy-Java-Converter` and syncs skills first. **Every** launch (including new workspaces) syncs `/repair-failed-262-output` skills from the tracked overlay.

```powershell
.\Open-GokuAIWorkspace.ps1 -ValidateOnly
.\scripts\Sync-LegacyConverterWorkspace.ps1 -Workspace C:\gokuai\projects\demo -SkillsOnly
```

Default OpenAI worker front door: `http://127.0.0.1:11437/v1`  
(Mia kit native port is `8888`; Goku aliases through the proxy.)

## Quick start

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
cd C:\gokuai
# 1) Put CUDA llama.cpp build in runtime\llama.cpp\ (llama-server.exe + ggml-cuda.dll)
# 2) Put GGUFs in models\ (kat-reap50-Q6_K.gguf required; Q8_0 optional)
.\Install-GokuAI.ps1 -ForceConfig
.\Start-GokuBackend.ps1 -Profile q6 -ForceRestart
.\Validate-GokuAI.ps1 -RequireBackend
.\Start-GokuAI.ps1 -ProjectPath C:\gokuai\projects\demo
```

### If install / backend breaks

```powershell
.\Repair-GokuAI.ps1
# or:
.\Install-GokuAI.ps1 -Repair -ForceConfig
.\Validate-GokuAI.ps1 -RequireBackend
```

**Backend:** llama.cpp `llama-server` (Mia/EXL3 workers deprecated — see `DEPRECATED-MIA-EXL3-WORKERS.md`).

## First EXL3 stack

Deployment kit: https://github.com/MiaAI-Lab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw

Installer downloads these public weight sets into `C:\gokuai\models\`:

| Piece | Hugging Face | Local folder |
|---|---|---|
| Target (default worker) | `Mia-AiLab/Qwen3.8-27B-EXL3-3.5bpw` (~14.2 GB) | `models\Qwen3.8-27B-EXL3-3.5bpw` |
| Draft (optional accelerator) | `Mia-AiLab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw` (~1.4 GB) | `models\Qwen3.8-27B-DFlash2-EXL3-5.0bpw` |
| Challenger (A/B test) | `AlexanderKyng/qwen3-coder-30b-a3b-instruct-exl3-4.0bpw-optimized` (~16 GB) | `models\qwen3-coder-30b-a3b-instruct-exl3-4.0bpw-optimized` |

Default runtime uses **MTP** (`DRAFT=mtp`) on the Mia target. Switch workers for comparison:

```powershell
.\Switch-GokuWorker.ps1 -Worker challenger -Restart
.\Switch-GokuWorker.ps1 -Worker primary -Restart
```

4090 defaults: `GPU_MEM_GB=22`, `CACHE_QUANT=nvfp4`, `CONTEXT_SIZE=65536`, `DRAFT=mtp`.

## Prerequisites (Phase 1 model load)

- Python 3.12
- Git
- NVIDIA RTX 4090 drivers (present)
- **Visual Studio Build Tools** (C++ workload) - required to compile Mia ExLlamaV3 CUDA ext
- **CUDA Toolkit** matching the torch index (default cu128 in `.env`)
- No HF token required for these public Mia repos

GGUF / llama.cpp is intentionally **not** the default worker path.
