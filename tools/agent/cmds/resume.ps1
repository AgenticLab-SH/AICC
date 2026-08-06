# cmds/resume.ps1 — `agent resume` 통합 세션 picker
#
# Claude와 Codex의 최근 세션을 하나의 목록으로 보여주고,
# 번호로 고르면 그 세션의 작업 폴더로 cd 한 뒤 해당 에이전트의 이어가기
# 명령을 실행한다.
#
#   claude  →  claude --resume <id>
#   codex   →  codex resume <id>
#
# 흐름: 최근 세션 수집 → 단일 목록 → 선택 → 해당 cwd 에서 네이티브 resume.

param(
    [Parameter(Position = 0)][int]$Top = 12,
    [switch]$NoClear,
    [switch]$Compact,
    [switch]$Wide
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $root 'lib\sessions.ps1')
$script:UserHome = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)

function script:_ShortCwd([string]$cwd) {
    if (-not $cwd) { return '?' }
    $shrunk = $cwd -replace [Regex]::Escape($script:UserHome), '~'
    if ($shrunk.Length -le 34) { return $shrunk }
    return $shrunk.Substring(0, 12) + '…' + $shrunk.Substring($shrunk.Length - 21)
}

function script:_AgoShort([datetime]$ts) {
    $d = (Get-Date) - $ts
    if ($d.TotalMinutes -lt 1)  { return 'now' }
    if ($d.TotalMinutes -lt 60) { return ('{0}m' -f [int]$d.TotalMinutes) }
    if ($d.TotalHours   -lt 24) { return ('{0}h' -f [int]$d.TotalHours) }
    return ('{0}d' -f [int]$d.TotalDays)
}

function script:_FolderName([string]$cwd) {
    if (-not $cwd) { return '?' }
    $leaf = Split-Path -Leaf ($cwd.TrimEnd('\', '/'))
    if (-not $leaf) { return $cwd }
    return $leaf
}

function script:_Fit([string]$text, [int]$max) {
    if ($max -lt 1) { return '' }
    $t = ([string]$text)
    if ($t.Length -le $max) { return $t }
    if ($max -le 1) { return $t.Substring(0, $max) }
    return $t.Substring(0, $max - 1) + '…'
}

function script:_SourceTag([string]$source) {
    switch ($source) {
        'claude' { return @{ Label = 'claude'; Color = 'Magenta' } }
        'codex'  { return @{ Label = 'codex '; Color = 'Green' } }
        default  { return @{ Label = ($source + '      ').Substring(0, 6); Color = 'Gray' } }
    }
}

# 1) Gather
$all = @(Get-AllSessionsUnified -Top $Top)
if (-not $all -or $all.Count -eq 0) {
    Write-Host "최근 세션이 없어요." -ForegroundColor Yellow
    exit
}

# 2) Render single unified list (phone width-aware)
if (-not $NoClear) { try { Clear-Host } catch {} }

$cols = 0
try { $cols = [Console]::WindowWidth } catch {}
if ($cols -le 0) { $cols = if ($env:COLUMNS) { [int]$env:COLUMNS } else { 80 } }
$useCompact = $Compact -or (-not $Wide -and $cols -lt 64)

Write-Host ""
Write-Host "  agent resume " -NoNewline -ForegroundColor Cyan
Write-Host "— 최근 세션 (최신순)"
Write-Host ""

for ($i = 0; $i -lt $all.Count; $i++) {
    $s = $all[$i]
    $key = $i + 1
    $tag = script:_SourceTag $s.Source
    $mark = ' '
    $ago = script:_AgoShort $s.Mtime

    if ($useCompact) {
        # 2-line entry: header line + indented preview. Never wraps.
        # line1:  [ 1]⚠ codex  18h  folderName
        Write-Host ("[{0,2}]" -f $key) -NoNewline -ForegroundColor Gray
        Write-Host $mark -NoNewline -ForegroundColor DarkYellow
        Write-Host ' ' -NoNewline
        Write-Host $tag.Label.Trim() -NoNewline -ForegroundColor $tag.Color
        $head1 = "  $ago  "
        $folderBudget = $cols - 4 - 1 - 1 - $tag.Label.Trim().Length - $head1.Length - 1
        Write-Host ($head1 + (script:_Fit (script:_FolderName $s.Cwd) ([Math]::Max(6, $folderBudget))))
        if ($s.Preview) {
            Write-Host ("     " + (script:_Fit $s.Preview ($cols - 6))) -ForegroundColor DarkGray
        }
    }
    else {
        # 1-line entry, truncated to terminal width (no wrap)
        Write-Host ("  [{0,2}] " -f $key) -NoNewline
        Write-Host $mark -NoNewline -ForegroundColor DarkYellow
        Write-Host ' ' -NoNewline
        Write-Host $tag.Label -NoNewline -ForegroundColor $tag.Color
        # head visible width: 2+4+1 +1+1 +6 = 15, plus the "{ago,4} " below
        $agoCol = ('{0,4} ' -f $ago)
        $headLen = 15 + $agoCol.Length
        $tailBudget = $cols - $headLen - 1
        $cwdMax = [Math]::Min(34, [int]($tailBudget * 0.5))
        $cwdS = script:_Fit (script:_ShortCwd $s.Cwd) ([Math]::Max(8, $cwdMax))
        $prevMax = $tailBudget - $cwdS.Length - 2
        $prevS = if ($prevMax -gt 0) { script:_Fit $s.Preview $prevMax } else { '' }
        Write-Host ("  {0}{1,-$($cwdMax)}  {2}" -f $agoCol, $cwdS, $prevS)
    }
}
Write-Host ""

Write-Host ("  선택 [1-{0}  /  q=취소]: " -f $all.Count) -NoNewline -ForegroundColor Yellow
$choice = Read-Host

if (-not $choice -or $choice -ieq 'q') {
    Write-Host "취소" -ForegroundColor DarkGray
    exit
}

# 4) Resolve
$chosen = $null
if ($choice -match '^\d+$') {
    $n = [int]$choice
    if ($n -ge 1 -and $n -le $all.Count) { $chosen = $all[$n - 1] }
}
if (-not $chosen) {
    Write-Host "잘못된 선택: '$choice'" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "선택: " -NoNewline
Write-Host "$($chosen.Source) " -ForegroundColor Cyan -NoNewline
Write-Host "@ $($chosen.Cwd)"
Write-Host ""

# 3) Launch
if (-not (Test-Path -LiteralPath $chosen.Cwd)) {
    Write-Host "cwd 경로가 존재하지 않아요: $($chosen.Cwd)" -ForegroundColor Red
    exit 1
}
Set-Location -LiteralPath $chosen.Cwd

Write-Host "cd $($chosen.Cwd)" -ForegroundColor DarkGray
switch ($chosen.Source) {
    'claude' {
        Write-Host "claude --resume $($chosen.Id)" -ForegroundColor DarkGray
        & claude --resume $chosen.Id
    }
    'codex' {
        Write-Host "codex resume $($chosen.Id)" -ForegroundColor DarkGray
        & codex resume $chosen.Id
    }
    default {
        Write-Host "알 수 없는 에이전트: $($chosen.Source)" -ForegroundColor Red
        exit 1
    }
}
