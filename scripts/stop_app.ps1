# Stop the Claro Streamlit application that this project started.
#
# Only the PID recorded in runtime\app.pid is stopped, and only after its command
# line is verified to belong to Claro. Unrelated Python processes are never touched.

[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")

Stop-ClaroApp
