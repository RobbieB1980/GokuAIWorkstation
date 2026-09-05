$ErrorActionPreference = 'Continue'
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'goku_alias_proxy\.py' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "killed $($_.ProcessId)"
    }
Start-Sleep -Seconds 1
$out = 'C:\gokuai\logs\backend\alias-proxy-live.stdout.log'
$err = 'C:\gokuai\logs\backend\alias-proxy-live.stderr.log'
Remove-Item $out, $err -ErrorAction SilentlyContinue
$p = Start-Process `
    -FilePath 'C:\gokuai\runtime\mia-kit\.venv\Scripts\python.exe' `
    -ArgumentList @(
        'C:\gokuai\scripts\goku_alias_proxy.py',
        '--host', '127.0.0.1',
        '--port', '11437',
        '--backend', 'http://127.0.0.1:8888/v1'
    ) `
    -WorkingDirectory 'C:\gokuai' `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -WindowStyle Hidden `
    -PassThru
Set-Content -Path 'C:\gokuai\logs\backend\alias-proxy.pid' -Value $p.Id
Write-Host "started $($p.Id)"
Start-Sleep -Seconds 2
try {
    $h = Invoke-WebRequest 'http://127.0.0.1:11437/health' -UseBasicParsing -TimeoutSec 5
    Write-Host $h.Content
} catch {
    Write-Host "health fail: $($_.Exception.Message)"
    if (Test-Path $err) { Get-Content $err -Tail 30 }
}
