$script:ClaroProjectRoot = Split-Path -Parent $PSScriptRoot
$script:ClaroRuntimeRoot = Join-Path $script:ClaroProjectRoot "runtime"
$script:ClaroLogRoot = Join-Path $script:ClaroProjectRoot "logs"
$script:ClaroPython = Join-Path $script:ClaroProjectRoot ".venv\Scripts\python.exe"
$script:ClaroPhase02Topics = @(
    "game.messages.raw",
    "game.messages.processed",
    "game.risk.events",
    "game.moderation.events",
    "game.messages.retry",
    "game.messages.dead-letter"
)

function Resolve-ClaroRedisExecutable {
    param([string]$Name)
    $command = Get-Command "$Name.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $packageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $packageRoot) {
        $package = Get-ChildItem -Path $packageRoot -Directory -Filter "taizod1024.redis-windows-fork_*" |
            Sort-Object Name -Descending | Select-Object -First 1
        if ($package) {
            $candidate = Join-Path $package.FullName "$Name.exe"
            if (Test-Path $candidate) {
                return $candidate
            }
        }
    }
    throw "$Name was not found. Install Redis with: winget install taizod1024.redis-windows-fork"
}

function Resolve-ClaroJavaHome {
    $java = Get-Command java.exe -ErrorAction SilentlyContinue
    if ($java) {
        return Split-Path -Parent $java.Source
    }
    $microsoftRoot = Join-Path $env:ProgramFiles "Microsoft"
    if (Test-Path $microsoftRoot) {
        $jdk = Get-ChildItem -Path $microsoftRoot -Directory -Filter "jdk-17*-hotspot" |
            Sort-Object Name -Descending | Select-Object -First 1
        if ($jdk) {
            $javaPath = Join-Path $jdk.FullName "bin\java.exe"
            if (Test-Path $javaPath) {
                return $jdk.FullName
            }
        }
    }
    throw "Java 17 was not found. Install it with: winget install Microsoft.OpenJDK.17"
}

function Get-ClaroKafkaPaths {
    $kafkaRoot = Join-Path $script:ClaroRuntimeRoot "kafka"
    if (-not (Test-Path $kafkaRoot)) {
        throw "Kafka distribution was not found under runtime\kafka."
    }
    $kafkaHome = Get-ChildItem -Path $kafkaRoot -Directory |
        Where-Object { $_.Name -like "kafka_2.*-*" } |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $kafkaHome) {
        throw "Kafka distribution was not found under runtime\kafka."
    }
    return [pscustomobject]@{
        Home = $kafkaHome.FullName
        JavaHome = Resolve-ClaroJavaHome
    }
}

function Resolve-ClaroPostgreSQL {
    param([string]$ServiceName)
    $psql = Get-Command psql.exe -ErrorAction SilentlyContinue
    $pgIsReady = Get-Command pg_isready.exe -ErrorAction SilentlyContinue
    if (-not $psql -or -not $pgIsReady) {
        throw "PostgreSQL 18 client tools were not found on PATH."
    }
    if ($ServiceName) {
        $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if (-not $service -or $service.Name -notlike "postgresql-x64-*") {
            throw "The specified PostgreSQL service is missing or has an unexpected name: $ServiceName"
        }
    } else {
        $services = @(Get-Service -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "postgresql-x64-*" })
        if ($services.Count -ne 1) {
            throw "Expected exactly one native PostgreSQL service; provide -PostgreSQLServiceName."
        }
        $service = $services[0]
    }
    return [pscustomobject]@{
        Psql = $psql.Source
        PgIsReady = $pgIsReady.Source
        ServiceName = $service.Name
        Service = $service
    }
}

function Invoke-ClaroKafkaJava {
    param($Paths, [string]$Class, [string[]]$Arguments)
    $java = Join-Path $Paths.JavaHome "bin\java.exe"
    $classPath = Join-Path $Paths.Home "libs\*"
    $log4j = "file:" + (Join-Path $Paths.Home "config\tools-log4j.properties")
    & $java "-Dlog4j.configuration=$log4j" -cp $classPath $Class @Arguments
}

