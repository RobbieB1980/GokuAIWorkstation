[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('q6', 'q8', 'repair', 'fast', 'migration', 'review', 'heavy', 'heavy-dflash')]
    [string]$Worker,
    [string]$Root = 'C:\gokuai',
    [switch]$Restart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# DEPRECATED Mia/EXL3 multi-model roles map onto the single llama.cpp GGUF backend.
# Only q6 (default 32k) and q8 (16k quality A/B) change weights.
$profile = switch ($Worker) {
    'q6' { 'q6' }
    'q8' { 'q8' }
    'repair' { 'q6' }
    'fast' { 'q6' }
    'migration' { 'q6' }
    'review' { 'q6' }
    'heavy' { 'q6' }
    'heavy-dflash' { 'q6' }
    default { 'q6' }
}

if ($Worker -notin @('q6', 'q8')) {
    Write-Host "DEPRECATED: -Worker $Worker (Mia/EXL3). Using llama.cpp profile '$profile' instead." -ForegroundColor Yellow
}

Write-Host "Active llama.cpp profile -> $profile" -ForegroundColor Green
if ($Restart) {
    & (Join-Path $Root 'Start-GokuBackend.ps1') -Root $Root -Profile $profile -ForceRestart
}
else {
    Write-Host "Restart backend to load it:"
    Write-Host "  C:\gokuai\Start-GokuBackend.ps1 -Profile $profile -ForceRestart"
}
