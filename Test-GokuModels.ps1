[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [switch]$SkipExl3,
    [switch]$SkipAux,
    [switch]$KeepHeavyLoaded
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

function Invoke-Exl3Chat([string]$Alias, [string]$Needle) {
    $bodyObj = @{
        model = $Alias
        messages = @(@{ role = 'user'; content = "Reply with exactly: $Needle" })
        max_tokens = 64
        temperature = 0
    }
    $body = $bodyObj | ConvertTo-Json -Depth 6 -Compress
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:11437/v1/chat/completions' -Method Post -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 300
    $sw.Stop()
    $content = [string]$resp.choices[0].message.content
    return @{
        alias = $Alias
        content = $content
        seconds = [math]::Round($sw.Elapsed.TotalSeconds, 2)
        pass = ($content -match [regex]::Escape($Needle))
        upstream_model = [string]$resp.model
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$reportDir = Join-Path $Root "benchmarks\model-verify-$stamp"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$results = @()

Write-Step 'Ensure backend'
& (Join-Path $Root 'Start-GokuBackend.ps1') -Root $Root
if (-not (Test-HttpOk 'http://127.0.0.1:8888/health')) { throw 'Mia backend not healthy' }
if (-not (Test-HttpOk 'http://127.0.0.1:11437/health')) {
    & (Join-Path $Root 'scripts\restart_alias_proxy.ps1')
    if (-not (Test-HttpOk 'http://127.0.0.1:11437/health')) { throw 'Alias proxy not healthy' }
}

if (-not $SkipExl3) {
    $cases = @(
        @{ worker = 'fast'; alias = 'goku-code'; needle = 'GOKU_FAST_OK' },
        @{ worker = 'heavy'; alias = 'goku-heavy'; needle = 'GOKU_HEAVY_OK' },
        @{ worker = 'heavy-dflash'; alias = 'goku-heavy'; needle = 'GOKU_DFLASH_OK' }
    )
    foreach ($c in $cases) {
        Write-Step "EXL3 worker=$($c.worker) alias=$($c.alias)"
        try {
            Write-Host "Pre-load GPU flush for $($c.worker)..." -ForegroundColor DarkCyan
            & (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
            & (Join-Path $Root 'Switch-GokuWorker.ps1') -Root $Root -Worker $c.worker -Restart
            Start-Sleep -Seconds 2
            if (-not (Test-HttpOk 'http://127.0.0.1:8888/health')) { throw 'backend unhealthy after switch' }
            if (-not (Test-HttpOk 'http://127.0.0.1:11437/health')) {
                & (Join-Path $Root 'scripts\restart_alias_proxy.ps1')
            }
            $chat = Invoke-Exl3Chat -Alias $c.alias -Needle $c.needle
            $item = [ordered]@{
                suite = 'exl3'
                worker = $c.worker
                alias = $c.alias
                status = $(if ($chat.pass) { 'pass' } else { 'fail' })
                content = $chat.content
                seconds = $chat.seconds
                upstream_model = $chat.upstream_model
            }
            if (-not $chat.pass) { $item.error = "expected needle '$($c.needle)' in content" }
            $results += [pscustomobject]$item
            Write-Host ("{0} {1} in {2}s -> {3}" -f $item.status.ToUpper(), $c.worker, $chat.seconds, $chat.content)

            # Flush again after each EXL3 test so the next model starts clean.
            Write-Host "Post-test GPU flush after $($c.worker)..." -ForegroundColor DarkCyan
            & (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
        } catch {
            $results += [pscustomobject]@{
                suite = 'exl3'
                worker = $c.worker
                alias = $c.alias
                status = 'fail'
                error = $_.Exception.Message
            }
            Write-Host ("FAIL {0}: {1}" -f $c.worker, $_.Exception.Message) -ForegroundColor Red
            & (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
        }
    }
}

$auxOut = Join-Path $reportDir 'aux-models.json'
if (-not $SkipAux) {
    Write-Step 'Free GPU for aux model tests'
    & (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
    Start-Sleep -Seconds 2

    Write-Step 'Install aux deps if needed (sentence-transformers / torchvision)'
    $py = Join-Path $Root 'runtime\mia-kit\.venv\Scripts\python.exe'
    # Native stderr must not terminate under $ErrorActionPreference=Stop.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    cmd.exe /c "`"$py`" -m pip install -q sentence-transformers qwen-vl-utils" | Out-Host
    cmd.exe /c "`"$py`" -c `"import torchvision`" 2>nul"
    if ($LASTEXITCODE -ne 0) {
        cmd.exe /c "`"$py`" -m pip install -q torchvision --index-url https://download.pytorch.org/whl/cu130" | Out-Host
    }

    Write-Step 'Aux embedding/rerank/VL verification'
    $auxScript = Join-Path $Root 'scripts\verify_aux_models.py'
    $auxCode = 0
    cmd.exe /c "`"$py`" `"$auxScript`" --root `"$Root\models`" --device cuda --out `"$auxOut`""
    $auxCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if (Test-Path $auxOut) {
        $aux = Get-Content -Raw $auxOut | ConvertFrom-Json
        foreach ($r in $aux.results) {
            $err = $null
            if ($null -ne $r.PSObject.Properties['error']) { $err = [string]$r.error }
            $kind = $null
            if ($null -ne $r.PSObject.Properties['kind']) { $kind = [string]$r.kind }
            $results += [pscustomobject]@{
                suite = 'aux'
                worker = [string]$r.name
                alias = $kind
                status = [string]$r.status
                detail = ($r | ConvertTo-Json -Compress)
                error = $err
            }
        }
    } else {
        $results += [pscustomobject]@{ suite = 'aux'; worker = 'aux-suite'; status = 'fail'; error = "no output file (exit $auxCode)" }
    }
}

Write-Step 'Restore default fast worker'
if (-not $KeepHeavyLoaded) {
    & (Join-Path $Root 'Start-GokuBackend.ps1') -Root $Root
    & (Join-Path $Root 'Switch-GokuWorker.ps1') -Root $Root -Worker fast -Restart
}

$passed = @($results | Where-Object { $_.status -eq 'pass' }).Count
$failed = @($results | Where-Object { $_.status -eq 'fail' }).Count
$summary = [ordered]@{
    stamp = $stamp
    passed = $passed
    failed = $failed
    results = $results
    report_dir = $reportDir
}
$summaryPath = Join-Path $reportDir 'summary.json'
$summary | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $summaryPath

Write-Host "`nVerification complete: $passed passed, $failed failed" -ForegroundColor $(if ($failed -eq 0) { 'Green' } else { 'Yellow' })
Write-Host "Report: $summaryPath"
if ($failed -gt 0) { exit 1 } else { exit 0 }
