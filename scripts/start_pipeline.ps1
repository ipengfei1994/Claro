[CmdletBinding()]
param(
    [string]$Topic = "game.messages.raw",
    [string]$ConsumerGroup = "claro.pipeline.v1",
    [string]$PostgreSQLServiceName,
    [string]$UiPort = "8501",
    [switch]$WithUi
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")
if ([int]$UiPort -lt 1 -or [int]$UiPort -gt 65535) {
    throw "UiPort must be between 1 and 65535."
}
$infrastructure = @(Get-ClaroServiceStatus -PostgreSQLServiceName $PostgreSQLServiceName |
    Where-Object { $_.Service -in @("PostgreSQL", "Redis", "Kafka") })
if (@($infrastructure | Where-Object { -not $_.Running }).Count -gt 0) {
    throw "PostgreSQL, Redis, and Kafka must be running before starting the pipeline."
}
Start-ClaroPipeline -Topic $Topic -ConsumerGroup $ConsumerGroup -UiPort $UiPort -WithUi:$WithUi
