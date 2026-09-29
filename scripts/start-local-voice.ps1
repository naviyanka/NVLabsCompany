# Starts everything needed for manual acceptance of the local CEO voice gateway:
# Redis (only a container this script creates), the voice worker, the NEXUS backend and
# the dashboard, then runs `nexus doctor --voice`.
#
#   ./scripts/start-local-voice.ps1 -HermesModel <model-id> -SecretRef <ref> -CompanyId <guid>
#                                   [-CeoAgentId <guid> [-ReplaceCeo]] [-EvidenceFile <path>] [-NoPause]
#                                   [-UseDevDatabase]
#
# Database: by default the acceptance backend runs on a private, transactionally consistent
# SQLite backup (Python's online backup API, see clone_sqlite.py) stored in this script's
# private temp directory. The primary database is opened read-only for the backup and is
# never written. Encrypted rows are copied verbatim, so the existing SECRET_KEY still
# resolves them; nothing is decrypted, printed or hashed by this script. stop-local-voice.ps1
# deletes the copy after checking that this script created it. Only the copy is migrated
# (prepare_acceptance.py runs `alembic upgrade head` on it and refuses to touch the source).
#
# CEO and snapshot: in isolated mode the copy needs a designated CEO and a fresh Organization
# Snapshot before `nexus doctor --voice --company` can pass. -CeoAgentId names the agent; it
# is appointed through the application's own service, in the copy only. Without it, and when
# the copy has no CEO, the eligible agents are listed and the script stops (exit 3,
# LIVE_CHECK_REQUIRED) after cleaning up: a person chooses, nothing is defaulted.
# -UseDevDatabase runs against the primary database instead, after a warning and an
# interactive confirmation.
#
# Secrets: the worker secret is random, lives only in the environment of the processes
# started here, and is never printed, written to disk or put in .env. .env is only read;
# DATABASE_URL and SECRET_KEY are never printed. Ownership of what was started is recorded
# in a private temp directory; stop with ./scripts/stop-local-voice.ps1, which touches
# nothing else. Failure and Ctrl+C run the same cleanup.

