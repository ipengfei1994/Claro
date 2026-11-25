[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$PostgreSQLServiceName,
    [string]$AdminUser = "postgres",
    [string]$DatabaseName = "claro",
    [string]$AppRole = "claro",
    [switch]$Seed
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "service_common.ps1")
if (-not $PSCmdlet.ShouldProcess("PostgreSQL database $DatabaseName", "Initialize Claro schema and role")) {
    return
}
if (-not (Test-Path $script:ClaroPython)) {
    throw "Virtual environment not found. Run scripts\claro.ps1 install first."
}
$postgres = Resolve-ClaroPostgreSQL -ServiceName $PostgreSQLServiceName
$ready = & $postgres.PgIsReady -h 127.0.0.1 -p 5432
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL is not ready. Run scripts\start_services.ps1 -Service PostgreSQL first."
}

$plainPassword = $env:CLARO_DB_PASSWORD
if (-not $plainPassword) {
    $securePassword = Read-Host "Enter the new Claro database password" -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
}
if ([string]::IsNullOrWhiteSpace($plainPassword) -or $plainPassword.Length -lt 12) {
    throw "CLARO_DB_PASSWORD must contain at least 12 characters."
}

$sql = Join-Path $script:ClaroProjectRoot "deploy\postgresql\init\001-create-claro.sql"
& $postgres.Psql -h 127.0.0.1 -p 5432 -U $AdminUser -d postgres -v ON_ERROR_STOP=1 `
    -v "db_name=$DatabaseName" -v "app_role=$AppRole" -v "claro_password=$plainPassword" -f $sql
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL role/database initialization failed."
}
$plainPassword = $null
Push-Location $script:ClaroProjectRoot
try {
    & $script:ClaroPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic migration failed."
    }
    & $script:ClaroPython -m alembic current
    if ($LASTEXITCODE -ne 0) {
        throw "Could not verify the Alembic revision."
    }
    if ($Seed) {
        & $script:ClaroPython -m claro seed
        if ($LASTEXITCODE -ne 0) {
            throw "Synthetic seed failed."
        }
    }
} finally {
    Pop-Location
}