function Invoke-ClaroProbe {
    param([scriptblock]$Action)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Action
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-ClaroPidProcess {
    [CmdletBinding()]
    param([string]$PidFile)
    $WhatIfPreference = $false
    if (-not (Test-Path $PidFile)) {
        return $null
    }
    $servicePid = 0
    if (-not [int]::TryParse((Get-Content -Path $PidFile -Raw).Trim(), [ref]$servicePid)) {
        throw "Invalid PID file: $PidFile"
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid" -ErrorAction SilentlyContinue
    if (-not $process) {
        return $null
    }
    return [pscustomobject]@{
        Pid = $servicePid
        Name = $process.Name
        CommandLine = $process.CommandLine
    }
}

function Test-ClaroOwnedProcess {
    param([string]$PidFile, [string]$ProcessName, [string]$CommandLinePattern)
    $process = Get-ClaroPidProcess -PidFile $PidFile
    if (-not $process) {
        return $null
    }
    if ($process.Name -ne $ProcessName -or $process.CommandLine -notlike $CommandLinePattern) {
        throw "PID $($process.Pid) does not match the expected Claro service; refusing to manage it."
    }
    return $process
}

function Start-ClaroRedis {
    $redisServer = Resolve-ClaroRedisExecutable "redis-server"
    $redisCli = Resolve-ClaroRedisExecutable "redis-cli"
    $pidFile = Join-Path $script:ClaroRuntimeRoot "redis.pid"
    New-Item -ItemType Directory -Force -Path $script:ClaroRuntimeRoot, $script:ClaroLogRoot | Out-Null
    $owned = Test-ClaroOwnedProcess -PidFile $pidFile -ProcessName "redis-server.exe" `
        -CommandLinePattern "*redis-server*redis.conf*"
    if ($owned) {
        Write-Host "Redis is already running under Claro PID $($owned.Pid)."
        return
    }
    $response = Invoke-ClaroProbe { & $redisCli -h 127.0.0.1 -p 6379 ping 2>$null }
    if ($LASTEXITCODE -eq 0 -and $response -eq "PONG") {
        throw "Port 6379 already has Redis, but no matching Claro PID file exists; refusing to adopt it."
    }
    $config = "deploy/redis/redis.conf"
    $process = Start-Process -FilePath $redisServer -ArgumentList @($config) `
        -WorkingDirectory $script:ClaroProjectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $script:ClaroLogRoot "redis.stdout.log") `
        -RedirectStandardError (Join-Path $script:ClaroLogRoot "redis.stderr.log")
    Set-Content -Path $pidFile -Value $process.Id
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        $response = Invoke-ClaroProbe { & $redisCli -h 127.0.0.1 -p 6379 ping 2>$null }
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

function Stop-ClaroRedis {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param()
    $pidFile = Join-Path $script:ClaroRuntimeRoot "redis.pid"
    $process = Test-ClaroOwnedProcess -PidFile $pidFile -ProcessName "redis-server.exe" `
        -CommandLinePattern "*redis-server*redis.conf*"
    if (-not $process) {
        if (Test-Path $pidFile) {
            Remove-Item -Path $pidFile
        }
        return
    }
    if ($PSCmdlet.ShouldProcess("Redis PID $($process.Pid)", "Stop Claro Redis")) {
        Stop-Process -Id $process.Pid
        Wait-Process -Id $process.Pid -Timeout 15 -ErrorAction SilentlyContinue
        Remove-Item -Path $pidFile
        Write-Host "Claro Redis stopped; persistent data was preserved."
    }
}

function Ensure-ClaroKafkaTopics {
    param($Paths)
    $topics = @(Invoke-ClaroKafkaJava -Paths $Paths -Class "org.apache.kafka.tools.TopicCommand" `
        -Arguments @("--bootstrap-server", "127.0.0.1:9092", "--list"))
    if ($LASTEXITCODE -ne 0) {
        throw "Kafka topic list could not be read."
    }
    foreach ($topic in $script:ClaroPhase02Topics) {
        if ($topics -notcontains $topic) {
            $null = Invoke-ClaroKafkaJava -Paths $Paths -Class "org.apache.kafka.tools.TopicCommand" `
                -Arguments @("--bootstrap-server", "127.0.0.1:9092", "--create", "--if-not-exists",
                    "--topic", $topic, "--partitions", "3", "--replication-factor", "1")
            if ($LASTEXITCODE -ne 0) {
                throw "Kafka topic could not be created: $topic"
            }
        }
    }
}

