[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "start", "start-native", "migrate", "seed", "test", "check", "check-native", "stop-native", "stop")]
    [string]$Command = "start",
    [switch]$Full,
    [switch]$Integration
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Invoke-ClaroPython {
    param([string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

function Test-PythonEnvironment {
    if (-not (Test-Path $Python)) {
        throw "Virtual environment not found. Run: .\scripts\claro.ps1 install"
    }
}

function Resolve-RedisExecutable {
    param([string]$Name)

    $command = Get-Command "$Name.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $packageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $packageRoot) {
        $package = Get-ChildItem -Path $packageRoot -Directory -Filter "taizod1024.redis-windows-fork_*" |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($package) {
            $candidate = Join-Path $package.FullName "$Name.exe"
            if (Test-Path $candidate) {
                return $candidate
            }
        }
    }

    throw "$Name was not found. Install Redis with: winget install taizod1024.redis-windows-fork"
}

function Resolve-JavaHome {
    $java = Get-Command java.exe -ErrorAction SilentlyContinue
    if ($java) {
        return Split-Path -Parent $java.Source
    }

    $microsoftRoot = Join-Path $env:ProgramFiles "Microsoft"
    if (Test-Path $microsoftRoot) {
        $jdk = Get-ChildItem -Path $microsoftRoot -Directory -Filter "jdk-17*-hotspot" |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($jdk) {
            $javaPath = Join-Path $jdk.FullName "bin\java.exe"
            if (Test-Path $javaPath) {
                return $jdk.FullName
            }
        }
    }

    throw "Java 17 was not found. Install it with: winget install Microsoft.OpenJDK.17"
}

function Get-KafkaPaths {
    $kafkaRoot = Join-Path $ProjectRoot "runtime\kafka"
    if (-not (Test-Path $kafkaRoot)) {
        throw "Kafka distribution was not found under runtime\kafka."
    }

    $kafkaHome = Get-ChildItem -Path $kafkaRoot -Directory |
        Where-Object { $_.Name -like "kafka_2.*-*" } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if (-not $kafkaHome) {
        throw "Kafka distribution was not found under runtime\kafka."
    }

    [pscustomobject]@{
        Home = $kafkaHome.FullName
        JavaHome = Resolve-JavaHome
    }
}

function Invoke-KafkaJava {
    param(
        $Paths,
        [string]$Class,
        [string[]]$Arguments
    )

    $java = Join-Path $Paths.JavaHome "bin\java.exe"
    $classPath = Join-Path $Paths.Home "libs\*"
    $log4j = "file:" + (Join-Path $Paths.Home "config\tools-log4j.properties")
    & $java "-Dlog4j.configuration=$log4j" -cp $classPath $Class @Arguments
}

function Invoke-NativeProbe {
    param([scriptblock]$Action)

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Action
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Test-RunningService {
    param(
        [string]$PidFile,
        [string]$ProcessName
    )

    if (-not (Test-Path $PidFile)) {
        return $false
    }

    $servicePid = 0
    if (-not [int]::TryParse((Get-Content -Path $PidFile -Raw).Trim(), [ref]$servicePid)) {
        return $false
    }

    $process = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
    return $null -ne $process -and $process.ProcessName -eq $ProcessName
}

function Start-NativeRedis {
    $redisServer = Resolve-RedisExecutable "redis-server"
    $redisCli = Resolve-RedisExecutable "redis-cli"
    $runtimeRoot = Join-Path $ProjectRoot "runtime"
    $logRoot = Join-Path $ProjectRoot "logs"
    $pidFile = Join-Path $runtimeRoot "redis.pid"
    New-Item -ItemType Directory -Force -Path $runtimeRoot, $logRoot | Out-Null

    if (Test-RunningService -PidFile $pidFile -ProcessName "redis-server") {
        Write-Host "Redis is already running."
        return
    }

    $config = "deploy/redis/redis.conf"
    $process = Start-Process -FilePath $redisServer -ArgumentList @($config) -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot "redis.stdout.log") `
        -RedirectStandardError (Join-Path $logRoot "redis.stderr.log")
    Set-Content -Path $pidFile -Value $process.Id

    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        $response = Invoke-NativeProbe { & $redisCli -h 127.0.0.1 -p 6379 ping 2>$null }
        if ($LASTEXITCODE -eq 0 -and $response -eq "PONG") {
            Write-Host "Redis is ready on 127.0.0.1:6379."
            return
        }
        if ($process.HasExited) {
            throw "Redis exited during startup. Check logs\redis.stderr.log."
        }
    }

    throw "Redis did not become ready. Check logs\redis.stderr.log."
}

function Ensure-ClaroKafkaTopic {
    param($Paths)

    $topics = Invoke-KafkaJava -Paths $Paths -Class "org.apache.kafka.tools.TopicCommand" `
        -Arguments @("--bootstrap-server", "127.0.0.1:9092", "--list")
    if ($LASTEXITCODE -ne 0) {
        throw "Kafka topic list could not be read."
    }
    if ($topics -notcontains "claro.content.events.v1") {
        Invoke-KafkaJava -Paths $Paths -Class "org.apache.kafka.tools.TopicCommand" `
            -Arguments @(
                "--bootstrap-server", "127.0.0.1:9092", "--create", "--if-not-exists",
                "--topic", "claro.content.events.v1", "--partitions", "1",
                "--replication-factor", "1"
            )
        if ($LASTEXITCODE -ne 0) {
            throw "The Claro Kafka topic could not be created."
        }
    }
}

function Start-NativeKafka {
    $paths = Get-KafkaPaths
    $runtimeRoot = Join-Path $ProjectRoot "runtime"
    $logRoot = Join-Path $ProjectRoot "logs"
    $kafkaLogDir = Join-Path $runtimeRoot "kafka-logs"
    $pidFile = Join-Path $runtimeRoot "kafka.pid"
    New-Item -ItemType Directory -Force -Path $runtimeRoot, $logRoot, $kafkaLogDir | Out-Null

    if (Test-RunningService -PidFile $pidFile -ProcessName "java") {
        Ensure-ClaroKafkaTopic -Paths $paths
        Write-Host "Kafka is already running; topic claro.content.events.v1 is available."
        return
    }

    $env:JAVA_HOME = $paths.JavaHome
    $env:PATH = "$($paths.JavaHome)\bin;$env:PATH"
    $config = Join-Path $ProjectRoot "deploy\kafka\server.properties"

    if (-not (Test-Path (Join-Path $kafkaLogDir "meta.properties"))) {
        $clusterLines = @(Invoke-KafkaJava -Paths $paths -Class "kafka.tools.StorageTool" `
            -Arguments @("random-uuid"))
        if ($LASTEXITCODE -ne 0 -or $clusterLines.Count -eq 0) {
            throw "Failed to generate a Kafka cluster ID."
        }
        $clusterId = $clusterLines[0].Trim()
        Invoke-KafkaJava -Paths $paths -Class "kafka.tools.StorageTool" `
            -Arguments @("format", "-t", $clusterId, "-c", $config)
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to format Kafka KRaft storage."
        }
    }

    $java = Join-Path $paths.JavaHome "bin\java.exe"
    $classPath = Join-Path $paths.Home "libs\*"
    $log4j = "file:" + (Join-Path $paths.Home "config\log4j.properties")
    $arguments = @(
        "-Xms256m",
        "-Xmx512m",
        "-Djava.awt.headless=true",
        "-Dlog4j.configuration=$log4j",
        "-cp",
        $classPath,
        "kafka.Kafka",
        $config
    )
    $process = Start-Process -FilePath $java -ArgumentList $arguments -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot "kafka.stdout.log") `
        -RedirectStandardError (Join-Path $logRoot "kafka.stderr.log")
    Set-Content -Path $pidFile -Value $process.Id

    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 1
        $null = Invoke-NativeProbe {
            Invoke-KafkaJava -Paths $paths -Class "org.apache.kafka.tools.TopicCommand" `
                -Arguments @("--bootstrap-server", "127.0.0.1:9092", "--list") 2>$null
        }
        if ($LASTEXITCODE -eq 0) {
            Ensure-ClaroKafkaTopic -Paths $paths
            Write-Host "Kafka is ready on 127.0.0.1:9092; topic claro.content.events.v1 is available."
            return
        }
        if ($process.HasExited) {
            throw "Kafka exited during startup. Check logs\kafka.stderr.log."
        }
    }

    throw "Kafka did not become ready. Check logs\kafka.stderr.log."
}

function Start-NativeServices {
    Start-NativeRedis
    Start-NativeKafka
}

function Stop-NativeService {
    param(
        [string]$PidFile,
        [string]$ProcessName,
        [string]$CommandLinePattern
    )

    if (-not (Test-Path $PidFile)) {
        return
    }

    $servicePid = 0
    if (-not [int]::TryParse((Get-Content -Path $PidFile -Raw).Trim(), [ref]$servicePid)) {
        throw "Invalid PID file: $PidFile"
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid" -ErrorAction SilentlyContinue
    if (-not $process) {
        Remove-Item -Path $PidFile
        return
    }
    if ($process.Name -ne $ProcessName -or $process.CommandLine -notlike $CommandLinePattern) {
        throw "PID $servicePid does not match the expected Claro service; refusing to stop it."
    }

    Stop-Process -Id $servicePid
    Wait-Process -Id $servicePid -Timeout 15 -ErrorAction SilentlyContinue
    Remove-Item -Path $PidFile
}

function Stop-NativeServices {
    Stop-NativeService -PidFile (Join-Path $ProjectRoot "runtime\kafka.pid") `
        -ProcessName "java.exe" -CommandLinePattern "*kafka.Kafka*"
    Stop-NativeService -PidFile (Join-Path $ProjectRoot "runtime\redis.pid") `
        -ProcessName "redis-server.exe" -CommandLinePattern "*redis-server*"
    Write-Host "Native Redis and Kafka services stopped. Data files were preserved."
}

switch ($Command) {
    "install" {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if (-not $launcher) {
            throw "Python Launcher was not found. Install Python 3.12 first."
        }
        & py -3.12 --version
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.12 is required."
        }
        if (-not (Test-Path $Python)) {
            & py -3.12 -m venv (Join-Path $ProjectRoot ".venv")
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to create the virtual environment."
            }
        }
        Push-Location $ProjectRoot
        try {
            Invoke-ClaroPython @("-m", "pip", "install", "-e", ".[dev]")
        } finally {
            Pop-Location
        }
        $envPath = Join-Path $ProjectRoot ".env"
        if (-not (Test-Path $envPath)) {
            $template = if ($Full) { ".env.full.example" } else { ".env.example" }
            Copy-Item (Join-Path $ProjectRoot $template) $envPath
            Write-Host "Created .env from $template. Existing .env files are never overwritten."
        } else {
            Write-Host ".env already exists; leaving it unchanged."
        }
        if ($Full) {
            Write-Warning "Configure %APPDATA%\postgresql\pgpass.conf before full-mode startup."
        }
    }
    "start-native" {
        Start-NativeServices
    }
    "start" {
        Test-PythonEnvironment
        Push-Location $ProjectRoot
        try {
            Invoke-ClaroPython @("-m", "alembic", "upgrade", "head")
            Invoke-ClaroPython @("-m", "claro", "check-services")
            Invoke-ClaroPython @("-m", "claro", "serve")
        } finally {
            Pop-Location
        }
    }
    "migrate" {
        Test-PythonEnvironment
        Push-Location $ProjectRoot
        try {
            Invoke-ClaroPython @("-m", "alembic", "upgrade", "head")
            Invoke-ClaroPython @("-m", "alembic", "current")
            Invoke-ClaroPython @("-m", "claro", "check-db")
        } finally {
            Pop-Location
        }
    }
    "seed" {
        Test-PythonEnvironment
        Push-Location $ProjectRoot
        try {
            Invoke-ClaroPython @("-m", "claro", "seed")
        } finally {
            Pop-Location
        }
    }
    "test" {
        Test-PythonEnvironment
        Push-Location $ProjectRoot
        try {
            Invoke-ClaroPython @("-m", "ruff", "check", "src", "tests", "migrations")
            if ($Integration) {
                Invoke-ClaroPython @("-m", "pytest", "-m", "integration", "-q")
            } else {
                Invoke-ClaroPython @("-m", "pytest", "-q")
            }
        } finally {
            Pop-Location
        }
    }
    "check" {
        Test-PythonEnvironment
        Push-Location $ProjectRoot
        try {
            Invoke-ClaroPython @("-m", "claro", "check-config")
            Invoke-ClaroPython @("-m", "claro", "check-services")
        } finally {
            Pop-Location
        }
    }
    "check-native" {
        foreach ($name in @("psql", "pg_isready")) {
            $found = Get-Command $name -ErrorAction SilentlyContinue
            if ($found) {
                Write-Host "${name}: $($found.Source)"
            } else {
                Write-Host "${name}: not found"
            }
        }

        try {
            $redisServer = Resolve-RedisExecutable "redis-server"
            $redisCli = Resolve-RedisExecutable "redis-cli"
            Write-Host "redis-server: $redisServer"
            & $redisServer --version
            $response = Invoke-NativeProbe { & $redisCli -h 127.0.0.1 -p 6379 ping 2>$null }
            Write-Host "Redis PING: $response"
        } catch {
            Write-Warning "Redis check failed: $($_.Exception.Message)"
        }

        try {
            $paths = Get-KafkaPaths
            $java = Join-Path $paths.JavaHome "bin\java.exe"
            Write-Host "java: $java"
            Invoke-NativeProbe { & $java -version 2>&1 } | ForEach-Object { Write-Host $_ }
            Write-Host "Kafka: $($paths.Home)"
            $env:JAVA_HOME = $paths.JavaHome
            $env:PATH = "$($paths.JavaHome)\bin;$env:PATH"
            Invoke-NativeProbe {
                Invoke-KafkaJava -Paths $paths -Class "org.apache.kafka.tools.TopicCommand" `
                    -Arguments @("--bootstrap-server", "127.0.0.1:9092", "--list") 2>&1
            } | ForEach-Object { Write-Host $_ }
            if ($LASTEXITCODE -ne 0) {
                throw "Kafka topic listing failed."
            }
        } catch {
            Write-Warning "Kafka check failed: $($_.Exception.Message)"
        }
    }
    "stop-native" {
        Stop-NativeServices
    }
    "stop" {
        Stop-NativeServices
    }
}
