[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Plan','Sync')][string]$Action = 'Plan',
    [ValidateSet('WindowsToMac','MacToWindows')][string]$Direction = 'WindowsToMac',
    [string]$MacHost = 'macbookpro',
    [int]$MinAgeMinutes = 5,
    [string]$LedgerPath
)

$ErrorActionPreference = 'Stop'
if (-not $IsWindows) {
    throw 'Run this command on Windows. It supports both directions and uses the verified Windows-to-Mac SSH/SFTP connection.'
}

$rclone = (Get-Command rclone -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$ssh = (Get-Command ssh -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$sshConfig = @(& $ssh -G $MacHost)
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve SSH host: $MacHost" }

function Get-SshValue([string]$Name) {
    $line = $sshConfig | Where-Object { $_ -match "^$([regex]::Escape($Name))\s+" } | Select-Object -First 1
    if (-not $line) { return $null }
    return ($line -replace "^$([regex]::Escape($Name))\s+", '').Trim()
}

$hostName = Get-SshValue 'hostname'
$userName = Get-SshValue 'user'
$port = Get-SshValue 'port'
$identityFiles = @($sshConfig | Where-Object { $_ -match '^identityfile\s+' } | ForEach-Object {
    ($_ -replace '^identityfile\s+', '').Trim() -replace '^~', $HOME
})
$identityFile = $identityFiles | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $hostName -or -not $userName -or -not $port -or -not $identityFile) {
    throw "Incomplete SSH configuration for $MacHost."
}

& $ssh -o BatchMode=yes -o ConnectTimeout=15 $MacHost 'printf SESSION_SYNC_SSH_OK'
if ($LASTEXITCODE -ne 0) { throw "SSH preflight failed: $MacHost" }

$windowsRoot = [IO.Path]::GetFullPath((Join-Path $HOME '.codex'))
$macRoot = "/Users/$userName/.codex"
if (-not (Test-Path -LiteralPath $windowsRoot -PathType Container)) { throw "Windows Codex home missing: $windowsRoot" }

$remote = ':sftp:'
$sftpArgs = @(
    '--sftp-host', $hostName,
    '--sftp-user', $userName,
    '--sftp-port', $port,
    '--sftp-key-file', $identityFile
)
$knownHosts = Join-Path $HOME '.ssh/known_hosts'
if (Test-Path -LiteralPath $knownHosts -PathType Leaf) {
    $sftpArgs += @('--sftp-known-hosts-file',$knownHosts,'--sftp-host-key-algorithms','ssh-ed25519')
}
$filters = @(
    '--include', '/sessions/**.jsonl',
    '--include', '/archived_sessions/**.jsonl',
    '--exclude', '/**'
)
$age = "${MinAgeMinutes}m"
$source = if ($Direction -eq 'WindowsToMac') { $windowsRoot } else { "$remote$macRoot" }
$destination = if ($Direction -eq 'WindowsToMac') { "$remote$macRoot" } else { $windowsRoot }

$rcloneArgs = [System.Collections.Generic.List[string]]::new()
$rcloneArgs.Add('copy')
$rcloneArgs.Add($source)
$rcloneArgs.Add($destination)
foreach ($value in $sftpArgs + $filters) { $rcloneArgs.Add($value) }
$rcloneArgs.Add('--min-age'); $rcloneArgs.Add($age)
$rcloneArgs.Add('--immutable')
$rcloneArgs.Add('--checksum')
$rcloneArgs.Add('--create-empty-src-dirs')
$rcloneArgs.Add('--metadata')
$rcloneArgs.Add('--stats-one-line')
$rcloneArgs.Add('--stats'); $rcloneArgs.Add('10s')
if ($Action -eq 'Plan') { $rcloneArgs.Add('--dry-run') }

$started = Get-Date
$output = @(& $rclone @rcloneArgs 2>&1)
$exitCode = $LASTEXITCODE
$completed = Get-Date

if (-not $LedgerPath) {
    $ledgerRoot = Join-Path $HOME '.ai-control-center/cross-device/ledgers'
    New-Item -ItemType Directory -Force -Path $ledgerRoot | Out-Null
    $LedgerPath = Join-Path $ledgerRoot 'codex-sessions.jsonl'
}
$record = [ordered]@{
    timestamp = $completed.ToString('o')
    action = $Action
    direction = $Direction
    transport = 'rclone-sftp-over-verified-ssh'
    source_root = if ($Direction -eq 'WindowsToMac') { '$HOME/.codex' } else { '$MAC_HOME/.codex' }
    destination_root = if ($Direction -eq 'WindowsToMac') { '$MAC_HOME/.codex' } else { '$HOME/.codex' }
    includes = @('sessions/**/*.jsonl','archived_sessions/**/*.jsonl')
    excludes = @('auth.json','history.jsonl','state*.sqlite*','logs','cache','tmp')
    min_age_minutes = $MinAgeMinutes
    exit_code = $exitCode
    duration_seconds = [math]::Round(($completed - $started).TotalSeconds, 3)
}
Add-Content -LiteralPath $LedgerPath -Value ($record | ConvertTo-Json -Compress) -Encoding utf8NoBOM

if ($exitCode -ne 0) {
    $safeTail = @($output | Select-Object -Last 20) -join [Environment]::NewLine
    throw "Codex session sync failed without overwriting conflicts.`n$safeTail"
}
[ordered]@{
    status = if ($Action -eq 'Plan') { 'planned' } else { 'synced' }
    direction = $Direction
    min_age_minutes = $MinAgeMinutes
    immutable = $true
    ledger = $LedgerPath
    note = 'Only stable JSONL transcripts are copied. Authentication, SQLite/WAL/SHM, logs, cache, temp, and history are excluded.'
} | ConvertTo-Json -Compress
