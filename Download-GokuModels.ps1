[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [ValidateSet('q6', 'q8', 'all')]
    [string]$Only = 'q6'
)

# GGUF worker weights for llama.cpp backend.
# EXL3 / Mia downloads are DEPRECATED for default workers.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Write-Host "GokuAI model download helper (llama.cpp GGUF)" -ForegroundColor Cyan
Write-Host "Place files under: $(Join-Path $Root 'models')" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "Required default:"
Write-Host "  kat-reap50-Q6_K.gguf"
Write-Host "Optional quality A/B:"
Write-Host "  kat-reap50-Q8_0.gguf"
Write-Host ""
Write-Host "Automatic HF download for kat-reap50 is not wired in this station yet."
Write-Host "Copy the GGUF(s) into models\, then:"
Write-Host "  .\Start-GokuBackend.ps1 -Profile $Only -ForceRestart"
Write-Host ""
Write-Warning "DEPRECATED: EXL3 Mia weight downloads (Install-MiaExl3Kit / old -Only primary|draft|challenger)."

$q6 = Join-Path $Root 'models\kat-reap50-Q6_K.gguf'
$q8 = Join-Path $Root 'models\kat-reap50-Q8_0.gguf'
if (Test-Path $q6) {
    Write-Host ("[OK] q6 present ({0:N2} GB)" -f ((Get-Item $q6).Length/1GB)) -ForegroundColor Green
} else {
    Write-Host "[MISSING] $q6" -ForegroundColor Yellow
}
if (Test-Path $q8) {
    Write-Host ("[OK] q8 present ({0:N2} GB)" -f ((Get-Item $q8).Length/1GB)) -ForegroundColor Green
} else {
    Write-Host "[OPTIONAL MISSING] $q8" -ForegroundColor DarkYellow
}
