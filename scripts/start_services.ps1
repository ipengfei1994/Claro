[CmdletBinding()]
param(
    [ValidateSet("All", "PostgreSQL", "Redis", "Kafka", "Pipeline")]
    [string]$Service = "All",
    [string]$PostgreSQLServiceName
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")
Start-ClaroServices -Service $Service -PostgreSQLServiceName $PostgreSQLServiceName
