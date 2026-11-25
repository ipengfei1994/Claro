# Stop everything Claro started, in reverse start order.
#
# Only processes recorded in runtime\*.pid and verified by command line are
# stopped. PostgreSQL is a Windows service owned by the machine, so it is stopped
# last and only when -IncludePostgreSQL is given.
#
# Options:
#   -IncludePostgreSQL   also stop the PostgreSQL Windows service
#   -Force               do not ask for confirmation

[CmdletBinding()]
param(
    [switch]$IncludePostgreSQL,
    [switch]$Force,
    [string]$PostgreSQLServiceName
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")

if (-not $Force) {
    $answer = Read-Host "Stop the Claro UI, pipeline consumers and Kafka/Redis that Claro started? Type 'yes' to continue"
    if ($answer -ne "yes") {
        Write-Host "Cancelled."
        exit 1
    }
}

Write-Host "==> application"
Stop-ClaroApp

Write-Host "==> pipeline consumers"
Stop-ClaroPipeline

Write-Host "==> Kafka"
Stop-ClaroKafka

Write-Host "==> Redis"
Stop-ClaroRedis

if ($IncludePostgreSQL) {
    Write-Host "==> PostgreSQL"
    Stop-ClaroPostgreSQL -ServiceName $PostgreSQLServiceName
} else {
    Write-Host "==> PostgreSQL (left running; use -IncludePostgreSQL to stop it)"
}

Write-Host ""
Write-Host "Remaining listeners:"
foreach ($port in @(8501, 9092, 9093, 6379, 5432)) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        $owner = (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        Write-Host ("  port {0,-5} still listening ({1}, PID {2})" -f $port, $owner, $listener.OwningProcess)
    } else {
        Write-Host ("  port {0,-5} free" -f $port)
    }
}
