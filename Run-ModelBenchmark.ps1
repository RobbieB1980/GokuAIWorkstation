[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [string]$KnowledgeRoot = 'C:\rmblocal_llm\knowledge',
    [ValidateSet('all', 'fast', 'heavy', 'heavy-dflash')]
    [string]$Workers = 'all',
    [switch]$SkipRestore
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Test-HttpOk([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300)
    } catch { return $false }
}

function Wait-BackendHealthy([int]$TimeoutSec = 180) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ((Test-HttpOk 'http://127.0.0.1:8888/health') -and (Test-HttpOk 'http://127.0.0.1:11437/health')) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw 'Backend/proxy not healthy within timeout'
}

$python = Join-Path $Root 'runtime\mia-kit\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Missing Python venv: $python" }
$benchScript = Join-Path $Root 'scripts\benchmark_models.py'
if (-not (Test-Path $benchScript)) { throw "Missing $benchScript" }
if (-not (Test-Path $KnowledgeRoot)) {
    Write-Warning "Knowledge root missing ($KnowledgeRoot); mapping tests will use embedded fallback evidence."
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$benchDir = Join-Path $Root 'benchmarks'
New-Item -ItemType Directory -Force -Path $benchDir | Out-Null
$out = Join-Path $benchDir ("model_benchmark_{0}.json" -f $stamp)
$partialDir = Join-Path $benchDir ("model_benchmark_{0}_parts" -f $stamp)
New-Item -ItemType Directory -Force -Path $partialDir | Out-Null

$plan = @()
if ($Workers -in @('all', 'fast')) {
    $plan += @{ worker = 'fast'; alias = 'goku-code'; suite = 'coder'; reportAs = 'goku-code'; label = 'fast coder EXL3 4.0bpw' }
}
if ($Workers -in @('all', 'heavy')) {
    $plan += @{ worker = 'heavy'; alias = 'goku-heavy'; suite = 'heavy'; reportAs = 'goku-heavy'; label = 'heavy MTP EXL3 3.5bpw' }
}
if ($Workers -in @('all', 'heavy-dflash')) {
    $plan += @{ worker = 'heavy-dflash'; alias = 'goku-heavy'; suite = 'heavy'; reportAs = 'goku-heavy-dflash'; label = 'heavy DFlash2 draft' }
}

$merged = [ordered]@{
    schema = 'rb-model-benchmark-v2.2'
    product = 'GokuAI'
    created = (Get-Date).ToString('o')
    knowledge_root = $KnowledgeRoot
    goku_root = $Root
    scoring = '90% grounded/factual task criteria, 10% JSON format; latency reported separately and never auto-promotes roles'
    workers_run = @($plan | ForEach-Object { $_.worker })
    models = [ordered]@{}
    parts = @()
}

Write-Step 'Reset GPU / start Goku backend before benchmark'
& (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
& (Join-Path $Root 'Start-GokuBackend.ps1') -Root $Root
Wait-BackendHealthy

foreach ($step in $plan) {
    Write-Step ("Benchmark worker={0} alias={1} suite={2}" -f $step.worker, $step.alias, $step.suite)
    Write-Host "Pre-load GPU flush for $($step.worker)..." -ForegroundColor DarkCyan
    & (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
    & (Join-Path $Root 'Switch-GokuWorker.ps1') -Root $Root -Worker $step.worker -Restart
    Wait-BackendHealthy

    $partOut = Join-Path $partialDir ("{0}.json" -f $step.reportAs)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python $benchScript `
        --url 'http://127.0.0.1:11437/v1/chat/completions' `
        --output $partOut `
        --root $KnowledgeRoot `
        --goku-root $Root `
        --suite $step.suite `
        --models $step.alias `
        --report-as $step.reportAs `
        --worker-label $step.label
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($code -ne 0 -or -not (Test-Path $partOut)) {
        throw "Benchmark failed for worker=$($step.worker) (exit $code)"
    }

    $part = Get-Content -Raw $partOut | ConvertFrom-Json
    foreach ($prop in $part.models.PSObject.Properties) {
        $merged.models[$prop.Name] = $prop.Value
    }
    $merged.parts += $partOut
    if (-not $merged.Contains('routing_recommendation')) {
        $rrProp = $part.PSObject.Properties['routing_recommendation']
        if ($null -ne $rrProp) {
            $merged['routing_recommendation'] = $rrProp.Value
        }
    }

    Write-Host "Post-test GPU flush after $($step.worker)..." -ForegroundColor DarkCyan
    & (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
}

$summary = [ordered]@{}
foreach ($name in @($merged.models.Keys)) {
    $m = $merged.models[$name]
    $label = $null
    if ($null -ne $m.PSObject.Properties['worker_label']) { $label = $m.worker_label }
    $summary[$name] = [ordered]@{
        quality = $m.quality_score
        success = $m.success_rate
        mean_seconds = $m.mean_seconds
        worker_label = $label
    }
}
$merged.summary = $summary
$merged | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 $out

Write-Host "`nBenchmark report: $out" -ForegroundColor Green
Write-Host ($summary | ConvertTo-Json -Depth 6)

if (-not $SkipRestore) {
    Write-Step 'Restore default fast worker'
    try {
        & (Join-Path $Root 'Start-GokuBackend.ps1') -Root $Root
        & (Join-Path $Root 'Switch-GokuWorker.ps1') -Root $Root -Worker fast -Restart
        Wait-BackendHealthy
    } catch {
        Write-Warning $_.Exception.Message
    }
}

Write-Host "Done. Report: $out" -ForegroundColor Green
exit 0
