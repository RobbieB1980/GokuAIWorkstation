[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [ValidateSet('q6', 'q8')]
    [string]$Profile = 'q6',
    [int]$BackendPort = 8888,
    [int]$ProxyPort = 11437,
    # 0 = primary start without MoE CPU offload; on OOM/early exit retry with NCpuMoeFallback.
    [int]$NCpuMoe = 0,
    [int]$NCpuMoeFallback = 8,
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

function Test-LooksLikeOom([string]$StderrPath, [string]$StdoutPath) {
    $chunks = @()
    foreach ($p in @($StderrPath, $StdoutPath)) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            try { $chunks += Get-Content -LiteralPath $p -Tail 80 -ErrorAction SilentlyContinue } catch { }
        }
    }
    $text = ($chunks -join "`n")
    return [bool]($text -match '(?i)out of memory|cudaMalloc|failed to allocate|ggml_backend_cuda|CUDA error|OOM|insufficient memory|failed to load model')
}

function Get-LlamaArgList {
    param(
        [Parameter(Mandatory)]$ProfileCfg,
        [Parameter(Mandatory)][int]$Port,
        [int]$NCpuMoeLayers = 0
    )
    $args = @(
        '-m', $ProfileCfg.ModelPath,
        '--alias', 'goku-code,goku-fast,goku-heavy,goku-research,goku-reviewer',
        '--host', '127.0.0.1',
        '--port', "$Port",
        '--ctx-size', "$($ProfileCfg.CtxSize)",
        '--gpu-layers', 'all',
        '--flash-attn', 'on',
        '--cache-type-k', 'q8_0',
        '--cache-type-v', 'q8_0',
        '--parallel', '1',
        '--batch-size', "$($ProfileCfg.BatchSize)",
        '--ubatch-size', "$($ProfileCfg.UBatchSize)",
        '--threads', '16',
        '--jinja',
        '--reasoning', 'off',
        '--reasoning-budget', '0',
        '--no-reasoning-preserve',
        '--temp', "$($ProfileCfg.Temp)",
        '--top-p', "$($ProfileCfg.TopP)",
        '--top-k', "$($ProfileCfg.TopK)",
        '--min-p', "$($ProfileCfg.MinP)",
        '--presence-penalty', "$($ProfileCfg.PresencePenalty)"
    )
    if ($NCpuMoeLayers -gt 0) {
        $args += @('--n-cpu-moe', "$NCpuMoeLayers")
    }
    return $args
}

