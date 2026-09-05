[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ProjectPath,
    [string]$Root = 'C:\gokuai',
    [string]$ParentModel = 'grok-4.5',
    [string]$Prompt = '',
    [string]$PromptFile = '',
    [switch]$SkipBackendStart,
    [switch]$Plan
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$project = (Resolve-Path -LiteralPath $ProjectPath).Path
$grokHome = Join-Path $Root 'grok-home'
$grok = Join-Path $grokHome 'bin\grok.exe'
if (-not (Test-Path $grok)) {
    throw "GrokBuild not installed at $grok. Run .\Install-GokuAI.ps1 first."
}

if ($PromptFile) {
    if (-not (Test-Path -LiteralPath $PromptFile)) { throw "PromptFile not found: $PromptFile" }
    $Prompt = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $PromptFile).Path)
}

# Seed AGENTS.md if missing
$agentsSrc = Join-Path $Root 'templates\AGENTS-GokuAI.md'
$agentsDst = Join-Path $project 'AGENTS.md'
if (-not (Test-Path $agentsDst) -and (Test-Path $agentsSrc)) {
    Copy-Item -Force $agentsSrc $agentsDst
    Write-Host "Seeded $agentsDst from GokuAI template" -ForegroundColor DarkCyan
}

New-Item -ItemType Directory -Force -Path (Join-Path $project '.gokuai\tasks') | Out-Null

if (-not $SkipBackendStart) {
    & (Join-Path $Root 'Start-GokuBackend.ps1') -Root $Root
}

$env:GROK_HOME = $grokHome
$env:GROK_SUBAGENTS = '1'
$env:GROK_MEMORY = '0'
$env:GOKUAI_ROOT = $Root

# Prefer a durable console window so the TUI does not vanish on launch errors.
$launchBat = Join-Path $Root 'logs\launch-grok-session.bat'
$promptArg = ''
if ($Prompt) {
    $escaped = $Prompt.Replace('"', '""')
    $promptArg = " `"$escaped`""
}
$planFlag = ''
if ($Plan) { $planFlag = ' --plan' }
$bat = @"
@echo off
title GokuAI - GrokBuild
cd /d "$project"
set GROK_HOME=$grokHome
set GROK_SUBAGENTS=1
set GROK_MEMORY=0
set GOKUAI_ROOT=$Root
echo.
echo GokuAI
echo Parent: $ParentModel
echo Workers: http://127.0.0.1:11437/v1
echo Workspace: $project
echo.
"$grok" -m $ParentModel --cwd "$project"$planFlag$promptArg
echo.
echo grok.exe exited with code %ERRORLEVEL%
pause
"@
$utf8 = New-Object System.Text.UTF8Encoding $false
[IO.File]::WriteAllText($launchBat, $bat, $utf8)
Write-Host "Launching GokuAI parent: $ParentModel (medium effort from config)" -ForegroundColor Cyan
Write-Host "Workspace: $project" -ForegroundColor DarkCyan
Write-Host "Workers: goku-* via http://127.0.0.1:11437/v1" -ForegroundColor DarkCyan
Write-Host "Console launcher: $launchBat" -ForegroundColor DarkCyan
Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', "`"$launchBat`"") -WorkingDirectory $project
Write-Host "Opened a durable cmd window for the GrokBuild TUI." -ForegroundColor Green
