[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [string]$SourceGrokHome = 'C:\rmblocal_llm\grok-home',
    [switch]$SkipGrokInstall,
    [switch]$ForceConfig,
    [switch]$DownloadModels,
    [ValidateSet('q6', 'q8')]
    [string]$DefaultProfile = 'q6',
    # Repair a broken/partial install without full re-scaffold.
    [switch]$Repair,
    [switch]$SkipBackendStart,
    # Deprecated no-ops (kept so old docs/scripts do not break).
    [switch]$SkipMiaKit,
    [switch]$DownloadMiaModels
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Ensure-Dir([string]$Path) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Test-Url([string]$Url) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return $resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500
    } catch { return $false }
}

function Ensure-Cuda12Redist([string]$LlamaDir) {
    $cudaDll = Join-Path $LlamaDir 'ggml-cuda.dll'
    $cudart = Join-Path $LlamaDir 'cudart64_12.dll'
    $cublas = Join-Path $LlamaDir 'cublas64_12.dll'
    if (-not (Test-Path $cudaDll)) {
        Write-Warning "ggml-cuda.dll missing under $LlamaDir - GPU offload will not work."
        return
    }
    if ((Test-Path $cudart) -and (Test-Path $cublas)) {
        Write-Host "CUDA 12 redistributables present."
        return
    }
    Write-Step "Fetching CUDA 12 runtime DLLs for ggml-cuda (one-time)"
    $tmp = Join-Path $LlamaDir 'cuda12-redist'
    Ensure-Dir $tmp
    $py = $null
    foreach ($c in @(
        (Join-Path $Root 'runtime\.venv\Scripts\python.exe'),
        'C:\Users\rmbel\AppData\Local\Programs\Python\Python312\python.exe',
        'py'
    )) {
        if ($c -eq 'py') { $py = 'py'; break }
        if (Test-Path $c) { $py = $c; break }
    }
    if ($py -eq 'py') {
        & py -3.12 -m pip download nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 -d $tmp --no-deps | Out-Host
    } else {
        & $py -m pip download nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 -d $tmp --no-deps | Out-Host
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($whl in Get-ChildItem $tmp -Filter '*.whl' -ErrorAction SilentlyContinue) {
        $extract = Join-Path $tmp ($whl.BaseName + '_extract')
        if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
        [IO.Compression.ZipFile]::ExtractToDirectory($whl.FullName, $extract)
        Get-ChildItem $extract -Recurse -Filter '*.dll' | ForEach-Object {
            Copy-Item -Force $_.FullName (Join-Path $LlamaDir $_.Name)
        }
    }
    if (-not ((Test-Path $cudart) -and (Test-Path $cublas))) {
        throw "Failed to materialize cudart64_12.dll / cublas64_12.dll into $LlamaDir"
    }
    Write-Host "CUDA 12 DLLs installed beside llama-server."
}

Write-Step "GokuAI station root"
$Root = (New-Item -ItemType Directory -Force -Path $Root).FullName
foreach ($rel in @('templates','scripts','runtime','models','logs','projects','vendor','grok-home')) {
    Ensure-Dir (Join-Path $Root $rel)
}
$here = if ($PSScriptRoot) { $PSScriptRoot } else { $Root }

if ($SkipMiaKit -or $DownloadMiaModels) {
    Write-Warning "DEPRECATED: -SkipMiaKit / -DownloadMiaModels ignored. Backend is llama.cpp."
}

Write-Step "Python 3.12"
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' not found. Install Python 3.12."
}
Write-Host (& py -3.12 --version)

Write-Step "Station venv (proxy / helpers)"
$venv = Join-Path $Root 'runtime\.venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
    & py -3.12 -m venv $venv
}
& (Join-Path $venv 'Scripts\python.exe') -m pip install --upgrade pip | Out-Host

Write-Step "GrokBuild home"
$grokHome = Join-Path $Root 'grok-home'
$grokExe = Join-Path $grokHome 'bin\grok.exe'
if (-not $SkipGrokInstall) {
    if (-not (Test-Path $grokExe)) {
        $srcExe = Join-Path $SourceGrokHome 'bin\grok.exe'
        if (Test-Path $srcExe) {
            Write-Host "Copying GrokBuild binary tree from $SourceGrokHome..."
            Ensure-Dir (Join-Path $grokHome 'bin')
            Copy-Item -Force (Join-Path $SourceGrokHome 'bin\*') (Join-Path $grokHome 'bin')
            if (Test-Path (Join-Path $SourceGrokHome 'bundled')) {
                Ensure-Dir (Join-Path $grokHome 'bundled')
                & robocopy.exe (Join-Path $SourceGrokHome 'bundled') (Join-Path $grokHome 'bundled') /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
            }
            if (Test-Path (Join-Path $SourceGrokHome 'docs')) {
                & robocopy.exe (Join-Path $SourceGrokHome 'docs') (Join-Path $grokHome 'docs') /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
            }
            foreach ($name in @('auth.json','version.json')) {
                $src = Join-Path $SourceGrokHome $name
                if (Test-Path $src) { Copy-Item -Force $src (Join-Path $grokHome $name) }
            }
        }
        else {
            Write-Host "Installing GrokBuild via official installer into $grokHome ..."
            $env:GROK_HOME = $grokHome
            irm https://x.ai/cli/install.ps1 | iex
        }
    }
    else {
        Write-Host "Found existing $grokExe - preserving."
    }
}
if (-not (Test-Path $grokExe)) {
    Write-Warning "grok.exe not found at $grokExe. Run grok login after install."
}

