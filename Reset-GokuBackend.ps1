[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [int]$WaitSeconds = 3,
    [int]$MaxWaitSeconds = 90,
    [int]$TargetUsedMiB = 2500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

function Get-GpuUsedMiB {
    try {
        $raw = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
        if (-not $raw) { return $null }
        return [int]([double](($raw | Select-Object -First 1).ToString().Trim()))
    } catch {
        return $null
    }
}

function Get-PidsListeningOnPort([int]$Port) {
    $pids = @()
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in @($conns)) {
            if ($c.OwningProcess) { $pids += [int]$c.OwningProcess }
        }
    } catch { }
    return $pids
}

function Stop-GokuInferenceProcesses {
    $logDir = Join-Path $Root 'logs\backend'
    $pids = @()
    foreach ($name in @('llama-server.pid', 'mia-server.pid', 'alias-proxy.pid')) {
        $f = Join-Path $logDir $name
        if (Test-Path $f) {
            $raw = (Get-Content -Raw $f).Trim()
            if ($raw -match '^\d+$') { $pids += [int]$raw }
        }
    }

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and (
                $_.CommandLine -match 'llama-server\.exe' -or
                $_.CommandLine -match 'serve_openai\.py' -or
                $_.CommandLine -match 'goku_alias_proxy\.py'
            )
        } |
        ForEach-Object { $pids += [int]$_.ProcessId }

    $pids += Get-PidsListeningOnPort 8888
    $pids += Get-PidsListeningOnPort 11437

    # Never walk up to parent shells (that can kill Test-GokuModels / Start-GokuAI).
    # taskkill /T still kills children of the inference PIDs (venv launcher -> base python).
    $pids = $pids | Where-Object { $_ -gt 0 } | Select-Object -Unique
    foreach ($procId in $pids) {
        try {
            & taskkill.exe /PID $procId /T /F 2>$null | Out-Null
            Write-Host "Stopped PID $procId (tree)"
        } catch {
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-Host "Stopped PID $procId"
            } catch {
                Write-Host "PID $procId already gone"
            }
        }
    }
    return $pids.Count
}

Write-Host "Flushing GokuAI GPU backends..." -ForegroundColor Cyan
$before = Get-GpuUsedMiB
if ($null -ne $before) { Write-Host "GPU used before kill: $before MiB" }

$killed = Stop-GokuInferenceProcesses
Start-Sleep -Seconds $WaitSeconds

# Second pass in case children respawned / delayed exit
Stop-GokuInferenceProcesses | Out-Null

$deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
$used = Get-GpuUsedMiB
while ($null -ne $used -and $used -gt $TargetUsedMiB -and (Get-Date) -lt $deadline) {
    Write-Host "Waiting for VRAM flush: ${used} MiB (target <= ${TargetUsedMiB} MiB)..."
    Start-Sleep -Seconds 2
    # Keep killing stragglers while waiting
    Stop-GokuInferenceProcesses | Out-Null
    $used = Get-GpuUsedMiB
}

$after = Get-GpuUsedMiB
if ($null -eq $after) {
    Write-Host "Reset complete (nvidia-smi unavailable). Killed=$killed"
} elseif ($after -gt $TargetUsedMiB) {
    Write-Warning "VRAM still high after flush: ${after} MiB (target <= ${TargetUsedMiB}). Close other GPU apps if load fails."
} else {
    Write-Host "GPU flushed: ${after} MiB used (killed=$killed)" -ForegroundColor Green
}
