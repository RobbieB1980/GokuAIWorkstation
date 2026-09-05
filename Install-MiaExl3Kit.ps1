[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [string]$KitUrl = 'https://github.com/MiaAI-Lab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw.git',
    [string]$EngineUrl = 'https://github.com/MiaAI-Lab/exllamav3.git',
    # Default: station models folder (C:\gokuai\models)
    [string]$ModelsRoot = '',
    [ValidateSet('mtp','dflash2','none')][string]$Draft = 'mtp',
    [int]$ContextSize = 65536,
    [double]$GpuMemGb = 22,
    [string]$CacheQuant = 'nvfp4',
    [int]$Port = 8888,
    [string]$TorchIndexUrl = 'https://download.pytorch.org/whl/cu130',
    [switch]$SkipEngineInstall,
    # Large HF weights are opt-in (slow links). Pass -DownloadModels when ready.
    [switch]$DownloadModels,
    [switch]$SkipModelDownload,
    [switch]$SkipDraftDownload,
    [switch]$SkipChallengerDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Test-Prereq {
    $issues = @()
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { $issues += 'git' }
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { $issues += 'py (Python 3.12)' }
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $vsPath = $null
    if (Test-Path $vswhere) {
        $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    }
    if (-not $vsPath) { $issues += 'Visual Studio Build Tools (C++ workload) - required to compile exllamav3 CUDA ext' }
    $cudaOk = $false
    foreach ($p in @($env:CUDA_PATH, 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8', 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0')) {
        if ($p -and (Test-Path $p)) { $cudaOk = $true; break }
    }
    if (-not $cudaOk) { $issues += 'CUDA Toolkit (nvcc) - required for first engine build' }
    return $issues
}

if (-not $ModelsRoot) {
    $ModelsRoot = Join-Path $Root 'models'
}

Write-Step "Prereq check"
$issues = Test-Prereq
foreach ($i in $issues) { Write-Warning "Missing: $i" }
if ($issues.Count -gt 0) {
    Write-Host @"

GokuAI can still clone the Mia kit, write the 4090 .env, and download public EXL3 weights.
Engine compile still needs Build Tools + CUDA Toolkit.

Install suggestions:
  winget install Microsoft.VisualStudio.2022.BuildTools
  # In Build Tools installer: enable Desktop development with C++
  # CUDA Toolkit from NVIDIA matching the torch index ($TorchIndexUrl)

"@ -ForegroundColor Yellow
}

Write-Step "Clone Mia deployment kit"
$kitDir = Join-Path $Root 'runtime\mia-kit'
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'runtime') | Out-Null
if (-not (Test-Path (Join-Path $kitDir '.git'))) {
    if (Test-Path $kitDir) { Remove-Item -Recurse -Force $kitDir }
    git clone --depth 1 $KitUrl $kitDir
}
else {
    Push-Location $kitDir
    try { git pull --ff-only } catch { Write-Warning "git pull failed: $($_.Exception.Message)" }
    Pop-Location
}

Write-Step "GokuAI models folder"
New-Item -ItemType Directory -Force -Path $ModelsRoot | Out-Null
$modelDir = Join-Path $ModelsRoot 'Qwen3.8-27B-EXL3-3.5bpw'
$draftDir = Join-Path $ModelsRoot 'Qwen3.8-27B-DFlash2-EXL3-5.0bpw'
$challengerDir = Join-Path $ModelsRoot 'qwen3-coder-30b-a3b-instruct-exl3-4.0bpw-optimized'
Write-Host "Target:     $modelDir"
Write-Host "Draft:      $draftDir"
Write-Host "Challenger: $challengerDir"

Write-Step "Write 4090 .env"
$envPath = Join-Path $kitDir '.env'
$engineLocal = Join-Path $Root 'runtime\exllamav3'
$stamp = Get-Date -Format o
$modelDirUnix = ($modelDir -replace '\\', '/')
$draftDirUnix = ($draftDir -replace '\\', '/')
$envLines = @(
    "# GokuAI-generated for RTX 4090 - $stamp",
    "EXL3_REPO=git+https://github.com/MiaAI-Lab/exllamav3.git",
    "TORCH_INDEX_URL=$TorchIndexUrl",
    "MODEL_DIR=$modelDirUnix",
    "DRAFT=$Draft",
    "DRAFT_DIR=$draftDirUnix",
    "HF_TARGET_REPO=Mia-AiLab/Qwen3.8-27B-EXL3-3.5bpw",
    "HF_DRAFT_REPO=Mia-AiLab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw",
    "PORT=$Port",
    "HOST=127.0.0.1",
    "CONTEXT_SIZE=$ContextSize",
    "CACHE_QUANT=$CacheQuant",
    "GPU_MEM_GB=$GpuMemGb",
    "CPU_CACHE_GB=0"
)
if ($env:HF_TOKEN) {
    $envLines += "HF_TOKEN=$($env:HF_TOKEN)"
}
elseif ($env:HUGGING_FACE_HUB_TOKEN) {
    $envLines += "HF_TOKEN=$($env:HUGGING_FACE_HUB_TOKEN)"
}
$envLines | Set-Content -Encoding UTF8 $envPath
Write-Host "Wrote $envPath"

