param(
    [ValidateSet('setup', 'install', 'start', 'stop', 'status', 'uninstall')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'

$TaskName = 'Codex Telegram Bot'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BotScript = Join-Path $Root 'codex_telegram_bot.py'
$Setup = Join-Path $Root 'codex_telegram_setup.py'
$EnvFile = Join-Path $env:USERPROFILE '.codex\telegram.env'

function Get-Pythonw {
    $preferred = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\pythonw.exe'
    if (Test-Path -LiteralPath $preferred) {
        return $preferred
    }

    $candidates = Get-Command pythonw.exe -All -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Source |
        Where-Object { $_ -and $_ -notmatch '\\hermes\\' }
    if ($candidates) {
        return ($candidates | Select-Object -First 1)
    }
    return 'python.exe'
}

function Assert-Config {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        throw "설정 파일이 없습니다: $EnvFile"
    }
    $text = Get-Content -LiteralPath $EnvFile -Raw -Encoding UTF8
    if ($text -notmatch '(?m)^CODEX_TELEGRAM_BOT_TOKEN=.+') {
        throw "CODEX_TELEGRAM_BOT_TOKEN이 비어 있습니다: $EnvFile"
    }
}

switch ($Action) {
    'setup' {
        python $Setup
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        & $PSCommandPath install
    }
    'install' {
        Assert-Config
        $pythonw = Get-Pythonw
        $taskAction = New-ScheduledTaskAction `
            -Execute $pythonw `
            -Argument ('"{0}"' -f $BotScript)
        $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        # Watchdog: fires every 10 min. With MultipleInstances=IgnoreNew it is a
        # no-op while the bot is alive, but relaunches it if it ever died.
        $watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 10) `
            -RepetitionDuration (New-TimeSpan -Days 3650)
        $settings = New-ScheduledTaskSettingsSet `
            -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit (New-TimeSpan -Days 0) `
            -RestartCount 3 `
            -RestartInterval (New-TimeSpan -Minutes 1) `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger @($logonTrigger, $watchdog) -Settings $settings -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
        Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
    }
    'start' {
        Assert-Config
        Start-ScheduledTask -TaskName $TaskName
        Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
    }
    'stop' {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Get-CimInstance Win32_Process |
            Where-Object { $_.Name -match '^pythonw?(\.exe)?$' -and $_.CommandLine -match 'codex_telegram_bot.py' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Select-Object TaskName, State
    }
    'status' {
        Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Select-Object TaskName, State
        Get-CimInstance Win32_Process |
            Where-Object { $_.Name -match '^pythonw?(\.exe)?$' -and $_.CommandLine -match 'codex_telegram_bot.py' } |
            Select-Object ProcessId, Name, CommandLine
    }
    'uninstall' {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    }
}
