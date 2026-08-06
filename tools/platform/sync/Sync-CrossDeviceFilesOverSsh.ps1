[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('WindowsToMac','MacToWindows')][string]$Direction,
    [Parameter(Mandatory)][string]$WindowsPath,
    [Parameter(Mandatory)][string]$MacPath,
    [ValidateSet('Plan','Sync')][string]$Action = 'Plan',
    [string]$MacHost,
    [string]$WindowsHost,
    [string]$ConfigPath,
    [int]$MinAgeMinutes = 0,
    [string[]]$Include,
    [string[]]$Exclude,
    [string]$LedgerPath,
    [string]$FilesFrom,
    [switch]$ValidateFilesFromOnly,
    [ValidateSet('Stop','PreserveAndReplace')][string]$ConflictMode = 'Stop'
)

$ErrorActionPreference = 'Stop'
if ($PSStyle) { $PSStyle.OutputRendering = 'PlainText' }
$env:NO_COLOR = '1'

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $HOME '.ai-control-center/cross-device/sync.json'
}
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    $syncConfig = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json -Depth 20
    if (-not $MacHost) { $MacHost = [string]$syncConfig.devices.mac.ssh_host }
    if (-not $WindowsHost) { $WindowsHost = [string]$syncConfig.devices.windows.ssh_host }
}
if (-not $MacHost -or -not $WindowsHost) {
    throw 'MacHost and WindowsHost must be supplied directly or through the private AICC sync config.'
}

