[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [ValidateSet('q6', 'q8')]
    [string]$Profile = 'q6',
    [int]$BackendPort = 8888,
    [int]$ProxyPort = 11437,
    [switch]$SkipProxy,
    [switch]$ForceRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Test-Url([string]$Url) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return $resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500
    }
    catch { return $false }
}

$llamaDir = Join-Path $Root 'runtime\llama.cpp'
$llamaServer = Join-Path $llamaDir 'llama-server.exe'
$modelsRoot = Join-Path $Root 'models'
$logDir = Join-Path $Root 'logs\backend'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path -LiteralPath $llamaServer)) {
    throw "llama-server missing: $llamaServer"
}

$profiles = @{
    q6 = [ordered]@{
        ModelPath = Join-Path $modelsRoot 'kat-reap50-Q6_K.gguf'
        CtxSize   = 32768
        Label     = 'kat-reap50-Q6_K @ 32k (default goku-code)'
    }
    q8 = [ordered]@{
        ModelPath = Join-Path $modelsRoot 'kat-reap50-Q8_0.gguf'
        CtxSize   = 16384
        Label     = 'kat-reap50-Q8_0 @ 16k (quality A/B)'
    }
}

$profileCfg = $profiles[$Profile]
if (-not (Test-Path -LiteralPath $profileCfg.ModelPath)) {
    throw "GGUF missing: $($profileCfg.ModelPath)"
}

$backendHealth = "http://127.0.0.1:$BackendPort/health"
$proxyHealth = "http://127.0.0.1:$ProxyPort/health"
$backendRoot = "http://127.0.0.1:$BackendPort"

if ($ForceRestart) {
    Write-Step "ForceRestart - flushing prior llama-server / proxy"
    & (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
    # Wait until old listener is actually gone (avoid false "already healthy").
    foreach ($i in 1..30) {
        if (-not (Test-Url $backendHealth)) { break }
        Start-Sleep -Seconds 1
    }
}

# Persist active backend profile for Switch-GokuWorker / docs.
$active = [ordered]@{
    backend        = 'llama.cpp'
    profile        = $Profile
    label          = $profileCfg.Label
    model_path     = $profileCfg.ModelPath
    alias          = 'goku-code'
    host           = '127.0.0.1'
    port           = $BackendPort
    proxy_port     = $ProxyPort
    ctx_size       = $profileCfg.CtxSize
    reasoning      = 'off'
    reasoning_budget = 0
    enable_thinking = $false
    deprecated_mia = $true
    updated        = (Get-Date).ToString('o')
}
$active | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $modelsRoot 'active-worker.json') -Encoding UTF8

if (Test-Url $backendHealth) {
    Write-Host "llama-server already healthy at $backendHealth"
}
else {
    Write-Step "Starting llama-server ($($profileCfg.Label)) on :$BackendPort"
    $stdout = Join-Path $logDir 'llama-server.stdout.log'
    $stderr = Join-Path $logDir 'llama-server.stderr.log'
    # Ensure ggml-cuda.dll and companions resolve (required for -ngl all).
    $env:PATH = "$llamaDir;" + $env:PATH
    $argList = @(
        '-m', $profileCfg.ModelPath,
        '--alias', 'goku-code,goku-fast,goku-heavy,goku-research,goku-reviewer',
        '--host', '127.0.0.1',
        '--port', "$BackendPort",
        '--ctx-size', "$($profileCfg.CtxSize)",
        '--gpu-layers', 'all',
        '--flash-attn', 'on',
        '--cache-type-k', 'q8_0',
        '--cache-type-v', 'q8_0',
        '--parallel', '1',
        '--batch-size', '1024',
        '--ubatch-size', '512',
        '--jinja',
        '--reasoning', 'off',
        '--reasoning-budget', '0',
        '--no-reasoning-preserve',
        '--threads', '16'
    )
    $proc = Start-Process -FilePath $llamaServer -ArgumentList $argList -WorkingDirectory $llamaDir `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -WindowStyle Hidden
    $proc.Id | Set-Content -Encoding ASCII (Join-Path $logDir 'llama-server.pid')
    Write-Host "Started PID $($proc.Id). Waiting for health (model load can take a minute)..."
    $ok = $false
    foreach ($i in 1..120) {
        Start-Sleep -Seconds 2
        if (Test-Url $backendHealth) { $ok = $true; break }
        if ($proc.HasExited) {
            throw "llama-server exited early (code $($proc.ExitCode)). See $stderr"
        }
    }
    if (-not $ok) { throw "llama-server did not become healthy at $backendHealth. See $stderr / $stdout" }
    Write-Host "llama-server healthy." -ForegroundColor Green
}

# Prefer Python for proxy if available; otherwise Grok can hit :8888 directly via aliases.
if (-not $SkipProxy) {
    if (Test-Url $proxyHealth) {
        Write-Host "Alias proxy already healthy at $proxyHealth"
    }
    else {
        $proxyScript = Join-Path $Root 'scripts\goku_alias_proxy.py'
        $proxyPyCandidates = @(
            (Join-Path $Root 'runtime\mia-kit\.venv\Scripts\python.exe'),
            (Join-Path $Root 'runtime\.venv\Scripts\python.exe'),
            'C:\Users\rmbel\AppData\Local\Programs\Python\Python312\python.exe'
        )
        $proxyPy = $proxyPyCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $proxyPy -or -not (Test-Path $proxyScript)) {
            Write-Host "Alias proxy skipped (python/script missing). Use http://127.0.0.1:$BackendPort/v1 directly." -ForegroundColor Yellow
        }
        else {
            Write-Step "Starting Goku alias proxy on :$ProxyPort -> $backendRoot/v1"
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            $pout = Join-Path $logDir "alias-proxy-$stamp.stdout.log"
            $perr = Join-Path $logDir "alias-proxy-$stamp.stderr.log"
            $pargs = @(
                $proxyScript,
                '--host', '127.0.0.1',
                '--port', "$ProxyPort",
                '--backend', "$backendRoot/v1"
            )
            $pproc = Start-Process -FilePath $proxyPy -ArgumentList $pargs -WorkingDirectory $Root `
                -RedirectStandardOutput $pout -RedirectStandardError $perr -PassThru -WindowStyle Hidden
            $pproc.Id | Set-Content -Encoding ASCII (Join-Path $logDir 'alias-proxy.pid')
            $pok = $false
            foreach ($i in 1..30) {
                Start-Sleep -Seconds 1
                if (Test-Url $proxyHealth) { $pok = $true; break }
                if ($pproc.HasExited) { throw "Alias proxy exited early. See $perr" }
            }
            if (-not $pok) { throw "Alias proxy not healthy at $proxyHealth (logs: $perr)" }
            Write-Host "Alias proxy healthy: http://127.0.0.1:$ProxyPort/v1" -ForegroundColor Green
        }
    }
}

Write-Host "`nGoku backend ready." -ForegroundColor Green
Write-Host "  Backend: llama.cpp  $($profileCfg.Label)"
Write-Host "  OpenAI:  http://127.0.0.1:$BackendPort/v1"
if (-not $SkipProxy) { Write-Host "  Proxy:   http://127.0.0.1:$ProxyPort/v1  (goku-* aliases)" }
Write-Host "  Confirm log shows reasoning/thinking off."
