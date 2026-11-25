# Run the Claro test suites.
#
#   -Suite unit        fast, no external services (default)
#   -Suite integration requires PostgreSQL / Kafka / Redis to be running
#   -Suite all         both, unit first
#   -Suite ui          render every screen through Streamlit's AppTest
#
# Exit code is pytest's, so this can gate a commit or a CI job.

[CmdletBinding()]
param(
    [ValidateSet("unit", "integration", "all", "ui")]
    [string]$Suite = "unit",
    [string]$Keyword = "",
    [switch]$Coverage
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")

if (-not (Test-Path $script:ClaroPython)) {
    throw "Python virtual environment not found at .venv."
}

$targets = @{
    unit = @("tests/unit")
    integration = @("tests/integration")
    ui = @("tests/ui")
    all = @("tests/unit", "tests/integration", "tests/ui")
}[$Suite]

# pyproject.toml sets ``-m 'not integration'`` as a default so plain ``pytest``
# stays fast. That default would also deselect the integration suite when it is
# requested explicitly, so the marker is restated here (the command-line value
# overrides addopts).
$marker = @{
    unit = "not integration"
    ui = "not integration"
    integration = "integration"
    all = "integration or not integration"
}[$Suite]

$arguments = @("-m", "pytest") + $targets + @("-q", "-m", $marker)
if ($Keyword) { $arguments += @("-k", $Keyword) }
if ($Coverage) {
    $arguments += @("--cov=claro", "--cov-report=term-missing", "--cov-report=html:runtime/coverage")
}

Write-Host "Running: python $($arguments -join ' ')"
Push-Location $script:ClaroProjectRoot
try {
    & $script:ClaroPython @arguments
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($code -ne 0) {
    Write-Host "Tests failed with exit code $code."
}
exit $code
