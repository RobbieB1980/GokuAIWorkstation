[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [string]$KnowledgeRoot = 'C:\rmblocal_llm\knowledge',
    [ValidateSet('all', 'fast', 'heavy', 'heavy-dflash')]
    [string]$Workers = 'all',
    [switch]$SkipRestore
)

# GokuAI grounded benchmark entrypoint (mirrors C:\rmblocal_llm\Test-*.ps1 style).
# Runs rb-model-benchmark-v2.2 against EXL3 workers with GPU flush between loads.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$runner = Join-Path $Root 'Run-ModelBenchmark.ps1'
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Missing $runner"
}

Write-Host '=== GokuAI model benchmark v2.2 (quality-first; speed reported separately) ===' -ForegroundColor Cyan
Write-Host "Workers=$Workers  KnowledgeRoot=$KnowledgeRoot"

& $runner -Root $Root -KnowledgeRoot $KnowledgeRoot -Workers $Workers -SkipRestore:$SkipRestore
if ($LASTEXITCODE -ne 0) { throw "GokuAI benchmark failed (exit $LASTEXITCODE)" }

Write-Host 'GokuAI benchmark finished. Selection JSON not modified.' -ForegroundColor Green
