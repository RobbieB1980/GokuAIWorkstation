[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [ValidateRange(4096, 65536)][int]$ContextSize = 16384,
    [ValidateSet('4', '6', '8', '8,4', 'fp8', 'nvfp4')][string]$CacheQuant = '8'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$envFile = Join-Path $Root 'runtime\mia-kit\.env'
$python = Join-Path $Root 'runtime\mia-kit\.venv\Scripts\python.exe'
$stage2 = Join-Path $Root 'scripts\benchmark_stage2.py'
$stage3 = Join-Path $Root 'scripts\benchmark_stage3.py'
$index = Join-Path $Root 'DataIndex\goku-data.db'
$reset = Join-Path $Root 'Reset-GokuBackend.ps1'
$start = Join-Path $Root 'Start-GokuBackend.ps1'

$plan = @(
    [pscustomobject]@{
        key = 'current_heavy_dflash_nothink'
        label = 'Qwen3.8-27B 3.5bpw + DFlash2 (thinking off)'
        path = Join-Path $Root 'models\EXL3\qwen3.8-27b-exl3-3.5bpw'
        draft = 'dflash2'
        draftPath = Join-Path $Root 'models\EXL3\qwen3.8-27b-dflash2-exl3-5bpw'
    },
    [pscustomobject]@{
        key = 'kat_coder_v25_nothink'
        label = 'KAT-Coder V2.5 4bpw (thinking off)'
        path = Join-Path $Root 'models\Candidates\KAT-Coder-V2.5-Dev-MTP-exl3-4bpw'
        draft = 'none'
        draftPath = 'none'
    },
    [pscustomobject]@{
        key = 'sera_32b_nothink'
        label = 'SERA-32B 4bpw (thinking off)'
        path = Join-Path $Root 'models\Candidates\SERA-32B-exl3-4bpw'
        draft = 'none'
        draftPath = 'none'
    }
)

foreach ($required in @($envFile, $python, $stage2, $stage3, $index, $reset, $start)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing: $required" }
}
foreach ($model in $plan) {
    if (-not (Test-Path -LiteralPath $model.path)) { throw "Missing model: $($model.path)" }
    if ($model.draftPath -ne 'none' -and -not (Test-Path -LiteralPath $model.draftPath)) {
        throw "Missing draft model: $($model.draftPath)"
    }
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$outputDir = Join-Path $Root "benchmarks\thinking-off-retests-$stamp"
$partsDir = Join-Path $outputDir 'parts'
$summaryPath = Join-Path $outputDir 'thinking-off-comparison.json'
New-Item -ItemType Directory -Path $partsDir -Force | Out-Null

$savedEnvFile = [IO.File]::ReadAllText($envFile)
$savedThinking = $env:GOKU_ENABLE_THINKING
$utf8 = New-Object Text.UTF8Encoding($false)
$result = [ordered]@{
    schema = 'goku-thinking-off-retests-v1'
    created = (Get-Date).ToString('o')
    context_size = $ContextSize
    cache_quant = $CacheQuant
    enable_thinking = $false
    models = [ordered]@{}
}

function Set-EnvKey($lines, $key, $value) {
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match ('^\s*' + [regex]::Escape($key) + '\s*=')) {
            $found = $true
            "$key=$value"
        } else { $line }
    }
    if (-not $found) { $updated += "$key=$value" }
    return ,@($updated)
}

function Configure-Model($model) {
    $lines = Get-Content -LiteralPath $envFile
    $lines = Set-EnvKey $lines 'MODEL_DIR' ($model.path -replace '\\', '/')
    $lines = Set-EnvKey $lines 'DRAFT' $model.draft
    $lines = Set-EnvKey $lines 'DRAFT_DIR' ($model.draftPath -replace '\\', '/')
    $lines = Set-EnvKey $lines 'CONTEXT_SIZE' "$ContextSize"
    $lines = Set-EnvKey $lines 'CACHE_QUANT' $CacheQuant
    [IO.File]::WriteAllLines($envFile, $lines, $utf8)
}

try {
    $env:GOKU_ENABLE_THINKING = 'false'
    foreach ($model in $plan) {
        Write-Host "`n=== Thinking-off retest: $($model.label) ===" -ForegroundColor Cyan
        $entry = [ordered]@{
            label = $model.label
            path = $model.path
            draft = $model.draft
            status = 'pending'
            started = (Get-Date).ToString('o')
        }
        $result.models[$model.key] = $entry
        try {
            & $reset -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
            Configure-Model $model
            & $start -Root $Root -ForceRestart

            $stage2Path = Join-Path $partsDir "$($model.key)-stage2.json"
            & $python $stage2 --output $stage2Path --report-as $model.key --worker-label $model.label
            if ($LASTEXITCODE -ne 0) { throw "Stage 2 exited with code $LASTEXITCODE" }

            $stage3Path = Join-Path $partsDir "$($model.key)-stage3.json"
            & $python $stage3 --index $index --output $stage3Path --report-as $model.key --worker-label $model.label
            if ($LASTEXITCODE -ne 0) { throw "Stage 3 exited with code $LASTEXITCODE" }

            $stage2Report = Get-Content -LiteralPath $stage2Path -Raw | ConvertFrom-Json
            $stage2Model = $stage2Report.models.($model.key)
            $stage3Report = Get-Content -LiteralPath $stage3Path -Raw | ConvertFrom-Json
            $entry.status = 'passed'
            $entry.stage2 = [ordered]@{
                quality = $stage2Model.quality_score
                success = $stage2Model.success_rate
                mean_seconds = $stage2Model.mean_seconds
                truncated = @($stage2Model.tests | Where-Object { $_.truncated }).Count
            }
            $entry.stage3 = [ordered]@{
                production = $stage3Report.modes.production
                oracle = $stage3Report.modes.oracle
                truncated = @($stage3Report.tests | Where-Object { $_.truncated }).Count
            }
            $entry.files = [ordered]@{ stage2 = $stage2Path; stage3 = $stage3Path }
        } catch {
            $entry.status = 'failed'
            $entry.error = $_.Exception.Message
            throw
        } finally {
            & $reset -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
            $entry.completed = (Get-Date).ToString('o')
            $result | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
        }
    }
} finally {
    [IO.File]::WriteAllText($envFile, $savedEnvFile, $utf8)
    if ($null -eq $savedThinking) {
        Remove-Item Env:GOKU_ENABLE_THINKING -ErrorAction SilentlyContinue
    } else {
        $env:GOKU_ENABLE_THINKING = $savedThinking
    }
    & $reset -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
}

$passed = @($result.models.Values | Where-Object { $_.status -eq 'passed' }).Count
$result.summary = [ordered]@{ passed = $passed; failed = $plan.Count - $passed; total = $plan.Count }
$result | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
Write-Host "Thinking-off retests complete: $summaryPath" -ForegroundColor Green
