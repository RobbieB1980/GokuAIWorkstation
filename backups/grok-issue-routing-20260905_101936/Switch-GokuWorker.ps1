[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('fast', 'heavy', 'heavy-dflash')]
    [string]$Worker,
    [string]$Root = 'C:\gokuai',
    [switch]$Restart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$envPath = Join-Path $Root 'runtime\mia-kit\.env'
if (-not (Test-Path $envPath)) {
    throw "Missing $envPath - run Install-MiaExl3Kit.ps1 first."
}

$fast = Join-Path $Root 'models\EXL3\qwen3-coder-30b-a3b-exl3-4bpw'
$heavy = Join-Path $Root 'models\EXL3\qwen3.8-27b-exl3-3.5bpw'
$draft = Join-Path $Root 'models\EXL3\qwen3.8-27b-dflash2-exl3-5bpw'

switch ($Worker) {
    'fast' {
        $modelDir = $fast
        $draftMode = 'none'
        $draftDir = 'none'
        $label = 'Fast coder - Qwen3-Coder-30B-A3B EXL3 4.0bpw'
    }
    'heavy' {
        $modelDir = $heavy
        $draftMode = 'mtp'
        $draftDir = $draft
        $label = 'Heavy planner - Mia Qwen3.8-27B EXL3 3.5bpw (MTP)'
    }
    'heavy-dflash' {
        $modelDir = $heavy
        $draftMode = 'dflash2'
        $draftDir = $draft
        $label = 'Heavy planner - Mia Qwen3.8-27B + DFlash2 draft'
    }
}

if (-not (Test-Path $modelDir)) {
    throw "Model folder missing: $modelDir"
}
if ($draftMode -eq 'dflash2' -and -not (Test-Path $draft)) {
    throw "DFlash draft folder missing: $draft"
}

$lines = Get-Content -LiteralPath $envPath
$out = foreach ($line in $lines) {
    if ($line -match '^\s*MODEL_DIR\s*=') {
        "MODEL_DIR=$($modelDir -replace '\\', '/')"
    }
    elseif ($line -match '^\s*DRAFT\s*=') {
        "DRAFT=$draftMode"
    }
    elseif ($line -match '^\s*DRAFT_DIR\s*=') {
        "DRAFT_DIR=$($draftDir -replace '\\', '/')"
    }
    else {
        $line
    }
}
$utf8 = New-Object System.Text.UTF8Encoding $false
[IO.File]::WriteAllLines($envPath, $out, $utf8)

$active = Join-Path $Root 'models\active-worker.json'
@{
    worker = $Worker
    label = $label
    model_dir = $modelDir
    draft = $draftMode
    updated = (Get-Date).ToString('o')
} | ConvertTo-Json | Set-Content -Encoding UTF8 $active

Write-Host "Active worker -> $Worker" -ForegroundColor Green
Write-Host "  $label"
Write-Host "  MODEL_DIR=$modelDir"
Write-Host "  DRAFT=$draftMode"

if ($Restart) {
    Write-Host "Flushing GPU before loading '$Worker'..." -ForegroundColor DarkCyan
    & (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120
    # Backend is fully stopped after flush; start clean without a second reset race.
    & (Join-Path $Root 'Start-GokuBackend.ps1') -Root $Root
}
else {
    Write-Host "Restart backend to load it: .\Start-GokuBackend.ps1 -ForceRestart"
}
