# Generate (and load) the synthetic dataset used for the walkthrough.
#
# Thin wrapper around generate_data.ps1 with demo-sized defaults, so the demo has
# a populated analytics layer without a 50,000-row load. Pass larger values
# explicitly when you want a heavier dataset.
#
# Note: the *Phase 06 demo scenarios* (14 steps, fixed ids) are created by
# run_demo.ps1; this script only produces the background synthetic population.

[CmdletBinding()]
param(
    [int]$Messages = 5000,
    [int]$Players = 500,
    [int]$Servers = 10,
    [int]$Alliances = 50,
    [int]$Seed = 20261125,
    [string]$Name = "phase-06-demo-population"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")

Write-Host "Generating and loading $Messages messages (seed $Seed) as '$Name' ..."
& (Join-Path $PSScriptRoot "generate_data.ps1") -Load -Seed $Seed -Players $Players `
    -Servers $Servers -Alliances $Alliances -Messages $Messages -Name $Name
if ($LASTEXITCODE -ne 0) {
    throw "Synthetic data generation failed."
}

Write-Host "Running relational and distribution checks ..."
& $script:ClaroPython -m claro.cli check-data --dataset $Name
if ($LASTEXITCODE -ne 0) {
    Write-Warning "check-data reported problems; inspect the output above."
}
