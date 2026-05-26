param(
    [switch]$SkipInstall,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Read-DotEnv {
    $envPath = Join-Path $Root ".env"
    if (-not (Test-Path $envPath)) {
        Copy-Item (Join-Path $Root ".env.example") $envPath
        Write-Host "Created .env from .env.example. Add an API key before running real tasks."
    }

    Get-Content $envPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $name, $value = $line.Split("=", 2)
        $commentIndex = $value.IndexOf(" #")
        if ($commentIndex -ge 0) { $value = $value.Substring(0, $commentIndex) }
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
}

function Test-Port {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $connection
}

Read-DotEnv

if (-not $env:AGENT_PORT) { $env:AGENT_PORT = "8765" }
if (-not $env:GATEWAY_PORT) { $env:GATEWAY_PORT = "8000" }

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
node --version | Out-Null
npm --version | Out-Null

if (-not (Test-Path "agent\.venv")) {
    Write-Host "Creating Python virtual environment..."
    python -m venv agent\.venv
}

$Python = Join-Path $Root "agent\.venv\Scripts\python.exe"
$Pip = Join-Path $Root "agent\.venv\Scripts\pip.exe"

if (-not $SkipInstall) {
    Write-Host "Installing Python dependencies..."
    & $Pip install -r agent\requirements.txt
    Write-Host "Installing Playwright Chromium..."
    & $Python -m playwright install chromium

    if (-not (Test-Path "web\node_modules")) {
        Write-Host "Installing web dependencies..."
        Push-Location web
        npm install
        Pop-Location
    }
}

foreach ($port in @([int]$env:AGENT_PORT, [int]$env:GATEWAY_PORT, 3000)) {
    if (Test-Port $port) {
        throw "Port $port is already in use. Run scripts\stop.ps1 or change ports in .env."
    }
}

$agentOutLog = Join-Path $Root "agent.out.log"
$agentErrLog = Join-Path $Root "agent.err.log"
$gatewayOutLog = Join-Path $Root "gateway.out.log"
$gatewayErrLog = Join-Path $Root "gateway.err.log"
$webOutLog = Join-Path $Root "web.out.log"
$webErrLog = Join-Path $Root "web.err.log"

$agent = Start-Process -FilePath $Python -ArgumentList "server.py" -WorkingDirectory (Join-Path $Root "agent") -PassThru -WindowStyle Hidden -RedirectStandardOutput $agentOutLog -RedirectStandardError $agentErrLog
Write-Host "Agent API starting on http://localhost:$env:AGENT_PORT"

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-RestMethod "http://127.0.0.1:$env:AGENT_PORT/health" -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) { throw "Agent did not become healthy. Check agent.err.log." }

$gateway = Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory (Join-Path $Root "gateway") -PassThru -WindowStyle Hidden -RedirectStandardOutput $gatewayOutLog -RedirectStandardError $gatewayErrLog
Write-Host "Gateway starting on http://localhost:$env:GATEWAY_PORT"

Start-Sleep -Seconds 2

Push-Location web
$web = Start-Process -FilePath "npm.cmd" -ArgumentList "run dev -- --host 0.0.0.0" -WorkingDirectory (Join-Path $Root "web") -PassThru -WindowStyle Hidden -RedirectStandardOutput $webOutLog -RedirectStandardError $webErrLog
Pop-Location

"$($agent.Id) $($gateway.Id) $($web.Id)" | Set-Content (Join-Path $Root ".pids")

Write-Host ""
Write-Host "AgenticWeb is running:"
Write-Host "  Web UI:    http://localhost:3000"
Write-Host "  Gateway:   http://127.0.0.1:$env:GATEWAY_PORT/api/health"
Write-Host "  Agent API: http://127.0.0.1:$env:AGENT_PORT/health"
Write-Host ""
Write-Host "Logs: agent.out.log/agent.err.log, gateway.out.log/gateway.err.log, web.out.log/web.err.log"
Write-Host "Stop: scripts\stop.ps1"

if (-not $NoWait) {
    Write-Host ""
    Write-Host "Press Ctrl+C to stop all services."
    try {
        while (
            -not $agent.HasExited -and
            -not $gateway.HasExited -and
            -not $web.HasExited
        ) {
            Start-Sleep -Seconds 2
            $agent.Refresh()
            $gateway.Refresh()
            $web.Refresh()
        }
    } finally {
        foreach ($process in @($agent, $gateway, $web)) {
            if ($process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
        Remove-Item (Join-Path $Root ".pids") -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped AgenticWeb."
    }
}
