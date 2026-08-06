[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Validate','Audit','Status','Deploy','RebootVerify','RecoverSsh')]
    [string]$Action,
    [Parameter(Mandatory)][string]$SshTarget,
    [Parameter(Mandatory)][string]$IdentityFile,
    [string]$BundlePath,
    [string]$DeployScript = 'deploy.sh',
    [string]$RollbackScript = 'rollback.sh',
    [string[]]$ServiceName = @(),
    [string[]]$TimerName = @(),
    [string]$HealthUrl,
    [int]$SshTimeoutSec = 15,
    [int]$RebootTimeoutSec = 600,
    [switch]$AllowOciSoftReset,
    [string]$OciInstanceId,
    [string]$OciProfile = 'DEFAULT',
    [string]$OciConfigFile = "$HOME\.oci\config",
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

function Assert-SafeToken([string]$Value, [string]$Name, [string]$Pattern) {
    if (-not $Value -or $Value -notmatch $Pattern) { throw "Unsafe or missing $Name." }
}

function Invoke-Capture([string]$File, [string[]]$Arguments, [int]$TimeoutSec = 120) {
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $File
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    foreach ($arg in $Arguments) { [void]$psi.ArgumentList.Add($arg) }
    $process = [Diagnostics.Process]::new(); $process.StartInfo = $psi
    [void]$process.Start()
    if (-not $process.WaitForExit($TimeoutSec * 1000)) {
        try { $process.Kill($true) } catch {}
        throw "$File timed out after $TimeoutSec seconds."
    }
    [pscustomobject]@{
        exitCode = $process.ExitCode
        stdout = $process.StandardOutput.ReadToEnd().Trim()
        stderr = $process.StandardError.ReadToEnd().Trim()
    }
}

function Get-SshArgs([string[]]$Tail = @()) {
    @('-o','BatchMode=yes','-o',"ConnectTimeout=$SshTimeoutSec",'-i',$IdentityFile) + $Tail
}

function Test-Ssh {
    $result = Invoke-Capture 'ssh' (Get-SshArgs @($SshTarget,'true')) ($SshTimeoutSec + 5)
    return ($result.exitCode -eq 0)
}

function Invoke-RemoteScript([string]$Script, [int]$TimeoutSec = 180) {
    $id = [Guid]::NewGuid().ToString('N')
    $local = Join-Path $env:TEMP "oracle-safe-$id.sh"
    $remote = "/tmp/oracle-safe-$id.sh"
    [IO.File]::WriteAllText($local, ($Script -replace "`r`n","`n"), [Text.UTF8Encoding]::new($false))
    try {
        $copy = Invoke-Capture 'scp' (Get-SshArgs @($local,"${SshTarget}:$remote")) 120
        if ($copy.exitCode -ne 0) { throw "SCP failed: $($copy.stderr)" }
        $run = Invoke-Capture 'ssh' (Get-SshArgs @($SshTarget,'bash',$remote)) $TimeoutSec
        return $run
    } finally {
        Remove-Item -LiteralPath $local -Force -ErrorAction SilentlyContinue
        try { $null = Invoke-Capture 'ssh' (Get-SshArgs @($SshTarget,'rm','-f',$remote)) 20 } catch {}
    }
}

function New-StatusScript([switch]$NoExit) {
    $services = ($ServiceName | ForEach-Object { "systemctl is-active --quiet '$($_)' && echo 'service:$($_):active' || { echo 'service:$($_):inactive'; failed=1; }" }) -join "`n"
    $timers = ($TimerName | ForEach-Object { "systemctl is-active --quiet '$($_)' && echo 'timer:$($_):active' || { echo 'timer:$($_):inactive'; failed=1; }" }) -join "`n"
    $health = if ($HealthUrl) { "curl --fail --silent --show-error --max-time 15 '$HealthUrl' >/dev/null && echo 'health:ok' || { echo 'health:failed'; failed=1; }" } else { "echo 'health:skipped'" }
    $finish = if ($NoExit) { 'status_code=$failed' } else { 'exit $failed' }
    @"
set -u
failed=0
$services
$timers
$health
$finish
"@
}

function Complete-Result($Result) {
    $output = [pscustomobject]$Result
    if ($AsJson) { $output | ConvertTo-Json -Depth 6 } else { $output }
    if (-not $Result.ok) { exit 1 }
    exit 0
}

Assert-SafeToken $SshTarget 'SSH target' '^[A-Za-z0-9._-]+@[A-Za-z0-9.:-]+$'
if (-not (Test-Path -LiteralPath $IdentityFile -PathType Leaf)) { throw 'SSH identity file does not exist.' }
foreach ($unit in @($ServiceName) + @($TimerName)) { Assert-SafeToken $unit 'systemd unit' '^[A-Za-z0-9_.@-]+$' }
Assert-SafeToken $DeployScript 'deploy script name' '^[A-Za-z0-9_./-]+$'
Assert-SafeToken $RollbackScript 'rollback script name' '^[A-Za-z0-9_./-]+$'
if ($DeployScript.StartsWith('/') -or $DeployScript -match '(^|/)[.][.](/|$)') { throw 'Unsafe deploy script path.' }
if ($RollbackScript.StartsWith('/') -or $RollbackScript -match '(^|/)[.][.](/|$)') { throw 'Unsafe rollback script path.' }
if ($HealthUrl -and $HealthUrl -notmatch '^https?://[A-Za-z0-9.:[\]_-]+(?::[0-9]+)?(?:/[A-Za-z0-9._~!$&()*+,;=:@%/-]*)?$') { throw 'Unsafe health URL.' }

$result = [ordered]@{ ok = $false; action = $Action; ssh = $false; mutation = 'none'; evidence = @(); timestamp = (Get-Date).ToString('o') }

if ($Action -eq 'Validate') {
    $result.ssh = Test-Ssh
    $result.ok = $result.ssh
} elseif ($Action -eq 'Audit') {
    $audit = Invoke-RemoteScript @'
set -eu
echo 'kernel:'"$(uname -r)"
free -m | sed -n '1,2p'
df -P / | tail -n 1
failed_count="$(systemctl --failed --no-legend 2>/dev/null | wc -l)"
echo "failed-units:$failed_count"
'@
    $status = Invoke-RemoteScript (New-StatusScript)
    $result.ssh = $true
    $result.evidence = @($audit.stdout, $status.stdout)
    $result.ok = ($audit.exitCode -eq 0 -and $status.exitCode -eq 0)
} elseif ($Action -eq 'Status') {
    $status = Invoke-RemoteScript (New-StatusScript)
    $result.ssh = $true; $result.evidence = @($status.stdout); $result.ok = ($status.exitCode -eq 0)
} elseif ($Action -eq 'Deploy') {
    if (-not $BundlePath -or -not (Test-Path -LiteralPath $BundlePath -PathType Container)) { throw 'Deploy requires a bundle directory.' }
    if (-not (Test-Path -LiteralPath (Join-Path $BundlePath $DeployScript) -PathType Leaf)) { throw 'Bundle deploy script is missing.' }
    if (-not $PSCmdlet.ShouldProcess('existing Oracle server','upload bundle and run deploy script')) { $result.ok = $true; $result.evidence = @('what-if'); Complete-Result $result }
    $id = [Guid]::NewGuid().ToString('N'); $archive = Join-Path $env:TEMP "oracle-deploy-$id.tgz"; $remoteArchive = "/tmp/oracle-deploy-$id.tgz"; $remoteDir = "/tmp/oracle-deploy-$id"
    try {
        $parent = Split-Path -Parent (Resolve-Path -LiteralPath $BundlePath); $leaf = Split-Path -Leaf (Resolve-Path -LiteralPath $BundlePath)
        $tar = Invoke-Capture 'tar' @('-czf',$archive,'-C',$parent,$leaf) 180
        if ($tar.exitCode -ne 0) { throw "Local bundle packaging failed: $($tar.stderr)" }
        $copy = Invoke-Capture 'scp' (Get-SshArgs @($archive,"${SshTarget}:$remoteArchive")) 180
        if ($copy.exitCode -ne 0) { throw "Bundle upload failed: $($copy.stderr)" }
        $script = @"
set -eu
mkdir -p '$remoteDir'
tar -xzf '$remoteArchive' -C '$remoteDir' --strip-components=1
cd '$remoteDir'
set +e
bash '$DeployScript'
code=`$?
if [ `$code -eq 0 ]; then
"@ + (New-StatusScript -NoExit) + @"
  code=`$status_code
fi
if [ `$code -ne 0 ] && [ -f '$RollbackScript' ]; then bash '$RollbackScript'; fi
rm -f '$remoteArchive'
exit `$code
"@
        $deploy = Invoke-RemoteScript $script 900
        $result.ssh = $true; $result.mutation = 'deploy'; $result.evidence = @($deploy.stdout); $result.ok = ($deploy.exitCode -eq 0)
    } finally { Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue }
} elseif ($Action -eq 'RebootVerify') {
    $before = Invoke-RemoteScript (New-StatusScript)
    if ($before.exitCode -ne 0) { throw 'Pre-reboot service/timer/health verification failed.' }
    if (-not $PSCmdlet.ShouldProcess('existing Oracle server','reboot once and verify return')) { $result.ok = $true; $result.evidence = @('what-if'); Complete-Result $result }
    try { $null = Invoke-Capture 'ssh' (Get-SshArgs @($SshTarget,'sudo','systemctl','reboot')) 20 } catch {}
    $deadline = (Get-Date).AddSeconds($RebootTimeoutSec); $returned = $false
    Start-Sleep -Seconds 5
    while ((Get-Date) -lt $deadline) { if (Test-Ssh) { $returned = $true; break }; Start-Sleep -Seconds 10 }
    if (-not $returned) { throw 'SSH did not return before the reboot timeout.' }
    $after = Invoke-RemoteScript (New-StatusScript)
    $result.ssh = $true; $result.mutation = 'reboot'; $result.evidence = @($before.stdout,$after.stdout); $result.ok = ($after.exitCode -eq 0)
} elseif ($Action -eq 'RecoverSsh') {
    if (Test-Ssh) { $result.ssh = $true; $result.ok = $true; $result.evidence = @('ssh-already-healthy'); Complete-Result $result }
    if (-not $AllowOciSoftReset -or -not $OciInstanceId) { throw 'SSH is down; explicit AllowOciSoftReset and an existing instance id are required.' }
    if (-not (Test-Path -LiteralPath $OciConfigFile -PathType Leaf)) { throw 'OCI config file does not exist.' }
    if (-not $PSCmdlet.ShouldProcess('existing OCI instance','issue one SOFTRESET for SSH recovery')) { $result.ok = $true; $result.evidence = @('what-if'); Complete-Result $result }
    $oci = Invoke-Capture 'oci' @('compute','instance','action','--instance-id',$OciInstanceId,'--action','SOFTRESET','--config-file',$OciConfigFile,'--profile',$OciProfile) 120
    if ($oci.exitCode -ne 0) { throw "OCI soft reset failed: $($oci.stderr)" }
    $deadline = (Get-Date).AddSeconds($RebootTimeoutSec); $returned = $false
    while ((Get-Date) -lt $deadline) { if (Test-Ssh) { $returned = $true; break }; Start-Sleep -Seconds 10 }
    if (-not $returned) { throw 'SSH did not return after the approved soft reset.' }
    $status = Invoke-RemoteScript (New-StatusScript)
    $result.ssh = $true; $result.mutation = 'oci-softreset'; $result.evidence = @($status.stdout); $result.ok = ($status.exitCode -eq 0)
}

$output = [pscustomobject]$result
if ($AsJson) { $output | ConvertTo-Json -Depth 6 } else { $output }
if (-not $result.ok) { exit 1 }
