[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectPath,
    [string]$Root = 'C:\rmblocal_llm'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath $ProjectPath).Path
$python = Join-Path $Root 'runtime\.venv\Scripts\python.exe'
$script = Join-Path $Root 'scripts\generate_project_knowledge_context.py'
if (-not (Test-Path -LiteralPath $python)) { throw "Python runtime missing: $python" }
if (-not (Test-Path -LiteralPath $script)) { throw "Knowledge wiring generator missing: $script" }
& $python $script --root $Root --project $project
if ($LASTEXITCODE -ne 0) { throw "Project knowledge wiring refresh failed with exit code $LASTEXITCODE" }
