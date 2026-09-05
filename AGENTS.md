# GokuAI issue-resolution policy

## Authority

GrokBuild (`grok-4.5`, medium effort) is the sole orchestrator and the only agent that communicates with the user, chooses work, changes routing, or decides whether an issue is resolved.

Local GokuAI models are disposable issue workers. They do not plan the overall project, converse with one another, spawn more workers, or retain project history.

## Backend (current)

**llama.cpp `llama-server`** serving `kat-reap50` GGUF (reasoning/thinking **off**).

```powershell
# Default worker backend (Q6_K @ 64k; OOM fallback --n-cpu-moe 8)
C:\gokuai\Start-GokuBackend.ps1 -Profile q6 -ForceRestart

# Optional quality A/B (Q8_0 @ 16k)
C:\gokuai\Start-GokuBackend.ps1 -Profile q8 -ForceRestart

# Force MoE CPU offload on first start
C:\gokuai\Start-GokuBackend.ps1 -Profile q6 -NCpuMoe 8 -ForceRestart
```

- OpenAI API: `http://127.0.0.1:8888/v1`
- Alias proxy: `http://127.0.0.1:11437/v1` (all `goku-*` → same model)
- Grok local model id: **`goku-code`**
- q6 defaults: `ctx=65536`, `batch=2048`, `ubatch=1024`, samplers `temp=0.7 top_p=0.8 top_k=20 min_p=0 presence_penalty=1.5`; on OOM retries with `--n-cpu-moe 8`

### Deprecated

Mia `serve_openai` / EXL3 multi-role switching (`repair`/`migration`/`review`/`fast` as separate weights) is **deprecated**.  
`Switch-GokuWorker.ps1 -Worker repair|migration|review|fast|heavy` now only maps onto llama.cpp `q6`/`q8`.

## When to delegate

Delegate only after GrokBuild has identified one concrete unresolved issue with a testable outcome. Do not delegate ordinary conversation, status reporting, planning, already-successful work, or broad repository exploration.

Use at most one local worker at a time and one worker call per issue. A second call is allowed only as an independent review after the first worker has produced an artifact.

## Issue packet

Create `.gokuai/issues/<issue-id>/request.md` containing only:

- one problem statement;
- acceptance criteria;
- exact source and evidence paths;
- the smallest useful error excerpt, never an entire build log;
- validation commands;
- the required result path.

Pass the worker the request path, not the parent transcript. Do not use `resume_from`. Do not paste previous worker reasoning into a new prompt.

## Worker contract

The worker handles one issue and writes `.gokuai/issues/<issue-id>/result.json` with `status`, `diagnosis`, `files_changed`, `evidence_paths`, `validation`, `remaining_risks`, and `confidence`.

The worker's chat response is at most 12 lines and contains only the result path, status, validation outcome, and unresolved blocker. Detailed notes and logs belong beside `result.json`.

Thinking/reasoning is disabled on the llama-server (`--reasoning off`). Never request hidden reasoning or chain-of-thought.

## Completion and escalation

GrokBuild reads the compact result and verifies the reported files or test result once. If validation passes, report the resolution to the user without another worker round-trip.

If the worker fails, GrokBuild either resolves the issue itself or performs one independent `review` pass using the request/result paths. Do not bounce context between workers. After one review, GrokBuild makes the final decision or reports the blocker.

Use `C:\gokuai\Reset-GokuBackend.ps1` when GPU memory is needed elsewhere.