function Start-ClaroKafka {
    $paths = Get-ClaroKafkaPaths
    $kafkaLogDir = Join-Path $script:ClaroRuntimeRoot "kafka-logs"
    $pidFile = Join-Path $script:ClaroRuntimeRoot "kafka.pid"
    New-Item -ItemType Directory -Force -Path $script:ClaroRuntimeRoot, $script:ClaroLogRoot, $kafkaLogDir | Out-Null
    $owned = Test-ClaroOwnedProcess -PidFile $pidFile -ProcessName "java.exe" `
        -CommandLinePattern "*kafka.Kafka*server.properties*"
    if ($owned) {
        Ensure-ClaroKafkaTopics -Paths $paths
        Write-Host "Kafka is already running under Claro PID $($owned.Pid)."
        return
    }
    $config = Join-Path $script:ClaroProjectRoot "deploy\kafka\server.properties"
    if (-not (Test-Path (Join-Path $kafkaLogDir "meta.properties"))) {
        $clusterLines = @(Invoke-ClaroKafkaJava -Paths $paths -Class "kafka.tools.StorageTool" `
            -Arguments @("random-uuid"))
        if ($LASTEXITCODE -ne 0 -or $clusterLines.Count -eq 0) {
            throw "Failed to generate a Kafka cluster ID."
        }
        $null = Invoke-ClaroKafkaJava -Paths $paths -Class "kafka.tools.StorageTool" `
            -Arguments @("format", "-t", $clusterLines[0].Trim(), "-c", $config)
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to format Kafka KRaft storage."
        }
    }
    $java = Join-Path $paths.JavaHome "bin\java.exe"
    $classPath = Join-Path $paths.Home "libs\*"
    $log4j = "file:" + (Join-Path $paths.Home "config\log4j.properties")
    $arguments = @("-Xms256m", "-Xmx512m", "-Djava.awt.headless=true",
        "-Dlog4j.configuration=$log4j", "-cp", $classPath, "kafka.Kafka", $config)
    $process = Start-Process -FilePath $java -ArgumentList $arguments `
        -WorkingDirectory $script:ClaroProjectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $script:ClaroLogRoot "kafka.stdout.log") `
        -RedirectStandardError (Join-Path $script:ClaroLogRoot "kafka.stderr.log")
    Set-Content -Path $pidFile -Value $process.Id
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 1
        $null = Invoke-ClaroProbe {
            Invoke-ClaroKafkaJava -Paths $paths -Class "org.apache.kafka.tools.TopicCommand" `
                -Arguments @("--bootstrap-server", "127.0.0.1:9092", "--list") 2>$null
        }
        if ($LASTEXITCODE -eq 0) {
            Ensure-ClaroKafkaTopics -Paths $paths
            Write-Host "Kafka is ready on 127.0.0.1:9092; Phase 02 topics are available."
            return
        }
        if ($process.HasExited) {
            throw "Kafka exited during startup. Check logs\kafka.stderr.log."
        }
    }
    throw "Kafka did not become ready. Check logs\kafka.stderr.log."
}

