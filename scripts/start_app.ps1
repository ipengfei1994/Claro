# Start the Claro Streamlit application with PID tracking and a health probe.
#
# The script refuses to adopt an unrelated process that happens to occupy the
# port, waits for the app to answer its health endpoint, and writes
# runtime\app.pid so stop_app.ps1 can stop exactly this process.

[CmdletBinding()]
param([int]$Port = 0, [int]$TimeoutSeconds = 90)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")

if ($Port -le 0) { $Port = Get-ClaroAppPort }
Start-ClaroApp -Port $Port -TimeoutSeconds $TimeoutSeconds
Write-Host "Logs: logs\app.stdout.log, logs\app.stderr.log"
