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
if (-not (Test-Path -LiteralPath $grok)) {
    throw "GrokBuild not installed at $grok. Run Install-GokuAI.ps1 first."
}

$promptFilePath = ''
if ($PromptFile) {
    if (-not (Test-Path -LiteralPath $PromptFile)) { throw "PromptFile not found: $PromptFile" }
    $promptFilePath = (Resolve-Path -LiteralPath $PromptFile).Path
    # NEVER inline multiline PromptFile text into the .bat launch line  -  cmd truncates at the
    # first newline, so Fix-in-Grok only received the first sentence and lost FAILED OUTPUT FOLDER.
    # Pass a single-line pointer; the agent must open the prompt file itself.
    $Prompt = "Read and obey EVERY line of the repair prompt file at: $promptFilePath - it names the FAILED OUTPUT FOLDER. Open that file first, then read MIGRATION_EVIDENCE.md, SOURCE_PROFILE.json, and compile-errors.log from the failed output before inventing any fix."
}
elseif ($Prompt -match "[\r\n]") {
    # Multiline -Prompt from callers: persist and point, same bat-safe rule.
    $promptFilePath = Join-Path $Root 'logs\last-grok-prompt.md'
    New-Item -ItemType Directory -Force -Path (Split-Path $promptFilePath -Parent) | Out-Null
    [IO.File]::WriteAllText($promptFilePath, $Prompt)
    $Prompt = "Read and obey EVERY line of the repair prompt file at: $promptFilePath - it names the FAILED OUTPUT FOLDER. Open that file first before inventing any fix."
}

# Seed the issue-only project policy when the project has no policy yet.
$agentsSrc = Join-Path $Root 'templates\AGENTS-GokuAI.md'
$agentsDst = Join-Path $project 'AGENTS.md'
if (-not (Test-Path -LiteralPath $agentsDst) -and (Test-Path -LiteralPath $agentsSrc)) {
    Copy-Item -LiteralPath $agentsSrc -Destination $agentsDst -Force
    Write-Host "Seeded issue-resolution policy: $agentsDst" -ForegroundColor DarkCyan
}

New-Item -ItemType Directory -Force -Path (Join-Path $project '.gokuai\issues') | Out-Null

# llama.cpp kat-reap50 is the default local worker (Mia/EXL3 deprecated).
if (-not $SkipBackendStart) {
    & (Join-Path $Root 'Start-GokuBackend.ps1') -Root $Root -Profile q6 -ForceRestart
}

$env:GROK_HOME = $grokHome
$env:GROK_SUBAGENTS = '1'
$env:GROK_MEMORY = '0'
$env:GROK_SHOW_THINKING_BLOCKS = '0'
$env:GOKUAI_ROOT = $Root
$env:GOKUAI_ORCHESTRATION = 'issue-only'

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
title GokuAI - GrokBuild Issue Orchestrator
cd /d "$project"
set GROK_HOME=$grokHome
set GROK_SUBAGENTS=1
set GROK_MEMORY=0
set GROK_SHOW_THINKING_BLOCKS=0
set GOKUAI_ROOT=$Root
set GOKUAI_ORCHESTRATION=issue-only
echo.
echo GokuAI issue-resolution mode
echo Orchestrator: $ParentModel (medium effort)
echo Default worker: KAT-Coder repair profile (thinking off)
echo Worker policy: one issue packet - one worker - one compact result
echo Workspace: $project
echo.
"$grok" -m $ParentModel --cwd "$project"$planFlag$promptArg
echo.
echo grok.exe exited with code %ERRORLEVEL%
pause
"@
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($launchBat, $bat, $utf8)

Write-Host "Launching GrokBuild as the sole issue orchestrator." -ForegroundColor Cyan
Write-Host "Workspace: $project" -ForegroundColor DarkCyan
Write-Host "Local workers: single-use, thinking off, no transcript hand-off." -ForegroundColor DarkCyan
Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', "`"$launchBat`"") -WorkingDirectory $project
Write-Host "Opened the GrokBuild TUI." -ForegroundColor Green