Write-Step "Materialize config.toml"
$configPath = Join-Path $grokHome 'config.toml'
$template = Join-Path $Root 'templates\config.toml.template'
if (-not (Test-Path $template)) { $template = Join-Path $here 'templates\config.toml.template' }
if (-not (Test-Path $template)) { throw "Missing templates\config.toml.template" }
if ((-not (Test-Path $configPath)) -or $ForceConfig -or $Repair) {
    Copy-Item -Force $template $configPath
    Write-Host "Wrote $configPath"
}
else {
    Write-Host "Keeping existing $configPath (use -ForceConfig or -Repair to overwrite)"
}

$personaSrc = Join-Path $Root 'templates\persona-goku-compact.toml'
$personaDir = Join-Path $grokHome 'personas'
Ensure-Dir $personaDir
if (Test-Path $personaSrc) {
    Copy-Item -Force $personaSrc (Join-Path $personaDir 'goku-compact.toml')
}

$agentsSrc = Join-Path $Root 'AGENTS.md'
$agentsTpl = Join-Path $Root 'templates\AGENTS-GokuAI.md'
if (Test-Path $agentsSrc) {
    Copy-Item -Force $agentsSrc $agentsTpl -ErrorAction SilentlyContinue
}

Write-Step "Routing + selection (llama.cpp)"
$routingSrc = Join-Path $Root 'runtime\goku-routing.json'
@{
    product = 'GokuAI'
    parent_model = 'grok-4.5'
    parent_reasoning_effort = 'medium'
    runtime = 'llama.cpp'
    deprecated_mia = $true
    proxy_url = 'http://127.0.0.1:11437/v1'
    backend_url = 'http://127.0.0.1:8888/v1'
    default_profile = $DefaultProfile
    model_q6 = (Join-Path $Root 'models\kat-reap50-Q6_K.gguf')
    model_q8 = (Join-Path $Root 'models\kat-reap50-Q8_0.gguf')
} | ConvertTo-Json | Set-Content -Encoding UTF8 $routingSrc

[ordered]@{
    backend = 'llama.cpp'
    default_profile = $DefaultProfile
    model_path = Join-Path $Root ("models\kat-reap50-{0}.gguf" -f $(if ($DefaultProfile -eq 'q8') { 'Q8_0' } else { 'Q6_K' }))
    alias = 'goku-code'
    ctx_size = $(if ($DefaultProfile -eq 'q8') { 16384 } else { 32768 })
    port = 8888
    proxy = 11437
    reasoning = 'off'
    updated = (Get-Date).ToString('o')
} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Root 'models\code-selection.json')

Write-Step "User env hints"
[Environment]::SetEnvironmentVariable('GOKUAI_ROOT', $Root, 'User')
Write-Host "GOKUAI_ROOT=$Root (User env)"

Write-Step "llama.cpp runtime"
$llamaDir = Join-Path $Root 'runtime\llama.cpp'
$llamaServer = Join-Path $llamaDir 'llama-server.exe'
if (-not (Test-Path $llamaServer)) {
    throw @"
Missing $llamaServer

Place a CUDA-enabled llama.cpp Windows build in runtime\llama.cpp\
(must include llama-server.exe + ggml-cuda.dll).
Then re-run: .\Install-GokuAI.ps1 -Repair
"@
}
Ensure-Cuda12Redist -LlamaDir $llamaDir

Write-Step "GGUF models"
$q6 = Join-Path $Root 'models\kat-reap50-Q6_K.gguf'
$q8 = Join-Path $Root 'models\kat-reap50-Q8_0.gguf'
$need = if ($DefaultProfile -eq 'q8') { $q8 } else { $q6 }
if (-not (Test-Path $need)) {
    if ($DownloadModels) {
        Write-Warning "Automatic GGUF download is not wired for kat-reap50 yet. Place the file at:`n  $need"
    }
    Write-Warning "Missing default GGUF: $need"
    Write-Host "Copy kat-reap50-Q6_K.gguf (and optional Q8_0) into $Root\models\"
}
else {
    $gb = [math]::Round((Get-Item $need).Length / 1GB, 2)
    Write-Host "Found $need ($gb GB)"
}

if ($Repair) {
    Write-Step "Repair mode"
    & (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 90
    & (Join-Path $Root 'Validate-GokuAI.ps1') -Root $Root
}

if (-not $SkipBackendStart) {
    if (Test-Path $need) {
        Write-Step "Start llama.cpp backend ($DefaultProfile)"
        & (Join-Path $Root 'Start-GokuBackend.ps1') -Root $Root -Profile $DefaultProfile -ForceRestart
    }
    else {
        Write-Warning "Skipping backend start (GGUF missing)."
    }
}

Write-Host "`nGokuAI install complete." -ForegroundColor Green
Write-Host "Backend:   llama.cpp (Mia/EXL3 workers DEPRECATED)"
Write-Host "Models:    $(Join-Path $Root 'models')"
Write-Host "Start:     .\Start-GokuBackend.ps1 -Profile $DefaultProfile -ForceRestart"
Write-Host "Repair:    .\Install-GokuAI.ps1 -Repair -ForceConfig"
Write-Host "Validate:  .\Validate-GokuAI.ps1 -RequireBackend"
Write-Host "Launch:    .\Start-GokuAI.ps1 -ProjectPath C:\gokuai\projects\demo"
