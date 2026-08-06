# sessions.ps1 — Claude/Codex 세션 enumeration 라이브러리
#
# Public functions:
#   Get-ClaudeSession  [-Top N]
#   Get-CodexSession   [-Top N]
#   Get-AgentSession   [-Source claude|codex|all] [-Top N]
#
# Returned object schema:
#   Source     : 'claude' | 'codex'
#   Id         : session UUID
#   Cwd        : absolute cwd path
#   Mtime      : [datetime] last activity
#   Preview    : short string (last user/agent text or thread name)
#   File       : jsonl absolute path
#   ThreadName : optional Codex thread label

# Capture this library's directory at load (dot-source) time. $PSScriptRoot is
# only valid while a script file executes, so functions called later from an
# interactive prompt cannot rely on it — we snapshot it here instead.
if ($PSScriptRoot) { $script:SessionsLibDir = $PSScriptRoot }
elseif ($PSCommandPath) { $script:SessionsLibDir = Split-Path -Parent $PSCommandPath }
else { $script:SessionsLibDir = (Get-Location).Path }
$script:UserHome = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)

function script:_ReadJsonLine([string]$Path, [int]$N) {
    # Read N-th line (1-indexed) safely
    try {
        return Get-Content -LiteralPath $Path -TotalCount $N -ErrorAction Stop | Select-Object -Last 1
    } catch { return $null }
}

function script:_TailJsonLine([string]$Path) {
    try {
        return Get-Content -LiteralPath $Path -Tail 1 -ErrorAction Stop
    } catch { return $null }
}

# Fast tail: seek to the end of the file and read at most $MaxBytes, then split
# into lines. Avoids Get-Content -Tail which is very slow on jsonl with huge
# single lines (image/tool payloads). Drops the first (possibly partial) line.
function script:_TailChunkLines([string]$Path, [int]$MaxBytes = 131072) {
    try {
        $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $start = [Math]::Max(0, $fs.Length - $MaxBytes)
            [void]$fs.Seek($start, [System.IO.SeekOrigin]::Begin)
            $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
            $text = $sr.ReadToEnd()
            $sr.Dispose()
        } finally { $fs.Dispose() }
        $lines = $text -split "`n"
        if ($start -gt 0 -and $lines.Count -gt 1) { $lines = $lines[1..($lines.Count - 1)] }
        return $lines
    } catch { return @() }
}

function script:_TruncateOneLine([string]$Text, [int]$Max = 80) {
    if (-not $Text) { return '' }
    $t = ($Text -replace '\s+', ' ').Trim()
    if ($t.Length -gt $Max) { return $t.Substring(0, $Max - 1) + '…' }
    return $t
}

function Get-ClaudeSession {
    [CmdletBinding()]
    param([int]$Top = 6)

    $root = Join-Path $script:UserHome '.claude/projects'
    if (-not (Test-Path -LiteralPath $root)) { return @() }

    # Only read content from the most-recent candidate files (file mtime proxy)
    $candidates = foreach ($folder in Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue) {
        Get-ChildItem -LiteralPath $folder.FullName -Filter '*.jsonl' -File -ErrorAction SilentlyContinue
    }
    $candidates = @($candidates | Sort-Object -Property LastWriteTime -Descending | Select-Object -First ([Math]::Max($Top * 4, 20)))

    $all = foreach ($file in $candidates) {
        if ($true) {
            # Cwd: find first line that has 'cwd' field (skip last-prompt/permission-mode meta lines)
            $cwd = $null
            try {
                $headLines = Get-Content -LiteralPath $file.FullName -TotalCount 12 -ErrorAction Stop
                foreach ($line in $headLines) {
                    if ($line -match '"cwd"\s*:\s*"([^"]+)"') {
                        $cwd = $matches[1] -replace '\\\\','\'
                        break
                    }
                }
            } catch { }
            if (-not $cwd) {
                # fallback: try folder-name decode (lossy for dash-containing paths)
                $cwd = $file.Directory.Name
            }

            # Mtime: tail line timestamp or file mtime
            $mt = $file.LastWriteTime
            $tail = script:_TailJsonLine $file.FullName
            if ($tail) {
                try {
                    $tobj = $tail | ConvertFrom-Json -ErrorAction Stop
                    if ($tobj.timestamp) { $mt = [datetime]$tobj.timestamp }
                } catch {}
            }

            # Preview: find last user record (not attachment)
            $preview = ''
            try {
                $tailLines = script:_TailChunkLines $file.FullName
                # keep only the last ~60 lines to bound JSON parsing
                if ($tailLines.Count -gt 60) { $tailLines = $tailLines[($tailLines.Count - 60)..($tailLines.Count - 1)] }
                # Iterate from end
                for ($i = $tailLines.Count - 1; $i -ge 0; $i--) {
                    $line = $tailLines[$i]
                    if ($line -notmatch '"type":"user"') { continue }
                    if ($line -match '"type":"attachment"') { continue }
                    try {
                        $o = $line | ConvertFrom-Json -ErrorAction Stop
                        if ($o.type -ne 'user' -or $o.attachment) { continue }
                        $msg = $o.message
                        if ($msg) {
                            $c = $msg.content
                            if ($c -is [array]) {
                                $textparts = @()
                                foreach ($p in $c) {
                                    if ($p.type -eq 'text' -and $p.text) { $textparts += $p.text }
                                }
                                if ($textparts) { $preview = ($textparts -join ' '); break }
                            } elseif ($c -is [string]) {
                                $preview = $c; break
                            }
                        }
                    } catch {}
                }
            } catch {}
            $preview = script:_TruncateOneLine $preview 80

            [pscustomobject]@{
                Source     = 'claude'
                Id         = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
                Cwd        = $cwd
                Mtime      = $mt
                Preview    = $preview
                File       = $file.FullName
                ThreadName = $null
            }
        }
    }
    $all | Sort-Object -Property Mtime -Descending | Select-Object -First $Top
}