function Stop-ClaroKafka {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param()
    $pidFile = Join-Path $script:ClaroRuntimeRoot "kafka.pid"
    $process = Test-ClaroOwnedProcess -PidFile $pidFile -ProcessName "java.exe" `
        -CommandLinePattern "*kafka.Kafka*server.properties*"
    if (-not $process) {
        if (Test-Path $pidFile) {
            Remove-Item -Path $pidFile
        }
        return
    }
    if ($PSCmdlet.ShouldProcess("Kafka PID $($process.Pid)", "Stop Claro Kafka")) {
        Stop-Process -Id $process.Pid
        Wait-Process -Id $process.Pid -Timeout 20 -ErrorAction SilentlyContinue
        Remove-Item -Path $pidFile
        Write-Host "Claro Kafka stopped; log data was preserved."
    }
}

function Start-ClaroPostgreSQL {
    param([string]$ServiceName)
    $postgres = Resolve-ClaroPostgreSQL -ServiceName $ServiceName
    if ($postgres.Service.Status -eq "Running") {
        Write-Host "PostgreSQL service $($postgres.ServiceName) is already running."
        return
    }
    Start-Service -Name $postgres.ServiceName
    Write-Host "PostgreSQL service $($postgres.ServiceName) started."
}

function Stop-ClaroPostgreSQL {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param([string]$ServiceName)
    $postgres = Resolve-ClaroPostgreSQL -ServiceName $ServiceName
    if ($postgres.Service.Status -ne "Running") {
        Write-Host "PostgreSQL service $($postgres.ServiceName) is already stopped."
        return
    }
    if ($PSCmdlet.ShouldProcess($postgres.ServiceName, "Stop native PostgreSQL service")) {
        Stop-Service -Name $postgres.ServiceName
        Write-Host "PostgreSQL service $($postgres.ServiceName) stopped."
    }
}

function Start-ClaroPipeline {
    param([string]$Topic = "game.messages.raw", [string]$ConsumerGroup = "claro.pipeline.v1",
        [string]$UiPort = "8501", [switch]$WithUi)
    if (-not (Test-Path $script:ClaroPython)) {
        throw "Virtual environment not found. Run scripts\claro.ps1 install first."
    }
    $consumerPidFile = Join-Path $script:ClaroRuntimeRoot "pipeline-consumer.pid"
    $consumer = Test-ClaroOwnedProcess -PidFile $consumerPidFile -ProcessName "python.exe" `
        -CommandLinePattern "*claro*kafka-consume*--persist*"
    if ($consumer) {
        Write-Host "Pipeline consumer is already running under Claro PID $($consumer.Pid)."
    } else {
        $arguments = @("-m", "claro", "kafka-consume", "--persist", "--continuous",
            "--topic", $Topic, "--group", $ConsumerGroup)
        $process = Start-Process -FilePath $script:ClaroPython -ArgumentList $arguments `
            -WorkingDirectory $script:ClaroProjectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $script:ClaroLogRoot "pipeline-consumer.stdout.log") `
            -RedirectStandardError (Join-Path $script:ClaroLogRoot "pipeline-consumer.stderr.log")
        Set-Content -Path $consumerPidFile -Value $process.Id
        Start-Sleep -Seconds 2
        if ($process.HasExited) {
            throw "Pipeline consumer exited during startup. Check logs\pipeline-consumer.stderr.log."
        }
        Write-Host "Pipeline consumer started with PID $($process.Id)."
    }
    if ($WithUi) {
        $uiPidFile = Join-Path $script:ClaroRuntimeRoot "streamlit.pid"
        $ui = Test-ClaroOwnedProcess -PidFile $uiPidFile -ProcessName "python.exe" `
            -CommandLinePattern "*claro*serve*"
        if ($ui) {
            Write-Host "Streamlit is already running under Claro PID $($ui.Pid)."
        } else {
            $env:CLARO_UI__PORT = $UiPort
            $process = Start-Process -FilePath $script:ClaroPython -ArgumentList @("-m", "claro", "serve") `
                -WorkingDirectory $script:ClaroProjectRoot -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $script:ClaroLogRoot "streamlit.stdout.log") `
                -RedirectStandardError (Join-Path $script:ClaroLogRoot "streamlit.stderr.log")
            Set-Content -Path $uiPidFile -Value $process.Id
            Write-Host "Streamlit started with PID $($process.Id) on port $UiPort."
        }
    }
}

function Stop-ClaroPipeline {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param()
    $specs = @(
        @{ File = "pipeline-consumer.pid"; Pattern = "*claro*kafka-consume*--persist*"; Name = "pipeline consumer" },
        @{ File = "streamlit.pid"; Pattern = "*claro*serve*"; Name = "Streamlit" }
    )
    foreach ($spec in $specs) {
        $pidFile = Join-Path $script:ClaroRuntimeRoot $spec.File
        $process = Test-ClaroOwnedProcess -PidFile $pidFile -ProcessName "python.exe" `
            -CommandLinePattern $spec.Pattern
        if (-not $process) {
            if (Test-Path $pidFile) {
                Remove-Item -Path $pidFile
            }
            continue
        }
        if ($PSCmdlet.ShouldProcess("$($spec.Name) PID $($process.Pid)", "Stop Claro $($spec.Name)")) {
            Stop-Process -Id $process.Pid
            Wait-Process -Id $process.Pid -Timeout 15 -ErrorAction SilentlyContinue
            Remove-Item -Path $pidFile
            Write-Host "Claro $($spec.Name) stopped."
        }
    }
}

function Start-ClaroServices {
    param([ValidateSet("All", "PostgreSQL", "Redis", "Kafka", "Pipeline")]
        [string]$Service = "All", [string]$PostgreSQLServiceName)
    New-Item -ItemType Directory -Force -Path $script:ClaroRuntimeRoot, $script:ClaroLogRoot | Out-Null
    if ($Service -in @("All", "PostgreSQL")) { Start-ClaroPostgreSQL -ServiceName $PostgreSQLServiceName }
    if ($Service -in @("All", "Redis")) { Start-ClaroRedis }
    if ($Service -in @("All", "Kafka")) { Start-ClaroKafka }
    if ($Service -eq "Pipeline") { Start-ClaroPipeline }
}

function Stop-ClaroServices {
    param([ValidateSet("All", "PostgreSQL", "Redis", "Kafka", "Pipeline")]
        [string]$Service = "All", [string]$PostgreSQLServiceName)
    if ($Service -in @("All", "Pipeline")) { Stop-ClaroPipeline }
    if ($Service -in @("All", "Kafka")) { Stop-ClaroKafka }
    if ($Service -in @("All", "Redis")) { Stop-ClaroRedis }
    if ($Service -in @("All", "PostgreSQL")) { Stop-ClaroPostgreSQL -ServiceName $PostgreSQLServiceName }
}