# Update selection JSON paths
$selectionPath = Join-Path $Root 'models\code-selection.json'
if (Test-Path $selectionPath) {
    $sel = Get-Content -Raw $selectionPath | ConvertFrom-Json
    $sel.model_dir = $modelDir
    $sel.draft_dir = $draftDir
    $sel.draft_mode = $Draft
    $sel.cache_quant = $CacheQuant
    $sel.context_size = $ContextSize
    $sel.gpu_mem_gb = $GpuMemGb
    $sel | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $selectionPath
}

Write-Step "Create Mia Python venv"
$venv = Join-Path $kitDir '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $python)) {
    & py -3.12 -m venv $venv
}
& $python -m pip install --upgrade pip wheel setuptools | Out-Host

if (-not $SkipEngineInstall) {
    if ($issues.Count -gt 0) {
        Write-Warning "Skipping engine install because build prereqs are missing. Re-run without -SkipEngineInstall after installing them."
    }
    else {
        Write-Step "Install torch from $TorchIndexUrl"
        & $python -m pip install torch --index-url $TorchIndexUrl | Out-Host

        Write-Step "Clone / install Mia exllamav3 fork"
        if (-not (Test-Path (Join-Path $engineLocal '.git'))) {
            if (Test-Path $engineLocal) { Remove-Item -Recurse -Force $engineLocal }
            git clone --depth 1 $EngineUrl $engineLocal
        }
        Push-Location $engineLocal
        try {
            & $python -m pip install -e . | Out-Host
        }
        finally {
            Pop-Location
        }

        Write-Step "Install server deps (fastapi/uvicorn/huggingface_hub)"
        & $python -m pip install fastapi uvicorn huggingface_hub sse-starlette pydantic | Out-Host
    }
}
else {
    Write-Host "SkipEngineInstall set - venv only."
}

# Default: do not download weights. Explicit -DownloadModels enables it.
# -SkipModelDownload remains supported for callers that already set it.
$shouldDownload = $DownloadModels -and (-not $SkipModelDownload)
if ($shouldDownload) {
    Write-Step "Download EXL3 weights into $ModelsRoot (public repos, resume-friendly)"
    $hfPython = $python
    if (-not (Test-Path $hfPython)) {
        $hfPython = (Get-Command py).Source
        & py -3.12 -m pip install -q huggingface_hub | Out-Host
    }
    else {
        & $hfPython -m pip install -q huggingface_hub | Out-Host
    }

    $dlScript = Join-Path $Root 'scripts\download_exl3_models.py'
    if (-not (Test-Path $dlScript)) {
        throw "Missing download script: $dlScript"
    }
    $dlArgs = @($dlScript, '--models-root', $ModelsRoot)
    if ($SkipDraftDownload) { $dlArgs += '--skip-draft' }
    if ($SkipChallengerDownload) { $dlArgs += '--skip-challenger' }

    # huggingface_hub writes progress to stderr; with $ErrorActionPreference=Stop,
    # PowerShell treats that as a terminating NativeCommandError. Run via cmd so
    # only the process exit code matters.
    $argLine = ($dlArgs | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '
    $cmd = '"' + $hfPython + '" ' + $argLine
    Write-Host "Running: $cmd"
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        cmd.exe /c $cmd
        $dlCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prevEap
    }
    if ($dlCode -ne 0) {
        throw "Model download failed with exit code $dlCode. Re-run to resume; no HF token required for these public repos."
    }

    if (-not (Test-Path $modelDir)) {
        throw "Target model folder missing after download: $modelDir"
    }
    Write-Host "Target ready: $modelDir" -ForegroundColor Green
    if (-not $SkipDraftDownload) {
        if (-not (Test-Path $draftDir)) {
            throw "Draft model folder missing after download: $draftDir"
        }
        Write-Host "Draft ready:  $draftDir" -ForegroundColor Green
    }
    if (-not $SkipChallengerDownload) {
        if (-not (Test-Path $challengerDir)) {
            throw "Challenger model folder missing after download: $challengerDir"
        }
        Write-Host "Challenger ready: $challengerDir" -ForegroundColor Green
        $chalPath = Join-Path $Root 'models\challenger-selection.json'
        if (Test-Path $chalPath) {
            $chal = Get-Content -Raw $chalPath | ConvertFrom-Json
            $chal.model_dir = $challengerDir
            $chal | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $chalPath
        }
    }
}
else {
    Write-Host "Model download deferred (pass -DownloadModels when ready). Models root: $ModelsRoot"
}

Write-Host "`nMia kit install step finished." -ForegroundColor Green
Write-Host "Kit:    $kitDir"
Write-Host "Env:    $envPath"
Write-Host "Models: $ModelsRoot"
if ($issues.Count -gt 0) {
    Write-Host "Resolve prereqs, then re-run: .\Install-MiaExl3Kit.ps1" -ForegroundColor Yellow
}
else {
    Write-Host "Next: .\Start-GokuBackend.ps1"
}
