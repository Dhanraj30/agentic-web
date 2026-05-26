$ErrorActionPreference = "SilentlyContinue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PidFile = Join-Path $Root ".pids"

if (Test-Path $PidFile) {
    $ids = (Get-Content $PidFile -Raw).Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
    foreach ($id in $ids) {
        Stop-Process -Id ([int]$id) -Force
    }
    Remove-Item $PidFile -Force
}

foreach ($port in @(8765, 8000, 3000)) {
    Get-NetTCPConnection -LocalPort $port -State Listen |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force }
}

Write-Host "Stopped any process listening on 8765, 8000, or 3000."