function Get-ClaroServiceStatus {
    param([string]$PostgreSQLServiceName)
    $results = New-Object System.Collections.Generic.List[object]
    try {
        $postgres = Resolve-ClaroPostgreSQL -ServiceName $PostgreSQLServiceName
        $ready = & $postgres.PgIsReady -h 127.0.0.1 -p 5432 2>$null
        $running = $postgres.Service.Status -eq "Running" -and $LASTEXITCODE -eq 0
        $results.Add([pscustomobject]@{
            Service = "PostgreSQL"; Running = $running
            Detail = "$($postgres.ServiceName): $($postgres.Service.Status); $ready"
        })
    } catch {
        $results.Add([pscustomobject]@{ Service = "PostgreSQL"; Running = $false; Detail = $_.Exception.Message })
    }
    try {
        $redisCli = Resolve-ClaroRedisExecutable "redis-cli"
        $response = Invoke-ClaroProbe { & $redisCli -h 127.0.0.1 -p 6379 ping 2>$null }
        $results.Add([pscustomobject]@{
            Service = "Redis"; Running = $LASTEXITCODE -eq 0 -and $response -eq "PONG"
            Detail = "127.0.0.1:6379 PING=$response"
        })
    } catch {
        $results.Add([pscustomobject]@{ Service = "Redis"; Running = $false; Detail = $_.Exception.Message })
    }
    try {
        $paths = Get-ClaroKafkaPaths
        $null = Invoke-ClaroProbe {
            Invoke-ClaroKafkaJava -Paths $paths -Class "org.apache.kafka.tools.TopicCommand" `
                -Arguments @("--bootstrap-server", "127.0.0.1:9092", "--list") 2>$null
        }
        $results.Add([pscustomobject]@{
            Service = "Kafka"; Running = $LASTEXITCODE -eq 0
            Detail = "127.0.0.1:9092 TopicCommand exit=$LASTEXITCODE"
        })
    } catch {
        $results.Add([pscustomobject]@{ Service = "Kafka"; Running = $false; Detail = $_.Exception.Message })
    }
    foreach ($spec in @(
        @{ File = "pipeline-consumer.pid"; Pattern = "*claro*kafka-consume*--persist*"; Name = "PipelineConsumer" },
        @{ File = "streamlit.pid"; Pattern = "*claro*serve*"; Name = "Streamlit" }
    )) {
        try {
            $process = Test-ClaroOwnedProcess -PidFile (Join-Path $script:ClaroRuntimeRoot $spec.File) `
                -ProcessName "python.exe" -CommandLinePattern $spec.Pattern
            $results.Add([pscustomobject]@{
                Service = $spec.Name; Running = $null -ne $process
                Detail = if ($process) { "PID $($process.Pid)" } else { "not running" }
            })
        } catch {
            $results.Add([pscustomobject]@{ Service = $spec.Name; Running = $false; Detail = $_.Exception.Message })
        }
    }
    return $results
}

function Test-ClaroEnvironment {
    $results = New-Object System.Collections.Generic.List[object]
    $python = Get-Command py -ErrorAction SilentlyContinue
    $results.Add([pscustomobject]@{
        Component = "Python 3.12"; OK = $null -ne $python -and (Test-Path $script:ClaroPython)
        Detail = if ($python) { & py -3.12 --version } else { "Python launcher missing" }
    })
    foreach ($item in @(
        @{ Component = "PostgreSQL"; Action = { Resolve-ClaroPostgreSQL | Out-Null } },
        @{ Component = "Redis"; Action = { Resolve-ClaroRedisExecutable "redis-server" | Out-Null } },
        @{ Component = "Kafka/Java"; Action = { Get-ClaroKafkaPaths | Out-Null } }
    )) {
        try {
            & $item.Action
            $results.Add([pscustomobject]@{ Component = $item.Component; OK = $true; Detail = "available" })
        } catch {
            $results.Add([pscustomobject]@{ Component = $item.Component; OK = $false; Detail = $_.Exception.Message })
        }
    }
    $expectedProcesses = @{
        5432 = "postgres"; 6379 = "redis-server"; 9092 = "java"
        9093 = "java"; 8501 = "python"
    }
    foreach ($port in @(5432, 6379, 9092, 9093, 8501)) {
        $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        $owner = if ($listener) { (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue).ProcessName }
        $results.Add([pscustomobject]@{
            Component = "Port $port"
            OK = -not $listener -or $owner -eq $expectedProcesses[$port]
            Detail = if ($listener) { "owned by $owner PID $($listener.OwningProcess)" } else { "available" }
        })
    }
    return $results
}
