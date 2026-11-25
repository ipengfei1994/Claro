[CmdletBinding()]
param([string]$PostgreSQLServiceName, [switch]$IncludePipeline)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")
$results = @(Get-ClaroServiceStatus -PostgreSQLServiceName $PostgreSQLServiceName |
    Where-Object { $IncludePipeline -or $_.Service -in @("PostgreSQL", "Redis", "Kafka") })
$results | Format-Table Service, Running, Detail -AutoSize
if (@($results | Where-Object { -not $_.Running }).Count -gt 0) {
    exit 1
}