function Start-LlamaServerAttempt {
    param(
        [Parameter(Mandatory)][string]$LlamaServer,
        [Parameter(Mandatory)][string]$LlamaDir,
        [Parameter(Mandatory)]$ArgList,
        [Parameter(Mandatory)][string]$StdoutPath,
        [Parameter(Mandatory)][string]$StderrPath,
        [Parameter(Mandatory)][string]$PidPath,
        [Parameter(Mandatory)][string]$HealthUrl,
        [int]$WaitSeconds = 240
    )

    if (Test-Path -LiteralPath $StdoutPath) { Remove-Item -LiteralPath $StdoutPath -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $StderrPath) { Remove-Item -LiteralPath $StderrPath -Force -ErrorAction SilentlyContinue }

    $proc = Start-Process -FilePath $LlamaServer -ArgumentList $ArgList -WorkingDirectory $LlamaDir `
        -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath -PassThru -WindowStyle Hidden
    $proc.Id | Set-Content -Encoding ASCII $PidPath
    Write-Host "Started PID $($proc.Id). Waiting for health (model load can take a minute)..."

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (Test-Url $HealthUrl) {
            return [pscustomobject]@{ Ok = $true; Process = $proc; Oom = $false; ExitCode = 0 }
        }
        if ($proc.HasExited) {
            $oom = Test-LooksLikeOom -StderrPath $StderrPath -StdoutPath $StdoutPath
            return [pscustomobject]@{ Ok = $false; Process = $proc; Oom = $oom; ExitCode = $proc.ExitCode }
        }
    }

    # Timed out still running — treat as failure (likely hung alloc).
    try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch { }
    $oom = Test-LooksLikeOom -StderrPath $StderrPath -StdoutPath $StdoutPath
    return [pscustomobject]@{ Ok = $false; Process = $proc; Oom = $oom; ExitCode = -1 }
}

$llamaDir = Join-Path $Root 'runtime\llama.cpp'
$llamaServer = Join-Path $llamaDir 'llama-server.exe'
$modelsRoot = Join-Path $Root 'models'
$logDir = Join-Path $Root 'logs\backend'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path -LiteralPath $llamaServer)) {
    throw "llama-server missing: $llamaServer"
}

# Preferred kat / goku-code launch profile (Q6 @ 64k + samplers).
# Path is always C:\gokuai\models\... (not C:\gokai\...).
$profiles = @{
    q6 = [ordered]@{
        ModelPath       = Join-Path $modelsRoot 'kat-reap50-Q6_K.gguf'
        CtxSize         = 65536
        BatchSize       = 2048
        UBatchSize      = 1024
        Temp            = '0.7'
        TopP            = '0.8'
        TopK            = '20'
        MinP            = '0'
        PresencePenalty = '1.5'
        Label           = 'kat-reap50-Q6_K @ 64k (default goku-code)'
    }
    q8 = [ordered]@{
        ModelPath       = Join-Path $modelsRoot 'kat-reap50-Q8_0.gguf'
        CtxSize         = 16384
        BatchSize       = 1024
        UBatchSize      = 512
        Temp            = '0.7'
        TopP            = '0.8'
        TopK            = '20'
        MinP            = '0'
        PresencePenalty = '1.5'
        Label           = 'kat-reap50-Q8_0 @ 16k (quality A/B)'
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
    foreach ($i in 1..30) {
        if (-not (Test-Url $backendHealth)) { break }
        Start-Sleep -Seconds 1
    }
}

$stdout = Join-Path $logDir 'llama-server.stdout.log'
$stderr = Join-Path $logDir 'llama-server.stderr.log'
$pidPath = Join-Path $logDir 'llama-server.pid'
$usedNCpuMoe = [Math]::Max(0, $NCpuMoe)

# Persist active backend profile for Switch-GokuWorker / docs.
$active = [ordered]@{
    backend            = 'llama.cpp'
    profile            = $Profile
    label              = $profileCfg.Label
    model_path         = $profileCfg.ModelPath
    alias              = 'goku-code,goku-fast,goku-heavy,goku-research,goku-reviewer'
    host               = '127.0.0.1'
    port               = $BackendPort
    proxy_port         = $ProxyPort
    ctx_size           = $profileCfg.CtxSize
    batch_size         = $profileCfg.BatchSize
    ubatch_size        = $profileCfg.UBatchSize
    temp               = $profileCfg.Temp
    top_p              = $profileCfg.TopP
    top_k              = $profileCfg.TopK
    min_p              = $profileCfg.MinP
    presence_penalty   = $profileCfg.PresencePenalty
    n_cpu_moe          = $usedNCpuMoe
    n_cpu_moe_fallback = $NCpuMoeFallback
    reasoning          = 'off'
    reasoning_budget   = 0
    enable_thinking    = $false
    deprecated_mia     = $true
    updated            = (Get-Date).ToString('o')
}
$active | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $modelsRoot 'active-worker.json') -Encoding UTF8

if (Test-Url $backendHealth) {
    Write-Host "llama-server already healthy at $backendHealth"
}
else {
    Write-Step "Starting llama-server ($($profileCfg.Label)) on :$BackendPort"
    $env:PATH = "$llamaDir;" + $env:PATH

    $argList = Get-LlamaArgList -ProfileCfg $profileCfg -Port $BackendPort -NCpuMoeLayers $usedNCpuMoe
    if ($usedNCpuMoe -gt 0) {
        Write-Host "Using --n-cpu-moe $usedNCpuMoe on primary start."
    }
    $attempt = Start-LlamaServerAttempt -LlamaServer $llamaServer -LlamaDir $llamaDir -ArgList $argList `
        -StdoutPath $stdout -StderrPath $stderr -PidPath $pidPath -HealthUrl $backendHealth

    if (-not $attempt.Ok) {
        $canFallback = ($NCpuMoeFallback -gt 0) -and ($usedNCpuMoe -lt $NCpuMoeFallback)
        $shouldRetry = $canFallback -and ($attempt.Oom -or $attempt.ExitCode -ne 0)
        if ($shouldRetry) {
            Write-Host "Primary start failed (exit $($attempt.ExitCode); oom-like=$($attempt.Oom)). Retrying with --n-cpu-moe $NCpuMoeFallback ..." -ForegroundColor Yellow
            try { Stop-Process -Id $attempt.Process.Id -Force -ErrorAction SilentlyContinue } catch { }
            Start-Sleep -Seconds 2
            $usedNCpuMoe = $NCpuMoeFallback
            $argList = Get-LlamaArgList -ProfileCfg $profileCfg -Port $BackendPort -NCpuMoeLayers $usedNCpuMoe
            $attempt = Start-LlamaServerAttempt -LlamaServer $llamaServer -LlamaDir $llamaDir -ArgList $argList `
                -StdoutPath $stdout -StderrPath $stderr -PidPath $pidPath -HealthUrl $backendHealth
        }
    }

    if (-not $attempt.Ok) {
        throw "llama-server failed to become healthy at $backendHealth (exit $($attempt.ExitCode); n-cpu-moe=$usedNCpuMoe). See $stderr / $stdout"
    }

    # Refresh active-worker with the MoE setting that actually worked.
    $active.n_cpu_moe = $usedNCpuMoe
    $active.updated = (Get-Date).ToString('o')
    $active | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $modelsRoot 'active-worker.json') -Encoding UTF8

    Write-Host "llama-server healthy (n-cpu-moe=$usedNCpuMoe)." -ForegroundColor Green
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
Write-Host "  ctx=$($profileCfg.CtxSize) batch=$($profileCfg.BatchSize) ubatch=$($profileCfg.UBatchSize) n-cpu-moe=$usedNCpuMoe"
Write-Host "  samplers: temp=$($profileCfg.Temp) top_p=$($profileCfg.TopP) top_k=$($profileCfg.TopK) min_p=$($profileCfg.MinP) presence_penalty=$($profileCfg.PresencePenalty)"
Write-Host "  Confirm log shows reasoning/thinking off."
