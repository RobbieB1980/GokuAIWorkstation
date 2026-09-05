[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [ValidateSet('q6', 'q8')]
    [string]$DefaultProfile = 'q6',
    [switch]$SkipBackendStart
)

# Repair a broken/partial GokuAI install after installer failure or backend breakage.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Write-Host "Repairing GokuAI at $Root ..." -ForegroundColor Cyan
& (Join-Path $Root 'Install-GokuAI.ps1') -Root $Root -Repair -ForceConfig -DefaultProfile $DefaultProfile -SkipBackendStart:$SkipBackendStart
& (Join-Path $Root 'Validate-GokuAI.ps1') -Root $Root -RequireBackend:(-not $SkipBackendStart)
Write-Host "Repair finished." -ForegroundColor Green
