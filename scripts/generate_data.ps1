[CmdletBinding()]
param(
    [int]$Seed = 20261125,
    [int]$Players = 5000,
    [int]$Servers = 10,
    [int]$Alliances = 500,
    [int]$Messages = 50000,
    [int]$PolicyRules = 40,
    [int]$Days = 31,
    [string]$Name,
    [string]$Output,
    [switch]$Load,
    [int]$BatchSize = 1000,
    [switch]$Clean,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")
if (-not (Test-Path $script:ClaroPython)) {
    throw "Virtual environment not found. Run scripts\claro.ps1 install first."
}
if (@($Players, $Servers, $Alliances, $Messages, $PolicyRules, $Days, $BatchSize |
        Where-Object { $_ -lt 1 }).Count -gt 0) {
    throw "Scale and batch-size values must be positive."
}
if ($Output -and (Test-Path $Output) -and -not $Force -and -not $Load) {
    throw "Output already exists: $Output. Use -Force to overwrite it explicitly."
}
$arguments = @("-m", "claro", $(if ($Load) { "load-data" } else { "generate-data" }),
    "--seed", $Seed, "--players", $Players, "--servers", $Servers,
    "--alliances", $Alliances, "--messages", $Messages,
    "--policy-rules", $PolicyRules, "--days", $Days)
if ($Name) { $arguments += @("--name", $Name) }
if ($Load) {
    $arguments += @("--batch-size", $BatchSize)
    if ($Clean) { $arguments += "--clean" }
} elseif ($Output) {
    $arguments += @("--output", $Output)
}
Push-Location $script:ClaroProjectRoot
try {
    & $script:ClaroPython @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Synthetic data command failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
