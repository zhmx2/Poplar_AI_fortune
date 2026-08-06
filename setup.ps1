$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    Write-Host "Python was not found. Install 64-bit Python 3.12, then run this script again."
    Write-Host "Official download: https://www.python.org/downloads/windows/"
    exit 1
}

if ($pythonCommand.Name -eq "py.exe") {
    & $pythonCommand.Source -3.12 -m venv .venv
} else {
    & $pythonCommand.Source -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from the safe example."
}

Write-Host ""
Write-Host "Installation complete. Review .env and TWS settings, then run .\start.ps1"
