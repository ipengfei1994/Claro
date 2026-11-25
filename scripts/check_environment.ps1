[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")
$results = @(Test-ClaroEnvironment)
$results | Format-Table Component, OK, Detail -AutoSize
if (@($results | Where-Object { -not $_.OK }).Count -gt 0) {
    exit 1
}
