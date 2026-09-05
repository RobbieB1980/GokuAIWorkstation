[CmdletBinding()]
param([string]$Root='C:\gokuai\Data',[string]$Output='C:\gokuai\DataIndex\goku-data.db',[switch]$Rebuild)
Set-StrictMode -Version Latest;$ErrorActionPreference='Stop'
$python='C:\gokuai\runtime\mia-kit\.venv\Scripts\python.exe';$script='C:\gokuai\scripts\index_goku_data.py'
if(-not(Test-Path $python)){throw "Python missing: $python"};if(-not(Test-Path $script)){throw "Indexer missing: $script"}
$a=@($script,'--root',$Root,'--out',$Output);if($Rebuild){$a+='--rebuild'}
&$python @a;if($LASTEXITCODE-ne0){throw "Indexer failed with exit $LASTEXITCODE"}
Write-Host "Index ready: $Output" -ForegroundColor Green
