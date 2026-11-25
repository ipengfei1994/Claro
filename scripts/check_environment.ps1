# Claro environment report.
#
# Reports every component with one of six explicit states:
#   Healthy        installed, running, and answering a real probe
#   Running        process/service is up but the health probe failed
#   Installed      present on disk but not currently running
#   NotConfigured  present but the platform has no usable configuration for it
#   Incompatible   present but the wrong version, or the port is taken by another owner
#   Missing        not installed at all
#
# Writes to the standard output stream so the report can be redirected to a file.
# Exit codes: 0 = no blocking problem, 1 = at least one Missing/Incompatible component.

[CmdletBinding()]
param([string]$PostgreSQLServiceName)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")

Write-Output "Claro environment report"
Write-Output "Project: $script:ClaroProjectRoot"
Write-Output ""

$report = Get-ClaroEnvironmentReport -PostgreSQLServiceName $PostgreSQLServiceName
$report | Format-Table -AutoSize -Property Component, State, Detail | Out-String -Width 200 | Write-Output

$hints = $report | Where-Object { $_.Hint }
if ($hints) {
    Write-Output "Next actions:"
    foreach ($item in $hints) {
        Write-Output ("  - {0}: {1}" -f $item.Component, $item.Hint)
    }
    Write-Output ""
}

Write-Output "Declared capabilities:"
$hiveBinary = Get-Command beeline -ErrorAction SilentlyContinue
if ($hiveBinary) {
    Write-Output "  Hive/Beeline   Available      offline warehouse queries enabled"
} else {
    Write-Output "  Hive/Beeline   Missing        offline warehouse analytics unavailable;"
    Write-Output "                                PostgreSQL serves the same metrics instead."
}
if ($env:CLARO_RISK__LLM__ENABLED -eq "true") {
    Write-Output "  LLM detector   Configured     external model adapter enabled"
} else {
    Write-Output "  LLM detector   NotConfigured  disabled by default; rule and ML layers stay active"
}
Write-Output ""

if (Test-ClaroStateHealthy -Report $report) {
    Write-Output "Result: no blocking problem detected."
    exit 0
}

Write-Output "Result: blocking problems detected (see Missing/Incompatible rows above)."
exit 1
