[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$JdbcUrl,
    [Parameter(Mandatory = $true)]
    [string]$WarehouseRoot,
    [Parameter(Mandatory = $true)]
    [string]$OdsRoot,
    [string]$BeelinePath = "beeline",
    [string]$ExportDirectory,
    [switch]$SkipLoad
)

$ErrorActionPreference = "Stop"
$HiveDirectory = Split-Path -Parent $PSScriptRoot
$beelineCommand = Get-Command $BeelinePath -ErrorAction SilentlyContinue
if (-not $beelineCommand -and (Test-Path $BeelinePath)) {
    $beelineCommand = Get-Item $BeelinePath
}
if (-not $beelineCommand) {
    throw "Beeline was not found. Hive SQL was not executed. Provide -BeelinePath after installing a native Hive distribution."
}
$beelineExecutable = if ($beelineCommand.Source) { $beelineCommand.Source } else { $beelineCommand.FullName }

function Invoke-HiveScript {
    param([string]$Path)
    Write-Host "Executing Hive SQL: $Path"
    & $beelineExecutable -u $JdbcUrl "--hivevar=warehouse_root=$WarehouseRoot" `
        "--hivevar=ods_root=$OdsRoot" -f $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Hive SQL failed with exit code ${LASTEXITCODE}: $Path"
    }
}

Invoke-HiveScript (Join-Path $HiveDirectory "00_create_databases.sql")
Invoke-HiveScript (Join-Path $HiveDirectory "10_create_ods.sql")
if (-not $SkipLoad) {
    if (-not $ExportDirectory) {
        throw "Provide -ExportDirectory containing load_ods.sql, or use -SkipLoad."
    }
    Invoke-HiveScript (Join-Path $ExportDirectory "load_ods.sql")
}
Invoke-HiveScript (Join-Path $HiveDirectory "20_build_dwd.sql")
Invoke-HiveScript (Join-Path $HiveDirectory "30_build_dws_ads.sql")
Invoke-HiveScript (Join-Path $HiveDirectory "40_data_quality.sql")
Write-Host "Hive warehouse scripts completed."