function Get-CodexSession {
    [CmdletBinding()]
    param([int]$Top = 6)

    $sessionsRoot = Join-Path $script:UserHome '.codex/sessions'
    if (-not (Test-Path -LiteralPath $sessionsRoot)) { return @() }

    # Load session_index for thread names
    $indexMap = @{}
    $indexPath = Join-Path $script:UserHome '.codex/session_index.jsonl'
    if (Test-Path -LiteralPath $indexPath) {
        try {
            Get-Content -LiteralPath $indexPath -ErrorAction Stop | ForEach-Object {
                try {
                    $o = $_ | ConvertFrom-Json -ErrorAction Stop
                    if ($o.id) {
                        $indexMap[$o.id] = @{
                            ThreadName = $o.thread_name
                            UpdatedAt  = if ($o.updated_at) { [datetime]$o.updated_at } else { $null }
                        }
                    }
                } catch {}
            }
        } catch {}
    }

    # Enumerate rollout-*.jsonl files (cap to most-recent candidates by mtime)
    $files = Get-ChildItem -LiteralPath $sessionsRoot -Filter 'rollout-*.jsonl' -File -Recurse -ErrorAction SilentlyContinue
    $files = @($files | Sort-Object -Property LastWriteTime -Descending | Select-Object -First ([Math]::Max($Top * 4, 20)))
    $all = foreach ($file in $files) {
        # Extract UUID from filename: rollout-YYYY-MM-DDTHH-mm-ss-<UUID>.jsonl
        $base = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
        $uuid = $null
        if ($base -match '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$') {
            $uuid = $matches[1]
        }
        if (-not $uuid) { continue }

        # Cwd from session_meta first line
        $cwd = $null
        $head = script:_ReadJsonLine $file.FullName 1
        if ($head) {
            try {
                $obj = $head | ConvertFrom-Json -ErrorAction Stop
                if ($obj.payload.cwd) { $cwd = $obj.payload.cwd }
            } catch {}
        }
        if (-not $cwd) { continue }

        # Mtime: index update_at > tail timestamp > file mtime
        $mt = $file.LastWriteTime
        if ($indexMap.ContainsKey($uuid) -and $indexMap[$uuid].UpdatedAt) {
            $mt = $indexMap[$uuid].UpdatedAt
        } else {
            $tail = script:_TailJsonLine $file.FullName
            if ($tail) {
                try {
                    $tobj = $tail | ConvertFrom-Json -ErrorAction Stop
                    if ($tobj.timestamp) { $mt = [datetime]$tobj.timestamp }
                } catch {}
            }
        }

        # Preview: index thread_name first, else last_agent_message
        $preview = ''
        if ($indexMap.ContainsKey($uuid) -and $indexMap[$uuid].ThreadName) {
            $preview = $indexMap[$uuid].ThreadName
        } else {
            $tail = script:_TailJsonLine $file.FullName
            if ($tail) {
                try {
                    $tobj = $tail | ConvertFrom-Json -ErrorAction Stop
                    if ($tobj.payload.last_agent_message) { $preview = $tobj.payload.last_agent_message }
                } catch {}
            }
        }
        $preview = script:_TruncateOneLine $preview 80

        [pscustomobject]@{
            Source     = 'codex'
            Id         = $uuid
            Cwd        = $cwd
            Mtime      = $mt
            Preview    = $preview
            File       = $file.FullName
            ThreadName = if ($indexMap.ContainsKey($uuid)) { $indexMap[$uuid].ThreadName } else { $null }
        }
    }
    $all | Sort-Object -Property Mtime -Descending | Select-Object -First $Top
}

function Get-AllSessionsUnified {
    [CmdletBinding()]
    param([int]$Top = 20)

    $sessions = @()
    $per = [Math]::Max(15, $Top)
    $sessions += @(Get-ClaudeSession -Top $per)
    $sessions += @(Get-CodexSession  -Top $per)
    $sessions | Sort-Object -Property Mtime -Descending | Select-Object -First $Top
}

function Get-AgentSession {
    [CmdletBinding()]
    param(
        [ValidateSet('claude','codex','all')][string]$Source = 'all',
        [int]$Top = 6
    )
    switch ($Source) {
        'claude' { Get-ClaudeSession -Top $Top }
        'codex'  { Get-CodexSession  -Top $Top }
        default  {
            Get-AllSessionsUnified -Top $Top
        }
    }
}
