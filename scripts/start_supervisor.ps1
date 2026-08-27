# Starts the NEXUS backend supervisor daemon.
#
# The supervisor is the one always-on process: it owns the backend uvicorn
# process and exposes start/stop/restart to the dashboard's Runtime Control
# panel (Settings -> System Hyperparameters). Run this once; leave it running.
#
#   ./scripts/start_supervisor.ps1
#
# Override any backend env var before launching if needed, e.g.:
#   $env:SECRET_KEY = "..."; ./scripts/start_supervisor.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $repoRoot "src")

Write-Host "Starting NEXUS supervisor on http://127.0.0.1:8001 ..."
Write-Host "It manages the backend on port 8000. Ctrl+C stops the supervisor (backend keeps running)."
python -m nexus.supervisor
