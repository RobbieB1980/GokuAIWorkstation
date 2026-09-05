<#
.SYNOPSIS
  GokuAI wrapper: sync RB Legacy migration skills into a workspace.
#>
[CmdletBinding()]
param(
    [string]$Workspace = 'C:\gokuai\projects\RB-Legacy-Java-Converter',
    [switch]$SkillsOnly
)

$ErrorActionPreference = 'Stop'
$sync = 'C:\gokuai\projects\_upstream\LegacyJavaConverter\scripts\Sync-GokuaiConverterWorkspace.ps1'
if (-not (Test-Path -LiteralPath $sync)) {
    throw "Missing sync script: $sync"
}

& $sync -Workspace $Workspace -SkillsOnly:$SkillsOnly
