# Run the Phase 06 end-to-end demo (14 steps) and print the report.
#
# The demo exercises: pipeline processing of 7 scenarios, case claim, manual
# override, mute enforcement, temporary ban, release, feedback, and strategy
# replay. It is idempotent: running it twice reports "duplicate" rather than
# creating a second copy of the data.
#
# Options:
#   -Status   show what the demo dataset currently contains and exit
#   -Clean    delete the demo dataset and its dependent rows (asks for confirmation)

[CmdletBinding()]
param(
    [switch]$Status,
    [switch]$Clean,
    [switch]$Yes,
    [string]$Output
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")

Push-Location $script:ClaroProjectRoot
try {
    if ($Status) {
        & $script:ClaroPython -m claro.cli demo-status
        exit $LASTEXITCODE
    }

    if ($Clean) {
        if (-not $Yes) {
            $answer = Read-Host "This deletes ONLY the demo dataset and its dependent rows. Type 'yes' to continue"
            if ($answer -ne "yes") {
                Write-Host "Cancelled."
                exit 1
            }
        }
        & $script:ClaroPython -m claro.cli demo-clean --yes
        exit $LASTEXITCODE
    }

    if (-not $Output) {
        $Output = Join-Path $script:ClaroRuntimeRoot "demo_report.json"
    }
    New-Item -ItemType Directory -Force -Path $script:ClaroRuntimeRoot | Out-Null

    & $script:ClaroPython -m claro.cli demo-run --output $Output
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        Write-Host ""
        Write-Host "Demo report written to $Output"
        Write-Host "Next: scripts\start_app.ps1, then open the Overview page in the browser."
    }
    exit $code
} finally {
    Pop-Location
}
