# llama.cpp runtime (required)

Place a **CUDA-enabled** Windows llama.cpp build here, including at least:

- `llama-server.exe`
- `llama-server-impl.dll` / companion DLLs
- `ggml-cuda.dll`

`Install-GokuAI.ps1 -Repair` will fetch `cudart64_12.dll` / `cublas64_12.dll` beside these binaries if missing (required by current `ggml-cuda.dll`).

Start:

```powershell
C:\gokuai\Start-GokuBackend.ps1 -Profile q6 -ForceRestart
```
