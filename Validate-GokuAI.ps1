[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [switch]$RequireBackend
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'
$failed = 0

function Ok($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Bad($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; $script:failed++ }
function Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }

Write-Host "Validating GokuAI at $Root" -ForegroundColor Cyan

$grok = Join-Path $Root 'grok-home\bin\grok.exe'
if (Test-Path $grok) { Ok "grok.exe" } else { Bad "missing $grok" }

$config = Join-Path $Root 'grok-home\config.toml'
if (Test-Path $config) {
    $text = Get-Content -Raw $config
    if ($text -match 'default\s*=\s*"grok-4\.5"') { Ok "parent default grok-4.5" } else { Bad "config default is not grok-4.5" }
    if ($text -match '\[model\.goku-code\]') { Ok "goku-code model block" } else { Bad "missing [model.goku-code]" }
    if ($text -match '11437|8888') { Ok "local backend URL referenced" } else { Warn "8888/11437 not found in config" }
    if ($text -match 'kat-reap50|llama\.cpp') { Ok "llama.cpp / kat-reap50 referenced" } else { Warn "config may still describe Mia/EXL3" }
    if ($text -match '(?m)^\s*general-purpose\s*=\s*"goku-code"\s*$') { Ok "general-purpose -> goku-code" } else { Bad "subagents.models general-purpose not goku-code" }
}
else { Bad "missing config.toml" }

foreach ($p in @(
    'templates\config.toml.template',
    'scripts\goku_alias_proxy.py',
    'models\code-selection.json',
    'runtime\goku-routing.json',
    'Start-GokuBackend.ps1',
    'Start-GokuAI.ps1',
    'Switch-GokuWorker.ps1',
    'Reset-GokuBackend.ps1',
    'Repair-GokuAI.ps1',
    'Install-GokuAI.ps1',
    'runtime\llama.cpp\llama-server.exe',
    'runtime\llama.cpp\ggml-cuda.dll'
)) {
    $full = Join-Path $Root $p
    if (Test-Path $full) { Ok $p } else { Bad "missing $p" }
}

$cudart = Join-Path $Root 'runtime\llama.cpp\cudart64_12.dll'
$cublas = Join-Path $Root 'runtime\llama.cpp\cublas64_12.dll'
if ((Test-Path $cudart) -and (Test-Path $cublas)) { Ok "CUDA 12 redistributables beside llama-server" }
else { Warn "CUDA 12 DLLs missing - run Install-GokuAI.ps1 -Repair (GPU offload will fail)" }

$q6 = Join-Path $Root 'models\kat-reap50-Q6_K.gguf'
$q8 = Join-Path $Root 'models\kat-reap50-Q8_0.gguf'
if (Test-Path $q6) {
    $gb = [math]::Round((Get-Item $q6).Length / 1GB, 2)
    if ($gb -ge 10) { Ok "q6 GGUF ${gb} GB" } else { Warn "q6 GGUF unexpectedly small (${gb} GB)" }
} else { Warn "missing $q6" }
if (Test-Path $q8) {
    $gb = [math]::Round((Get-Item $q8).Length / 1GB, 2)
    Ok "q8 GGUF ${gb} GB (optional)"
} else { Warn "optional q8 GGUF missing" }

if (Test-Path (Join-Path $Root 'Install-MiaExl3Kit.ps1')) {
    Warn "Install-MiaExl3Kit.ps1 still present (DEPRECATED for default workers)"
}
if (Test-Path (Join-Path $Root 'DEPRECATED-MIA-EXL3-WORKERS.md')) {
    Ok "Mia deprecation note present"
}

try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8888/health' -TimeoutSec 3
    Ok "llama-server health :8888"
}
catch {
    if ($RequireBackend) { Bad "llama-server not reachable on :8888" } else { Warn "llama-server not running on :8888" }
}

try {
    $proxy = Invoke-RestMethod -Uri 'http://127.0.0.1:11437/health' -TimeoutSec 2
    Ok "alias proxy health :11437"
    if ($proxy.upstream_model) { Ok "upstream model: $($proxy.upstream_model)" }
}
catch {
    if ($RequireBackend) { Bad "alias proxy not reachable on :11437" } else { Warn "alias proxy not running on :11437" }
}

if ($failed -gt 0) {
    Write-Host "`nValidation FAILED ($failed)." -ForegroundColor Red
    Write-Host "Repair: .\Repair-GokuAI.ps1"
    exit 1
}
Write-Host "`nValidation OK." -ForegroundColor Green
exit 0
