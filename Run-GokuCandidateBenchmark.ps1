[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [string]$KnowledgeRoot = 'C:\rmblocal_llm\knowledge',
    [ValidateSet('all','kat_coder_v25','sera_32b','devstral_small_2','qwen25_coder_32b')]
    [string[]]$Models = @('all'),
    [ValidateRange(4096,65536)][int]$ContextSize = 16384,
    [ValidateSet('4','6','8','8,4','fp8','nvfp4')][string]$CacheQuant = '8'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$candidateManifestPath = Join-Path $Root 'models\Candidates\candidate-manifest.json'
$envPath = Join-Path $Root 'runtime\mia-kit\.env'
$python = Join-Path $Root 'runtime\mia-kit\.venv\Scripts\python.exe'
$benchmarkScript = Join-Path $Root 'scripts\benchmark_models.py'
$resetScript = Join-Path $Root 'Reset-GokuBackend.ps1'
$startScript = Join-Path $Root 'Start-GokuBackend.ps1'

foreach ($required in @($candidateManifestPath,$envPath,$python,$benchmarkScript,$resetScript,$startScript)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required file missing: $required" }
}

$parsedCandidates = Get-Content -LiteralPath $candidateManifestPath -Raw | ConvertFrom-Json
$allCandidates = @()
foreach ($parsedCandidate in $parsedCandidates) {
    $allCandidates += $parsedCandidate
}
if ($Models -contains 'all') { $selected = $allCandidates }
else { $selected = @($allCandidates | Where-Object { $Models -contains $_.key }) }
if ($selected.Count -eq 0) { throw 'No candidates matched -Models.' }

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$runDir = Join-Path $Root "benchmarks\candidate-fit-$stamp"
$partsDir = Join-Path $runDir 'parts'
New-Item -ItemType Directory -Path $partsDir -Force | Out-Null
$reportPath = Join-Path $runDir 'candidate-benchmark.json'
$originalEnv = [IO.File]::ReadAllText($envPath)
$utf8 = New-Object Text.UTF8Encoding $false

function Get-GpuSnapshot {
    try {
        $line = (& nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
        if (-not $line) { return $null }
        $p = $line -split '\s*,\s*'
        return [ordered]@{ name=$p[0]; total_mib=[int]$p[1]; used_mib=[int]$p[2]; free_mib=[int]$p[3]; utilization_percent=[int]$p[4] }
    } catch { return $null }
}

function Set-EnvValue([string[]]$Lines,[string]$Name,[string]$Value) {
    $found = $false
    $result = foreach ($line in $Lines) {
        if ($line -match ("^\s*" + [regex]::Escape($Name) + "\s*=")) { $found=$true; "$Name=$Value" } else { $line }
    }
    if (-not $found) { $result += "$Name=$Value" }
    return @($result)
}

function Configure-Candidate([string]$ModelPath) {
    $lines = Get-Content -LiteralPath $envPath
    $lines = Set-EnvValue $lines 'MODEL_DIR' ($ModelPath -replace '\\','/')
    $lines = Set-EnvValue $lines 'DRAFT' 'none'
    $lines = Set-EnvValue $lines 'DRAFT_DIR' 'none'
    $lines = Set-EnvValue $lines 'CONTEXT_SIZE' "$ContextSize"
    $lines = Set-EnvValue $lines 'CACHE_QUANT' $CacheQuant
    [IO.File]::WriteAllLines($envPath,$lines,$utf8)
}

function Test-Health([int]$TimeoutSeconds=300) {
    $deadline=(Get-Date).AddSeconds($TimeoutSeconds)
    while((Get-Date) -lt $deadline) {
        try {
            $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8888/health' -UseBasicParsing -TimeoutSec 4
            if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ return $true }
        } catch {}
        Start-Sleep -Seconds 2
    }
    return $false
}

$result = [ordered]@{
    schema='goku-candidate-benchmark-v1'
    created=(Get-Date).ToString('o')
    context_size=$ContextSize
    cache_quant=$CacheQuant
    knowledge_root=$KnowledgeRoot
    candidates=[ordered]@{}
}

try {
    foreach($candidate in $selected) {
        $key=[string]$candidate.key
        $entry=[ordered]@{
            repository=$candidate.repository; revision=$candidate.revision; path=$candidate.path
            status='pending'; started=(Get-Date).ToString('o'); gpu_before=$null; gpu_after=$null
        }
        $result.candidates[$key]=$entry
        Write-Host "`n=== Candidate: $key ===" -ForegroundColor Cyan
        try {
            if (-not (Test-Path -LiteralPath $candidate.path)) { throw "Model directory missing: $($candidate.path)" }
            & $resetScript -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
            $entry.gpu_before=Get-GpuSnapshot
            Configure-Candidate $candidate.path
            & $startScript -Root $Root -ForceRestart
            if (-not (Test-Health 300)) { throw 'Mia backend did not become healthy within 300 seconds.' }

            $partPath=Join-Path $partsDir "$key.json"
            & $python $benchmarkScript --url 'http://127.0.0.1:11437/v1/chat/completions' --output $partPath --root $KnowledgeRoot --goku-root $Root --suite heavy --models goku-heavy --report-as $key --worker-label "$key candidate"
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $partPath)) { throw "Benchmark engine failed with exit code $LASTEXITCODE" }
            $part=Get-Content -LiteralPath $partPath -Raw | ConvertFrom-Json
            $block=$part.models.PSObject.Properties[$key].Value
            $entry.status='passed'
            $entry.quality_score=$block.quality_score
            $entry.success_rate=$block.success_rate
            $entry.mean_seconds=$block.mean_seconds
            $entry.result_file=$partPath
        } catch {
            $entry.status='failed'
            $entry.error=$_.Exception.Message
            $stderr=Join-Path $Root 'logs\backend\mia-server.stderr.log'
            if(Test-Path -LiteralPath $stderr){ $entry.backend_error_tail=@(Get-Content -LiteralPath $stderr -Tail 30) }
            Write-Warning "$key failed: $($_.Exception.Message)"
        } finally {
            & $resetScript -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
            $entry.gpu_after=Get-GpuSnapshot
            $entry.completed=(Get-Date).ToString('o')
            $result | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $reportPath -Encoding UTF8
        }
    }
} finally {
    [IO.File]::WriteAllText($envPath,$originalEnv,$utf8)
    & $resetScript -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
}

$passed=@($result.candidates.Values | Where-Object {$_.status -eq 'passed'}).Count
$failed=@($result.candidates.Values | Where-Object {$_.status -eq 'failed'}).Count
$result.summary=[ordered]@{passed=$passed;failed=$failed;total=$selected.Count;gpu_final=Get-GpuSnapshot}
$result | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Host "`nCandidate suite finished: $passed passed, $failed failed" -ForegroundColor $(if($failed){'Yellow'}else{'Green'})
Write-Host "Report: $reportPath"
if($failed){exit 1}