$filesFromResolved = $null
$filesFromCount = 0
$filesFromSha256 = $null
if ($FilesFrom) {
    $filesFromResolved = [IO.Path]::GetFullPath($FilesFrom)
    if (-not (Test-Path -LiteralPath $filesFromResolved -PathType Leaf)) { throw "FilesFrom manifest missing: $filesFromResolved" }
    if ($PSBoundParameters.ContainsKey('Include') -or $PSBoundParameters.ContainsKey('Exclude')) { throw 'FilesFrom cannot be combined with Include or Exclude.' }
    $lineNumber = 0
    foreach ($rawLine in [IO.File]::ReadLines($filesFromResolved)) {
        $lineNumber++
        $line = $rawLine.Trim()
        if (-not $line) { continue }
        if ($line.StartsWith('/') -or $line.StartsWith('\') -or $line.Contains('\') -or $line.Contains(':')) {
            throw "FilesFrom line $lineNumber must be a slash-separated relative path: $line"
        }
        $parts = @($line.Split('/', [StringSplitOptions]::RemoveEmptyEntries))
        if ($parts.Count -eq 0 -or $parts -contains '..' -or $parts -contains '.') {
            throw "FilesFrom line $lineNumber contains an unsafe relative path: $line"
        }
        $filesFromCount++
    }
    if ($filesFromCount -eq 0) { throw 'FilesFrom manifest contains no paths.' }
    $filesFromSha256 = (Get-FileHash -LiteralPath $filesFromResolved -Algorithm SHA256).Hash.ToLowerInvariant()
}
if ($ValidateFilesFromOnly) {
    if (-not $FilesFrom) { throw 'ValidateFilesFromOnly requires FilesFrom.' }
    [ordered]@{status='valid';files_from=$filesFromResolved;file_count=$filesFromCount;sha256=$filesFromSha256} | ConvertTo-Json -Compress
    return
}
if ($WindowsPath -notmatch '^[A-Za-z]:[\\/]') { throw 'WindowsPath must be an absolute drive path.' }
if (-not $MacPath.StartsWith('/')) { throw 'MacPath must be absolute.' }
if ($MacPath -eq '/' -or $WindowsPath -match '^[A-Za-z]:[\\/]?$') {
    throw 'Refusing to synchronize a filesystem root.'
}

function Convert-ToWindowsSftpPath([string]$Path) {
    $normalized = $Path -replace '\\','/'
    if ($normalized -notmatch '^([A-Za-z]):/(.*)$') { throw "Invalid Windows path for SFTP: $Path" }
    return "/$($Matches[1].ToUpperInvariant()):/$($Matches[2])"
}

$rclone = (Get-Command rclone -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
if ($IsWindows) {
    $rcloneItem = Get-Item -LiteralPath $rclone -Force
    if ($rcloneItem.LinkType -and $rcloneItem.Target) {
        $rclone = [IO.Path]::GetFullPath([string]@($rcloneItem.Target)[0])
    }
}
$ssh = (Get-Command ssh -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$remoteHost = if ($IsWindows) { $MacHost } else { $WindowsHost }
$sshConfig = @(& $ssh -G $remoteHost)
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve SSH host: $remoteHost" }
function Get-SshValue([string]$Name) {
    $line = $sshConfig | Where-Object { $_ -match "^$([regex]::Escape($Name))\s+" } | Select-Object -First 1
    if (-not $line) { return $null }
    return ($line -replace "^$([regex]::Escape($Name))\s+", '').Trim()
}
$hostName = Get-SshValue 'hostname'
$userName = Get-SshValue 'user'
$port = Get-SshValue 'port'
$identityCandidates = @($sshConfig | Where-Object { $_ -match '^identityfile\s+' } | ForEach-Object {
    ($_ -replace '^identityfile\s+', '').Trim() -replace '^~', $HOME
}) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
if (-not $hostName -or -not $userName -or -not $port) { throw "Incomplete SSH configuration for $remoteHost." }
$identityFile = $null
foreach ($candidate in $identityCandidates) {
    & $ssh -T -q -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=15 -i $candidate $remoteHost 'exit 0'
    if ($LASTEXITCODE -eq 0) {
        $identityFile = $candidate
        break
    }
}
if (-not $identityFile) { throw "No configured identity successfully authenticated to $remoteHost." }

$windowsResolved = if ($IsWindows) { [IO.Path]::GetFullPath($WindowsPath) } else { $WindowsPath -replace '\\','/' }
$macResolved = if ($IsWindows) { $MacPath } else { [IO.Path]::GetFullPath($MacPath) }
$windowsRemotePath = Convert-ToWindowsSftpPath $windowsResolved
$remote = ':sftp:'
if ($IsWindows) {
    $source = if ($Direction -eq 'WindowsToMac') { $windowsResolved } else { "$remote$macResolved" }
    $destination = if ($Direction -eq 'WindowsToMac') { "$remote$macResolved" } else { $windowsResolved }
    if ($Direction -eq 'WindowsToMac' -and -not (Test-Path -LiteralPath $windowsResolved)) { throw "Source missing: $windowsResolved" }
} else {
    $source = if ($Direction -eq 'MacToWindows') { $macResolved } else { "$remote$windowsRemotePath" }
    $destination = if ($Direction -eq 'MacToWindows') { "$remote$windowsRemotePath" } else { $macResolved }
    if ($Direction -eq 'MacToWindows' -and -not (Test-Path -LiteralPath $macResolved)) { throw "Source missing: $macResolved" }
}

$rcloneArgs = [System.Collections.Generic.List[string]]::new()
foreach ($value in @('copy',$source,$destination,'--sftp-host',$hostName,'--sftp-user',$userName,'--sftp-port',$port,'--sftp-key-file',$identityFile)) { $rcloneArgs.Add($value) }
$knownHosts = Join-Path $HOME '.ssh/known_hosts'
if (Test-Path -LiteralPath $knownHosts -PathType Leaf) {
    foreach ($value in @('--sftp-known-hosts-file',$knownHosts,'--sftp-host-key-algorithms','ssh-ed25519')) { $rcloneArgs.Add($value) }
}
foreach ($pattern in @($Include)) {
    if ([string]::IsNullOrWhiteSpace($pattern)) { continue }
    $rcloneArgs.Add('--include'); $rcloneArgs.Add($pattern)
}
foreach ($pattern in @($Exclude)) {
    if ([string]::IsNullOrWhiteSpace($pattern)) { continue }
    $rcloneArgs.Add('--exclude'); $rcloneArgs.Add($pattern)
}
if ($filesFromResolved) {
    $rcloneArgs.Add('--files-from-raw'); $rcloneArgs.Add($filesFromResolved)
} elseif ($MinAgeMinutes -gt 0) {
    $rcloneArgs.Add('--min-age'); $rcloneArgs.Add("${MinAgeMinutes}m")
}
$backupRoot = $null
if ($ConflictMode -eq 'Stop') {
    $rcloneArgs.Add('--immutable')
} else {
    $backupLeaf = (Get-Date).ToString('yyyyMMdd-HHmmss')
    $backupRoot = if ($IsWindows) {
        if ($Direction -eq 'MacToWindows') {
            $destinationParent = Split-Path -Parent $windowsResolved
            $destinationLeaf = Split-Path -Leaf $windowsResolved
            Join-Path $destinationParent ".cross-device-conflicts/$destinationLeaf/$backupLeaf"
        } else {
            $destinationPath = $macResolved.TrimEnd('/')
            $separator = $destinationPath.LastIndexOf('/')
            $destinationParent = $destinationPath.Substring(0, $separator)
            $destinationLeaf = $destinationPath.Substring($separator + 1)
            "$remote$destinationParent/.cross-device-conflicts/$destinationLeaf/$backupLeaf"
        }
    } else {
        if ($Direction -eq 'WindowsToMac') {
            $destinationParent = Split-Path -Parent $macResolved
            $destinationLeaf = Split-Path -Leaf $macResolved
            Join-Path $destinationParent ".cross-device-conflicts/$destinationLeaf/$backupLeaf"
        } else {
            $destinationPath = ($windowsResolved -replace '\\','/').TrimEnd('/')
            $separator = $destinationPath.LastIndexOf('/')
            $destinationParent = $destinationPath.Substring(0, $separator)
            $destinationLeaf = $destinationPath.Substring($separator + 1)
            "$remote$(Convert-ToWindowsSftpPath $destinationParent)/.cross-device-conflicts/$destinationLeaf/$backupLeaf"
        }
    }
    $rcloneArgs.Add('--backup-dir'); $rcloneArgs.Add($backupRoot)
}
$rcloneArgs.Add('--checksum')
$rcloneArgs.Add('--create-empty-src-dirs')
$rcloneArgs.Add('--copy-links')
$rcloneArgs.Add('--metadata')
$rcloneArgs.Add('--stats-one-line')
$rcloneArgs.Add('--stats'); $rcloneArgs.Add('10s')
if ($Action -eq 'Plan') { $rcloneArgs.Add('--dry-run') }

$started = Get-Date
$ansiPattern = "$([char]27)\[[0-9;]*m"
$output = @(& $rclone @rcloneArgs 2>&1 | ForEach-Object { ("$_" -replace $ansiPattern, '') })
$exitCode = $LASTEXITCODE
$completed = Get-Date
if (-not $LedgerPath) {
    $ledgerRoot = Join-Path $HOME '.ai-control-center/cross-device/ledgers'
    New-Item -ItemType Directory -Force -Path $ledgerRoot | Out-Null
    $LedgerPath = Join-Path $ledgerRoot 'files.jsonl'
}
$record = [ordered]@{
    timestamp = $completed.ToString('o')
    action = $Action
    direction = $Direction
    initiator = if($IsWindows){'windows'}else{'mac'}
    remote_host = $remoteHost
    transport = 'rclone-sftp-over-verified-ssh'
    windows_path = $windowsResolved
    mac_path = $MacPath
    include = @($Include)
    exclude = @($Exclude)
    files_from = $filesFromResolved
    files_from_count = $filesFromCount
    files_from_sha256 = $filesFromSha256
    min_age_minutes = $MinAgeMinutes
    conflict_mode = $ConflictMode
    backup_dir = $backupRoot
    immutable = ($ConflictMode -eq 'Stop')
    delete = $false
    exit_code = $exitCode
    duration_seconds = [math]::Round(($completed - $started).TotalSeconds, 3)
}
Add-Content -LiteralPath $LedgerPath -Value ($record | ConvertTo-Json -Compress) -Encoding utf8NoBOM
if ($exitCode -ne 0) {
    $safeTail = @($output | Select-Object -Last 20) -join [Environment]::NewLine
    throw "SSH file synchronization failed without overwriting conflicts.`n$safeTail"
}
[ordered]@{
    status = if($Action-eq'Plan'){'planned'}else{'synced'}
    direction = $Direction
    initiator = if($IsWindows){'windows'}else{'mac'}
    remote_host = $remoteHost
    conflict_mode = $ConflictMode
    backup_dir = $backupRoot
    immutable = ($ConflictMode -eq 'Stop')
    delete = $false
    files_from_count = $filesFromCount
    files_from_sha256 = $filesFromSha256
    output_tail = @($output | Select-Object -Last 20)
    ledger = $LedgerPath
} | ConvertTo-Json -Depth 4 -Compress
