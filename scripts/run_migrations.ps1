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

Write-Host "Current revision:"
& $script:ClaroPython -m alembic current
if ($LASTEXITCODE -ne 0) { throw "alembic current failed." }

if ($Sql) {
    Write-Host "SQL preview for $Revision:"
    & $script:ClaroPython -m alembic upgrade $Revision --sql
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade --sql failed." }
    exit 0
}

Write-Host "Applying migrations up to $Revision ..."
& $script:ClaroPython -m alembic upgrade $Revision
if ($LASTEXITCODE -ne 0) {
    throw "alembic upgrade failed. The database may be partially migrated; inspect the output above."
}

Write-Host "Revision after upgrade:"
& $script:ClaroPython -m alembic current
