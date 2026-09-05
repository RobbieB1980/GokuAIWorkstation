<#
.SYNOPSIS
  Sync RB Legacy migration skills into a workspace.

  Prefers the tracked GokuAI overlay at tooling/legacy-converter-workspace-overlay,
  then the LegacyJavaConverter packaging overlay, then the live converter project.
#>
[CmdletBinding()]
param(
    [string]$Workspace = 'C:\gokuai\projects\RB-Legacy-Java-Converter',
    [switch]$SkillsOnly,
    [string]$GokuRoot = 'C:\gokuai'
)

$ErrorActionPreference = 'Stop'

$trackedOverlay = Join-Path $GokuRoot 'tooling\legacy-converter-workspace-overlay'
$packagingSync = Join-Path $GokuRoot 'projects\_upstream\LegacyJavaConverter\scripts\Sync-GokuaiConverterWorkspace.ps1'
$packagingOverlay = Join-Path $GokuRoot 'projects\_upstream\LegacyJavaConverter\gokuai-workspace-overlay'
$liveGrok = Join-Path $GokuRoot 'projects\RB-Legacy-Java-Converter\.grok'

if (-not (Test-Path -LiteralPath $Workspace)) {
    New-Item -ItemType Directory -Path $Workspace -Force | Out-Null
}

function Sync-FromOverlay([string]$OverlayRoot, [string]$Target, [bool]$FullTools) {
    $grokSrc = Join-Path $OverlayRoot '.grok'
    if (-not (Test-Path -LiteralPath $grokSrc)) { throw "Overlay missing .grok: $OverlayRoot" }

    Write-Host ("==> Syncing migration skills from {0} -> {1}" -f $OverlayRoot, $Target) -ForegroundColor Cyan
    & robocopy.exe $grokSrc (Join-Path $Target '.grok') /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy .grok failed: $LASTEXITCODE" }

    $agents = Join-Path $OverlayRoot 'Agents.md'
    if (Test-Path $agents) { Copy-Item $agents (Join-Path $Target 'Agents.md') -Force }

    $toolsDst = Join-Path $Target 'tools'
    if (-not (Test-Path $toolsDst)) { New-Item -ItemType Directory -Path $toolsDst -Force | Out-Null }
    $toolsSrc = Join-Path $OverlayRoot 'tools'
    if (Test-Path $toolsSrc) {
        Get-ChildItem -LiteralPath $toolsSrc -File | ForEach-Object {
            $dest = Join-Path $toolsDst $_.Name
            $srcFull = $_.FullName
            $dstFull = [IO.Path]::GetFullPath($dest)
            if (-not [string]::Equals($srcFull, $dstFull, [StringComparison]::OrdinalIgnoreCase)) {
                Copy-Item $srcFull $dest -Force
            }
        }
    }

    if ($FullTools -and (Test-Path -LiteralPath $packagingSync)) {
        & $packagingSync -Workspace $Target
    }

    Write-Host ("OK: migration skills synced ({0})." -f $(if ($FullTools) { 'full' } else { 'skills-only' })) -ForegroundColor Green
}

# 1) Tracked GokuAI overlay (survives projects/ wipe)
if (Test-Path (Join-Path $trackedOverlay '.grok')) {
    Sync-FromOverlay -OverlayRoot $trackedOverlay -Target $Workspace -FullTools:(-not $SkillsOnly)
    return
}

# 2) Packaging repo sync script
if (Test-Path -LiteralPath $packagingSync) {
    & $packagingSync -Workspace $Workspace -SkillsOnly:$SkillsOnly
    return
}

# 3) Packaging overlay folder
if (Test-Path (Join-Path $packagingOverlay '.grok')) {
    Sync-FromOverlay -OverlayRoot $packagingOverlay -Target $Workspace -FullTools:$false
    return
}

# 4) Live converter project .grok
if (Test-Path -LiteralPath $liveGrok) {
    Write-Host "==> Syncing from live converter .grok" -ForegroundColor Cyan
    & robocopy.exe $liveGrok (Join-Path $Workspace '.grok') /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy .grok failed: $LASTEXITCODE" }
    $agents = Join-Path $GokuRoot 'projects\RB-Legacy-Java-Converter\Agents.md'
    if (Test-Path $agents) { Copy-Item $agents (Join-Path $Workspace 'Agents.md') -Force }
    Write-Host 'OK: migration skills synced (live fallback).' -ForegroundColor Green
    return
}

throw "No migration overlay found. Expected one of:`n  $trackedOverlay`n  $packagingSync`n  $liveGrok"