[CmdletBinding()]
param(
    [string]$HermesModel = $env:HERMES_NATIVE_MODEL,
    [string]$HermesBaseUrl = "http://127.0.0.1:20128/v1",   # OmniRoute
    [string]$SecretRef,             # Fernet secret backend ref holding the OmniRoute key
    [string]$CompanyId,             # company for `nexus doctor --voice --company`
    [string]$EnvFile,               # defaults to the main checkout's .env (read only)
    [string]$Python,                # backend interpreter; defaults to the checkout's .venv
    [string]$Worker,                # voice worker executable; defaults to voice\.venv
    [int]$BackendPort = 8000,
    [int]$DashboardPort = 3100,
    [int]$WorkerPort = 8765,
    [int]$RedisPort = 6379,
    [string]$EvidenceFile,          # write the sanitized doctor JSON here
    [string]$CeoAgentId,            # isolated mode only: agent to appoint CEO in the copy
    [switch]$ReplaceCeo,            # with -CeoAgentId: replace a CEO the copy already has
    [switch]$UseDevDatabase,        # run on the primary database (asks for confirmation)
    [switch]$NoPause                # do not wait for Enter before manual acceptance
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$stateDir = Join-Path $env:TEMP "nexus-local-voice"
$stateFile = Join-Path $stateDir "state.json"
$copyPath = Join-Path $stateDir "acceptance.db"

if (Test-Path $stateFile) {
    Write-Host "FAIL  already started (state in $stateDir). Run ./scripts/stop-local-voice.ps1 first."
    exit 1
}

if ($CeoAgentId -and $UseDevDatabase) {
    Write-Host "FAIL  -CeoAgentId is for the isolated copy only; it is rejected with -UseDevDatabase."
    exit 1
}
if ($ReplaceCeo -and -not $CeoAgentId) { Write-Host "FAIL  -ReplaceCeo needs -CeoAgentId."; exit 1 }
$guid = [guid]::Empty
if ($CeoAgentId -and -not [guid]::TryParse($CeoAgentId, [ref]$guid)) { Write-Host "FAIL  -CeoAgentId is not a GUID."; exit 1 }
if (-not $UseDevDatabase -and -not [guid]::TryParse([string]$CompanyId, [ref]$guid)) {
    Write-Host "FAIL  isolated mode needs -CompanyId <guid>: the copy's CEO and snapshot are prepared for it."
    exit 1
}

if ($UseDevDatabase) {
    Write-Host "WARNING  -UseDevDatabase runs the acceptance backend on the primary development"
    Write-Host "         database. Acceptance activity WILL write to it. The default is an isolated copy."
    $answer = Read-Host "Type USE DEV DATABASE to continue"
    if ($answer -cne "USE DEV DATABASE") { Write-Host "FAIL  not confirmed; nothing started."; exit 1 }
}

# Private directory: only the current user may read it.
New-Item -ItemType Directory -Path $stateDir | Out-Null
icacls $stateDir /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" | Out-Null

$owned = [ordered]@{ run = [guid]::NewGuid().ToString(); processes = @(); container = $null; db = $null }
function Save-State { $owned | ConvertTo-Json -Depth 5 | Set-Content -Path $stateFile -Encoding utf8 }
Save-State

function Test-Port([int]$Port) {
    try { $c = [Net.Sockets.TcpClient]::new("127.0.0.1", $Port); $c.Dispose(); $true } catch { $false }
}

function Test-Redis([int]$Port) {
    try {
        $c = [Net.Sockets.TcpClient]::new("127.0.0.1", $Port)
        $s = $c.GetStream(); $s.ReadTimeout = 2000
        $b = [Text.Encoding]::ASCII.GetBytes("PING`r`n"); $s.Write($b, 0, $b.Length)
        $buf = New-Object byte[] 16; $n = $s.Read($buf, 0, 16); $c.Dispose()
        [Text.Encoding]::ASCII.GetString($buf, 0, $n) -like "+PONG*"
    } catch { $false }
}

# Any HTTP answer, even 401, means the gateway is up. Nothing is sent that could carry a key.
function Test-Http([string]$Url) {
    try { Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 3 | Out-Null; $true }
    catch { [bool]$_.Exception.Response }
}

# Not Get-FileHash: it is missing when the parent shell's PSModulePath shadows Windows PowerShell's.
function Get-Sha256([string]$Path) {
    $fs = [IO.File]::Open($Path, "Open", "Read", "ReadWrite")
    try { [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($fs)) } finally { $fs.Dispose() }
}

# prepare_acceptance.py prints one JSON line; only its exit code and that line are used.
function Invoke-Prepare([string[]]$PyArgs) {
    $ErrorActionPreference = "Continue"
    $lines = & $Python (Join-Path $PSScriptRoot "prepare_acceptance.py") @PyArgs 2>$null
    $code = $LASTEXITCODE
    $json = @($lines | Where-Object { "$_" -like "{*" }) | Select-Object -Last 1
    [pscustomobject]@{ code = $code; report = if ($json) { $json | ConvertFrom-Json } else { $null } }
}

function Wait-Until([scriptblock]$Ready, [int]$Seconds, [string]$What) {
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) {
        if (& $Ready) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "$What did not become ready within ${Seconds}s"
}

function Start-Owned([string]$Name, [string]$File, [string[]]$Arguments, [string]$WorkDir) {
    $p = Start-Process -FilePath $File -ArgumentList $Arguments -WorkingDirectory $WorkDir `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $stateDir "$Name.out.log") `
        -RedirectStandardError (Join-Path $stateDir "$Name.err.log")
    $owned.processes += [ordered]@{ name = $Name; pid = $p.Id; started = $p.StartTime.ToFileTimeUtc() }
    Save-State
}

# Test seam: NEXUS_LOCAL_VOICE_TEST_INTERRUPT=<stage> raises the exception Ctrl+C raises.
function Test-Interrupt([string]$Stage) {
    if ($env:NEXUS_LOCAL_VOICE_TEST_INTERRUPT -eq $Stage) {
        throw (New-Object System.Management.Automation.PipelineStoppedException)
    }
}

# Settings from the operator's .env become this process's environment only; never printed.
if (-not $EnvFile) {
    $common = (git -C $repo rev-parse --path-format=absolute --git-common-dir 2>$null)
    $main = if ($common) { Split-Path -Parent $common } else { $repo }
    $EnvFile = Join-Path $main ".env"
}
$saved = @{}
function Set-Env([string]$Key, [string]$Value) {
    if (-not $saved.ContainsKey($Key)) { $saved[$Key] = [Environment]::GetEnvironmentVariable($Key) }
    [Environment]::SetEnvironmentVariable($Key, $Value)
}

$status = [ordered]@{}
$ok = $false
$needCeo = $false
$prep = $null
$secret = $null
try {
    if (Test-Path $EnvFile) {
        foreach ($line in Get-Content $EnvFile) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$' -and $line -notmatch '^\s*#') {
                Set-Env $Matches[1] ($Matches[2].Trim('"', "'"))
            }
        }
        # A relative SQLite path means "next to the .env", not next to this checkout.
        if ($env:DATABASE_URL -match '^(sqlite[^:]*:///)(\./.+)$') {
            Set-Env "DATABASE_URL" ($Matches[1] + (Join-Path (Split-Path -Parent $EnvFile) $Matches[2]).Replace('\', '/'))
        }
    }

    # Backend interpreter.
    if (-not $Python) {
        $Python = @((Join-Path $repo ".venv\Scripts\python.exe"), (Join-Path (Split-Path -Parent $EnvFile) ".venv\Scripts\python.exe")) |
            Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $Python) { throw "no backend Python found; pass -Python" }
    if (-not $Worker) { $Worker = Join-Path $repo "voice\.venv\Scripts\nexus-voice.exe" }
    if (-not (Test-Path $Worker)) { throw "worker not installed: cd voice; uv sync" }

    # Database. Default: a private backup, migrated to head; only the processes started below see its URL.
    $sourceDb = $null; $sourceHash = $null
    if ($UseDevDatabase) {
        $status.database = "DEV DATABASE (confirmed by operator)"
    } else {
        if ($env:DATABASE_URL -notmatch '^(sqlite[^:]*:///)(.+?)(\?.*)?$' -or $Matches[2] -eq ':memory:') {
            throw "isolated mode supports a file-based SQLite DATABASE_URL only; use -UseDevDatabase to run on another database"
        }
        $prefix = $Matches[1]; $sourceDb = $Matches[2]
        # Canonical absolute paths, so the source and the copy compare exactly.
        if (-not [IO.Path]::IsPathRooted($sourceDb)) { $sourceDb = Join-Path (Split-Path -Parent $EnvFile) $sourceDb }
        $sourceDb = [IO.Path]::GetFullPath($sourceDb)
        if ($sourceDb -ieq [IO.Path]::GetFullPath($copyPath)) { throw "refusing to run: the database copy would be the source database" }
        $sourceHash = Get-Sha256 $sourceDb
        $owned.db = [ordered]@{ path = $copyPath; owner = $owned.run }
        Save-State   # recorded first, so stop can remove it even if the backup is interrupted
        & $Python (Join-Path $PSScriptRoot "clone_sqlite.py") $copyPath | Out-Null
        if ($LASTEXITCODE) { throw "could not create the isolated database copy" }
        Set-Env "DATABASE_URL" ($prefix + $copyPath.Replace('\', '/'))   # from here on only the copy is visible
        $status.database = "PASS (isolated backup; source opened read-only)"
        Test-Interrupt "database"
        $m = Invoke-Prepare @("migrate", $sourceDb)   # alembic runs on the copy; the source path is only compared
        if ($m.code) { throw "migration of the copy failed: $($m.report.error)" }
        $status.migration = "PASS (copy at Alembic head $($m.report.head); source not migrated)"
    }

    # Ephemeral worker secret: 48 random bytes, shared through the environment only.
    $bytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    Set-Env "NEXUS_VOICE_WORKER_SECRET" $secret
    Set-Env "VOICE_WORKER_SECRET" $secret
    Set-Env "NEXUS_VOICE_PORT" "$WorkerPort"
    Set-Env "VOICE_ENABLED" "true"
    Set-Env "VOICE_WORKER_URL" "ws://127.0.0.1:$WorkerPort"
    Set-Env "REDIS_URL" "redis://127.0.0.1:$RedisPort/0"
    Set-Env "PYTHONPATH" (Join-Path $repo "src")
    Set-Env "PYTHONIOENCODING" "utf-8"
    Set-Env "HERMES_NATIVE_TOOLS_ENABLED" "true"
    Set-Env "HERMES_NATIVE_BASE_URL" $HermesBaseUrl
    if ($HermesModel) { Set-Env "HERMES_NATIVE_MODEL" $HermesModel }
    if ($SecretRef) { Set-Env "HERMES_NATIVE_SECRET_REF" $SecretRef }
    Set-Env "NEXUS_API_URL" "http://127.0.0.1:$BackendPort"
    Set-Env "CORS_ORIGINS" "http://localhost:$DashboardPort,http://127.0.0.1:$DashboardPort"
    Set-Env "PORT" "$DashboardPort"
    Set-Env "PROXY_API" "true"

    # OmniRoute: must already be running; only probed, never started, stopped or authenticated to.
    if (-not (Test-Http ($HermesBaseUrl.TrimEnd('/') + "/models"))) { throw "OmniRoute is not reachable at $HermesBaseUrl" }
    $status.omniroute = "PASS (reachable, left running)"

    # The key is resolved by the app's own Fernet secret backend against the database the
    # backend will use (the copy); only a boolean comes back, and no model is called.
    $ErrorActionPreference = "Continue"
    $probe = & $Python -c "from nexus.adapters import hermes_provider as h; print('secret_resolves=' + str(h.status()['secret_configured']))" 2>$null
    $ErrorActionPreference = "Stop"
    if (($probe -join "") -notmatch 'secret_resolves=True') { throw "the OmniRoute secret ref does not resolve in the backend's database" }
    $status.secret = "PASS (resolves via the Fernet backend; value not read here)"

    # Isolated mode: the copy needs a CEO and a fresh Organization Snapshot for the doctor.
    if (-not $UseDevDatabase) {
        $prepArgs = @("prepare", $CompanyId)
        if ($CeoAgentId) { $prepArgs += @("--agent", $CeoAgentId) }
        if ($ReplaceCeo) { $prepArgs += "--replace-ceo" }
        $prep = Invoke-Prepare $prepArgs
        if ($prep.code -eq 3) {
            $needCeo = $true
            Write-Host ""
            Write-Host "LIVE_CHECK_REQUIRED  The copy has no CEO, and none is chosen for you. Eligible agents:"
            foreach ($c in $prep.report.candidates) { Write-Host ("  {0}  {1}  ({2})" -f $c.id, $c.name, $c.role) }
            $status.ceo = "LIVE_CHECK_REQUIRED (choose one; nothing was started)"
            throw [System.OperationCanceledException]::new("needs a CEO choice")
        }
        if ($prep.code) { throw "could not prepare the CEO and snapshot: $($prep.report.error)" }
        $status.ceo = "PASS ($($prep.report.ceo_source): $($prep.report.ceo.name) $($prep.report.ceo.id); in the copy only)"
        $status.snapshot = "PASS (version $($prep.report.snapshot.version), $($prep.report.snapshot.freshness), hash verified)"
    }

    # Redis: reuse one that answers, otherwise a container this script owns.
    if (Test-Redis $RedisPort) {
        $status.redis = "PASS (existing, not owned)"
    } else {
        if (Test-Port $RedisPort) { throw "port $RedisPort is used by something that is not Redis" }
        $name = "nexus-local-voice-redis-" + $owned.run.Substring(0, 8)
        $id = docker run -d --name $name --label "nexus.local-voice=$($owned.run)" -p "127.0.0.1:${RedisPort}:6379" redis:7-alpine
        if ($LASTEXITCODE) { throw "could not start the Redis container" }
        $owned.container = [ordered]@{ id = ([string]$id).Trim(); name = $name }
        Save-State
        Wait-Until { Test-Redis $RedisPort } 30 "Redis"
        $status.redis = "PASS (container owned by this script)"
    }
    Test-Interrupt "redis"

    foreach ($p in $WorkerPort, $BackendPort, $DashboardPort) {
        if (Test-Port $p) { throw "port $p is already in use" }
    }

    Start-Owned "worker" $Worker @("serve") (Join-Path $repo "voice")
    Wait-Until { Test-Port $WorkerPort } 60 "voice worker"
    $status.worker = "PASS"
    Test-Interrupt "worker"

    Start-Owned "backend" $Python @("-m", "uvicorn", "nexus.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") (Join-Path $repo "src")
    Wait-Until { try { (Invoke-WebRequest "http://127.0.0.1:$BackendPort/health" -UseBasicParsing -TimeoutSec 2).StatusCode -lt 500 } catch { $false } } 90 "backend"
    $status.backend = "PASS"

    Start-Owned "dashboard" "npm.cmd" @("run", "dev") (Join-Path $repo "dashboard")
    Wait-Until { Test-Port $DashboardPort } 60 "dashboard"
    $status.dashboard = "PASS"

    # Doctor runs with the same environment, so it can check the real worker link.
    $doctorArgs = @("-m", "nexus.cli", "doctor", "--voice", "--json")
    if ($CompanyId) { $doctorArgs += @("--company", $CompanyId) }
    $ErrorActionPreference = "Continue"
    $json = (& $Python @doctorArgs 2>$null) -join "`n"
    $ErrorActionPreference = "Stop"
    $report = $json | ConvertFrom-Json
    if ($json -match [regex]::Escape($secret)) { throw "doctor output contained the worker secret; not saved" }
    if ($EvidenceFile) { $json | Set-Content -Path $EvidenceFile -Encoding utf8 }
    Write-Host ""
    foreach ($c in $report.checks) { Write-Host ("{0,-20} {1,-22} {2}" -f $c.status, $c.id, $c.detail) }
    $status.doctor = $report.status

    if ($EvidenceFile -and $prep) {   # what was prepared in the copy, beside the doctor evidence
        ($prep.report | ConvertTo-Json -Depth 6) | Set-Content -Path ([IO.Path]::ChangeExtension($EvidenceFile, "prep.json")) -Encoding utf8
    }
    $ok = $true
} catch {
    if (-not $needCeo) {
        Write-Host "FAIL  $($_.Exception.Message)"
        $status.error = "FAIL"
    }
} finally {
    # The secret must not outlive this script's own environment.
    foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
    $secret = $null
    if ($sourceHash) {   # on every path: success, failure, Ctrl+C and the CEO-choice stop
        $same = (Get-Sha256 $sourceDb) -eq $sourceHash
        $status.source_db = if ($same) { "PASS (byte-for-byte unchanged)" } else { "FAIL changed while running (another process may be writing it)" }
        if (-not $same) { $status.error = "FAIL" }
    }
    if (-not $ok) {
        # Failure or Ctrl+C: leave nothing half-started.
        & (Join-Path $PSScriptRoot "stop-local-voice.ps1") | Out-Null
        if (-not $status.Contains("error") -and -not $needCeo) {
            # A stopped pipeline (Ctrl+C) skips the catch block and would otherwise exit 0.
            Write-Host "FAIL  interrupted; everything this script started was stopped."
            exit 1
        }
    }
}

Write-Host ""
foreach ($k in $status.Keys) { Write-Host ("{0,-10} {1}" -f $k, $status[$k]) }
if ($status.Contains("error")) { exit 1 }
if ($needCeo) {
    Write-Host ""
    Write-Host "Everything this script started was stopped and the copy was removed."
    Write-Host "Choose the CEO from the list above, then rerun with  -CeoAgentId <id>."
    exit 3
}

$hindi = $report.checks | Where-Object { $_.id -eq "tts_hi" } | Select-Object -First 1
if ($hindi -and $hindi.status -ne "PASS") {
    Write-Host ""
    Write-Host "MISSING  No Hindi (hi-IN) text-to-speech voice is installed, so Hindi replies cannot be"
    Write-Host "         spoken. tts_hi stays LIVE_CHECK_REQUIRED. English acceptance can continue;"
    Write-Host "         bilingual spoken output cannot pass until the Windows voice is installed."
    Write-Host "         Procedure: docs/VOICE_GATEWAY.md, section 'Hindi speech on Windows'."
}
Write-Host ""
Write-Host "Dashboard  http://localhost:$DashboardPort"
Write-Host "Backend    http://127.0.0.1:$BackendPort"
Write-Host "Worker     ws://127.0.0.1:$WorkerPort (loopback)"
Write-Host "Stop with  ./scripts/stop-local-voice.ps1"
if ($hindi -and $hindi.status -ne "PASS" -and -not $NoPause -and -not [Console]::IsInputRedirected) {
    Write-Host ""
    Read-Host "Press Enter to continue to manual acceptance (English only; run ./scripts/stop-local-voice.ps1 to stop)" | Out-Null
}
if ($status.doctor -eq "FAIL") { exit 1 }
