# Apply database migrations with Alembic.
#
# Prints the current revision before and after, so a failed migration is obvious.
# Use -Revision to target a specific revision, and -Sql to preview the SQL only.

[CmdletBinding()]
param(
    [string]$Revision = "head",
    [switch]$Sql
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")

if (-not (Test-Path $script:ClaroPython)) {
    throw "Python virtual environment not found at .venv."
}

# Alembic writes its INFO logging to stderr. Windows PowerShell 5.1 turns native
# stderr into a terminating NativeCommandError while $ErrorActionPreference is
# "Stop", which aborts the script before the exit code can be inspected. Every
# call therefore runs with "Continue" and the exit code is checked explicitly.
function Invoke-Alembic {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = & $script:ClaroPython -m alembic @Arguments 2>&1 | ForEach-Object { "$_" }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    $lines | ForEach-Object { Write-Host $_ }
    return $exitCode
}

Write-Host "Current revision:"
$code = Invoke-Alembic current
if ($code -ne 0) { throw "alembic current failed (exit $code)." }

if ($Sql) {
    Write-Host "SQL preview for ${Revision}:"
    $code = Invoke-Alembic upgrade $Revision --sql
    if ($code -ne 0) { throw "alembic upgrade --sql failed (exit $code)." }
    exit 0
}

Write-Host "Applying migrations up to $Revision ..."
$code = Invoke-Alembic upgrade $Revision
if ($code -ne 0) {
    throw "alembic upgrade failed (exit $code). The database may be partially migrated; inspect the output above."
}

Write-Host "Revision after upgrade:"
$code = Invoke-Alembic current
if ($code -ne 0) { throw "alembic current failed (exit $code)." }
