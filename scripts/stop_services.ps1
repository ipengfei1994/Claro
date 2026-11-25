[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("All", "PostgreSQL", "Redis", "Kafka", "Pipeline")]
    [string]$Service = "All",
    [string]$PostgreSQLServiceName
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")
Stop-ClaroServices -Service $Service -PostgreSQLServiceName $PostgreSQLServiceName
