param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontend = Join-Path $repoRoot "frontend"

if (-not $SkipInstall) {
    Write-Host "Installing dashboard dependencies from frontend/package-lock.json..."
    Push-Location $frontend
    try {
        & npm.cmd ci --no-audit --no-fund --progress=false
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }
    }
    finally { Pop-Location }

    Write-Host "Checking backend dependencies..."
    & python -c "import fastapi, uvicorn, httpx, websockets, pydantic, networkx"
    if ($LASTEXITCODE -ne 0) {
        & python -m pip install -e (Join-Path $repoRoot "backend")
        if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed" }
    }
}

if (-not (Test-Path (Join-Path $frontend "node_modules\.bin\next.cmd"))) {
    throw "Next.js is missing. Run this script without -SkipInstall to install dependencies."
}

Write-Host "Starting API at http://127.0.0.1:8000 (Swagger: /docs)..."
$backendProc = Start-Process -FilePath "python" -ArgumentList @("-m", "backend.app.main") -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden

try {
    $apiReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($backendProc.HasExited) { throw "Backend exited with code $($backendProc.ExitCode)" }
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 1
            $apiReady = $true
            break
        }
        catch { Start-Sleep -Seconds 1 }
    }
    if (-not $apiReady) { throw "Backend did not become ready on port 8000" }

    Write-Host "Starting dashboard at http://localhost:3000..."
    Push-Location $frontend
    & npm.cmd run dev -- --hostname 127.0.0.1
}
finally {
    Pop-Location
    if (-not $backendProc.HasExited) {
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    }
}
