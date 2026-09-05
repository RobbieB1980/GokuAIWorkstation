<#
.SYNOPSIS
  Lint migration skills/agents for token-waste anti-patterns and catalog drift.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = ''
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) {
    $here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    $ProjectRoot = (Resolve-Path (Join-Path $here '..')).Path
}
$skills = Join-Path $ProjectRoot '.grok\skills'
$agents = Join-Path $ProjectRoot '.grok\agents'
$catalogPath = 'C:\gokuai\Data\262r\catalog.json'
$failures = New-Object System.Collections.Generic.List[string]

function Add-Fail([string]$m) { $failures.Add($m) | Out-Null }

$agentsMd = Join-Path $ProjectRoot 'Agents.md'
if (Test-Path $agentsMd) {
    $lines = @(Get-Content -LiteralPath $agentsMd).Count
    if ($lines -gt 120) { Add-Fail ("Agents.md has {0} lines (want <= 120 standing orders)" -f $lines) }
}

foreach ($skillMd in @(Get-ChildItem -LiteralPath $skills -Recurse -Filter 'SKILL.md' -ErrorAction SilentlyContinue)) {
    $text = Get-Content -LiteralPath $skillMd.FullName -Raw
    $lines = ($text -split "`n").Count
    if ($lines -gt 200) {
        Add-Fail ("{0} has {1} lines (want slim SKILL + references/)" -f $skillMd.FullName, $lines)
    }
}

if (-not (Test-Path -LiteralPath $catalogPath)) {
    Add-Fail ("Missing catalog: {0}" -f $catalogPath)
} else {
    $catalog = Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json
    $ids = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($c in @($catalog.converter)) { [void]$ids.Add([string]$c.id) }
    foreach ($s in @($catalog.shards)) { [void]$ids.Add([string]$s.id) }

    $indexPath = Join-Path $skills 'repair-failed-262-output\references\262r-shard-index.md'
    if (Test-Path -LiteralPath $indexPath) {
        $indexText = Get-Content -LiteralPath $indexPath -Raw
        foreach ($m in [regex]::Matches($indexText, 'mc-262r-[a-z0-9-]+')) {
            $id = $m.Value
            if (-not $ids.Contains($id)) { Add-Fail ("Shard index references unknown id: {0}" -f $id) }
        }
    } else {
        Add-Fail 'Missing 262r-shard-index.md - regenerate from catalog'
    }

    $root262 = 'C:\gokuai\Data\262r'
    $rows = @()
    if ($catalog.converter) { $rows += @($catalog.converter) }
    if ($catalog.shards) { $rows += @($catalog.shards) }
    foreach ($row in $rows) {
        $p = Join-Path $root262 $row.file
        if (-not (Test-Path -LiteralPath $p)) { Add-Fail ("Catalog file missing: {0}" -f $row.file) }
    }
}

foreach ($a in @('mc-research.md', 'mc-fast.md', 'mc-code.md', 'mc-reviewer.md')) {
    if (-not (Test-Path (Join-Path $agents $a))) { Add-Fail ("Missing agent definition: {0}" -f $a) }
}

foreach ($s in @('minecraft-knowledge', 'migrate-neoforge-262', 'repair-failed-262-output', 'encode-262r-remap', 'validate-destination-build')) {
    if (-not (Test-Path (Join-Path $skills ($s + '\SKILL.md')))) { Add-Fail ("Missing skill: {0}" -f $s) }
}

if ($failures.Count -eq 0) {
    Write-Host 'Lint OK' -ForegroundColor Green
    exit 0
}

Write-Host ("Lint FAILED ({0})" -f $failures.Count) -ForegroundColor Red
foreach ($f in $failures) { Write-Host (' - ' + $f) }
exit 1
