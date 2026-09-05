[CmdletBinding()]
param([string]$Root='C:\gokuai',[string]$KnowledgeRoot='C:\rmblocal_llm\knowledge',[ValidateSet('all','fast','heavy','heavy-dflash')][string]$Workers='all',[switch]$SkipAux,[switch]$SkipChat,[switch]$KeepHeavyLoaded)
Set-StrictMode -Version Latest;$ErrorActionPreference='Stop'
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss';$outDir=Join-Path $Root "benchmarks\fit-suite-$stamp";New-Item $outDir -ItemType Directory -Force|Out-Null
$steps=@();$failed=0
function Run-Step([string]$Name,[scriptblock]$Action){$sw=[Diagnostics.Stopwatch]::StartNew();try{&$Action;$code=$LASTEXITCODE;if($null-ne$code-and$code-ne0){throw "exit $code"};$script:steps+=@{name=$Name;status='pass';seconds=[math]::Round($sw.Elapsed.TotalSeconds,2)}}catch{$script:failed++;$script:steps+=@{name=$Name;status='fail';seconds=[math]::Round($sw.Elapsed.TotalSeconds,2);error=$_.Exception.Message};Write-Warning "$Name failed: $($_.Exception.Message)"}}
Run-Step 'installation-validation' {& (Join-Path $Root 'Validate-GokuAI.ps1') -Root $Root}
if(-not$SkipChat){Run-Step 'chat-quality-and-latency' {& (Join-Path $Root 'Run-ModelBenchmark.ps1') -Root $Root -KnowledgeRoot $KnowledgeRoot -Workers $Workers -SkipRestore:$KeepHeavyLoaded}}
if(-not$SkipAux){Run-Step 'all-model-inference-validation' {& (Join-Path $Root 'Test-GokuModels.ps1') -Root $Root -SkipExl3 -KeepHeavyLoaded:$KeepHeavyLoaded}}
$python=Join-Path $Root 'runtime\mia-kit\.venv\Scripts\python.exe';$report=Join-Path $outDir 'model-fit-report.json'
Run-Step 'fit-scorecard' {&$python (Join-Path $Root 'scripts\model_fit_report.py') --root $Root --out $report}
if(-not$KeepHeavyLoaded){Run-Step 'final-gpu-flush' {& (Join-Path $Root 'Reset-GokuBackend.ps1') -Root $Root -TargetUsedMiB 2500 -MaxWaitSeconds 120}}
@{schema='goku-fit-suite-run-v1';created=(Get-Date).ToString('o');failed=$failed;steps=$steps;fit_report=$report}|ConvertTo-Json -Depth 7|Set-Content (Join-Path $outDir 'run-summary.json') -Encoding UTF8
Write-Host "Fit suite complete: $failed failed. Report: $report" -ForegroundColor $(if($failed){'Yellow'}else{'Green'});if($failed){exit 1}
