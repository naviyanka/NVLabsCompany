# Stops only what ./scripts/start-local-voice.ps1 started, then removes its private state.
# Each process is checked against the recorded PID and start time, the Redis container
# against its recorded ID and run label, and the isolated database copy against the run that
# created it, so a reused PID, a look-alike container or a tampered state file is left
# alone. An existing Redis, OmniRoute, models, the primary database and stored secrets are
# never touched. Safe to run repeatedly.

$ErrorActionPreference = "Stop"
$stateDir = Join-Path $env:TEMP "nexus-local-voice"
$stateFile = Join-Path $stateDir "state.json"
if (-not (Test-Path $stateFile)) { Write-Host "PASS  nothing to stop"; exit 0 }

$owned = Get-Content $stateFile -Raw | ConvertFrom-Json
$skipped = 0
$keepState = $false   # kept only while a container could not be checked

foreach ($rec in @($owned.processes)) {
    $p = Get-Process -Id $rec.pid -ErrorAction SilentlyContinue
    $same = $p -and [math]::Abs($p.StartTime.ToFileTimeUtc() - [int64]$rec.started) -lt 20000000   # 2 s
    if ($same) {
        taskkill /F /T /PID $rec.pid | Out-Null   # the whole tree: npm and uvicorn spawn children
        Write-Host "PASS  stopped $($rec.name)"
    } else {
        Write-Host "PASS  $($rec.name) already gone (PID not verified as ours, left alone)"
        if ($p) { $skipped++ }
    }
}

# The container is removed only if Docker confirms, by exact full ID, that it carries this
# run's label, then that its name and image are what this launcher created. `docker inspect
# -f '{{index .Config.Labels "..."}}'` is not used: PowerShell strips the inner quotes.
if ($owned.container) {
    $id = [string]$owned.container.id
    $run = [string]$owned.run
    $note = "Redis container already gone or not ours, left alone"
    if ($id -match '^[0-9a-f]{64}$' -and $run -match '^[0-9a-f-]{36}$') {
        try {
            $hit = @(docker ps -aq --no-trunc --filter "id=$id" --filter "label=nexus.local-voice=$run" 2>$null)
            if ($LASTEXITCODE -ne 0) { $note = "Docker unavailable; container and its record left alone, rerun when Docker is up"; $skipped++; $keepState = $true }
            elseif ($hit.Count -eq 1 -and ([string]$hit[0]).Trim() -eq $id) {
                $info = @(docker ps -a --no-trunc --filter "id=$id" --format "{{.Names}} {{.Image}}" 2>$null)
                if ($info.Count -eq 1 -and ([string]$info[0]).Trim() -ceq ("nexus-local-voice-redis-" + $run.Substring(0, 8) + " redis:7-alpine")) {
                    docker rm -f $id | Out-Null
                    $note = "removed Redis container $($owned.container.name)"
                }
            }
        } catch { $note = "Docker unavailable; container and its record left alone, rerun when Docker is up"; $skipped++; $keepState = $true }
    }
    Write-Host "PASS  $note"
}

# Only the launcher's own files: state, logs and the database copy it created.
$mine = @(if (-not $keepState) { $stateFile }) + @(Get-ChildItem -LiteralPath $stateDir -Filter "*.log" -File | ForEach-Object FullName)
$removeCopy = $false
if ($owned.db) {
    $copy = Join-Path $stateDir "acceptance.db"
    if ($owned.db.owner -eq $owned.run -and [IO.Path]::GetFullPath($owned.db.path) -eq [IO.Path]::GetFullPath($copy)) {
        $mine += @($copy, "$copy-wal", "$copy-shm", "$copy-journal")
        $removeCopy = $true
    } else {
        Write-Host "PASS  database path in state is not the launcher's copy, left alone"
    }
}
foreach ($f in $mine) {
    for ($i = 0; $i -lt 10 -and (Test-Path -LiteralPath $f); $i++) {
        try { Remove-Item -LiteralPath $f -Force; break } catch { Start-Sleep -Milliseconds 300 }   # file lock from a dying process
    }
}
if ($removeCopy) { Write-Host "PASS  removed isolated database copy" }
if (-not (Get-ChildItem -LiteralPath $stateDir -Force)) {
    Remove-Item -LiteralPath $stateDir -Force
    Write-Host "PASS  removed private state"
} else {
    Write-Host "PASS  private state emptied; the directory holds files this script did not create, left alone"
}
if ($skipped) { exit 1 }
