# GokuAI model-fit suite

This suite evaluates models listed in `models/model-manifest.json`.

## What it measures

- Installation integrity and configured paths.
- EXL3 instruction following, grounded answers, Java repair, code review, migration discipline, completion rate, and latency.
- MTP versus DFlash speculative decoding under the same heavy-model task suite.
- Embedding, reranker, and vision model load/inference compatibility.
- A consolidated role-fit report with conservative decision labels.

`candidate` for an auxiliary model means inference works; it does not claim production retrieval quality without a labelled local evaluation corpus.

## Run

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\gokuai\Run-GokuModelFitSuite.ps1
```

Use `-SkipAux` for chat-only testing, `-SkipChat` for installation/auxiliary validation, or `-Workers fast` for a short coder run.

Reports are written beneath `C:\gokuai\benchmarks\fit-suite-<timestamp>`.
