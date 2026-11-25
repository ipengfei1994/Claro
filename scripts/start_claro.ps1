# Bring the whole Claro stack up on this Windows machine.
#
# Order: environment check -> services (PostgreSQL, Redis, Kafka) -> database
# revision check -> Streamlit app. Every step is idempotent: components that are
# already healthy are reported and left alone.
#
# Options:
#   -SkipServices   only start the UI (services are managed elsewhere)
#   -SkipChecks     skip the blocking environment check (not recommended)
#   -Port           override the UI port

[CmdletBinding()]
param(
    [switch]$SkipServices,
    [switch]$SkipChecks,
    [int]$Port = 0,
    [string]$PostgreSQLServiceName,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")

New-Item -ItemType Directory -Force -Path $script:ClaroRuntimeRoot, $script:ClaroLogRoot | Out-Null
if ($Port -le 0) { $Port = Get-ClaroAppPort }

Write-Host "==> 1/4 environment"
if ($SkipChecks) {
    Write-Host "    skipped (-SkipChecks)"
} else {
    $report = Get-ClaroEnvironmentReport -PostgreSQLServiceName $PostgreSQLServiceName
    $blocking = $report | Where-Object { $_.State -in @("Missing", "Incompatible") }
    $report | Format-Table -AutoSize -Property Component, State, Detail
    if ($blocking) {
        Write-Host "Blocking problems found. Fix these first, or re-run with -SkipChecks to try anyway:"
        $blocking | ForEach-Object { Write-Host ("  - {0}: {1}" -f $_.Component, $_.Detail) }
        exit 1
    }
}

if ($SkipServices) {
    Write-Host "==> 2/4 services (skipped)"
} else {
    Write-Host "==> 2/4 services"
    Start-ClaroServices -Service All -PostgreSQLServiceName $PostgreSQLServiceName
}

Write-Host "==> 3/4 database revision"
& (Join-Path $PSScriptRoot "run_migrations.ps1") -Revision head
if ($LASTEXITCODE -ne 0) {
    throw "Database migrations failed; refusing to start the application."
}

Write-Host "==> 4/4 application"
Start-ClaroApp -Port $Port -TimeoutSeconds $TimeoutSeconds

Write-Host ""
Write-Host "Claro is up:"
Write-Host "  UI          http://127.0.0.1:$Port"
Write-Host "  Health      http://127.0.0.1:$Port/_stcore/health"
Write-Host "  Logs        logs\app.stdout.log, logs\app.stderr.log"
Write-Host "  Stop with   scripts\stop_claro.ps1"
