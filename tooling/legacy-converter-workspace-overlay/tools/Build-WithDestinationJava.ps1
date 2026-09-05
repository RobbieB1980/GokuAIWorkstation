<#
.SYNOPSIS
  Run Gradle for a NeoForge 26.2 converted project using the destination JDK (Java 25).

.DESCRIPTION
  Agents and Fix-in-Grok repairs must use this instead of bare ``gradlew`` under ambient
  JAVA_HOME (often Java 8). Pins org.gradle.java.home, sets JAVA_HOME, then runs the wrapper.

.EXAMPLE
  .\Build-WithDestinationJava.ps1 -ProjectRoot "C:\mods\mymod-26.2"
.EXAMPLE
  .\Build-WithDestinationJava.ps1 -ProjectRoot "C:\mods\mymod-26.2" -Tasks "compileJava --no-daemon --stacktrace"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProjectRoot,
    [string]$Tasks = 'build --no-daemon --stacktrace',
    [string]$LogFileName = 'compile-errors.log',
    [int]$FallbackJavaMajor = 25
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib\ConversionCore.ps1')

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "Project root missing: $ProjectRoot"
}

$result = Invoke-GradleBuildWithRequiredJava -ProjectRoot $ProjectRoot -Tasks $Tasks -LogFileName $LogFileName -FallbackJavaMajor $FallbackJavaMajor
Write-Host ("Destination JAVA_HOME={0} (Java {1}; required {2}+)" -f $result.JavaHome, $result.SelectedMajor, $result.RequiredMajor) -ForegroundColor Cyan
Write-Host ("Gradle exit: {0}  log: {1}" -f $result.ExitCode, $result.LogPath)
if ($result.ExitCode -eq 0) {
    $libs = Join-Path $ProjectRoot 'build\libs'
    $jars = @(Get-ChildItem -LiteralPath $libs -Filter '*.jar' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch 'sources|javadoc' })
    if ($jars.Count -gt 0) {
        Write-Host ("OK: {0}" -f $jars[0].FullName) -ForegroundColor Green
    }
}
exit [int]$result.ExitCode
