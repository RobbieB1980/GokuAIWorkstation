[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [switch]$SkipCudaInstall,
    [switch]$SkipBuildToolsCheck
)

# Ensures llama.cpp CUDA redistributables are present.
# Does NOT download GGUF weights. Mia/EXL3 engine install is deprecated.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

Write-Step "llama.cpp present?"
$llamaDir = Join-Path $Root 'runtime\llama.cpp'
$server = Join-Path $llamaDir 'llama-server.exe'
if (-not (Test-Path $server)) {
    throw "Missing $server - place a CUDA llama.cpp Windows build in runtime\llama.cpp\"
}
Write-Host "[OK] llama-server.exe" -ForegroundColor Green

Write-Step "CUDA 12 redistributables for ggml-cuda.dll"
if (-not ((Test-Path (Join-Path $llamaDir 'cudart64_12.dll')) -and (Test-Path (Join-Path $llamaDir 'cublas64_12.dll')))) {
    Write-Host "Fetching CUDA 12 DLLs via Install-GokuAI -Repair..."
    & (Join-Path $Root 'Install-GokuAI.ps1') -Root $Root -Repair -SkipGrokInstall -SkipBackendStart
}
if ((Test-Path (Join-Path $llamaDir 'cudart64_12.dll')) -and (Test-Path (Join-Path $llamaDir 'cublas64_12.dll'))) {
    Write-Host "[OK] cudart64_12.dll + cublas64_12.dll" -ForegroundColor Green
} else {
    throw "CUDA 12 redistributables still missing under $llamaDir"
}

Write-Step "Optional nvcc check"
if (Get-Command nvcc -ErrorAction SilentlyContinue) {
    nvcc --version | Select-Object -First 3 | Out-Host
} else {
    Write-Host "nvcc not required for prebuilt llama-server."
}

Write-Host "`nRuntime OK for llama.cpp backend." -ForegroundColor Green
Write-Host "Place GGUFs in $Root\models\ then: .\Start-GokuBackend.ps1 -Profile q6 -ForceRestart"
Write-Host "If install breaks: .\Repair-GokuAI.ps1"
