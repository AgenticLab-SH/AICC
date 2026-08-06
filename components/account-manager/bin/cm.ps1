# Codex Account Manager launcher (Windows PowerShell / PowerShell 7).
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$entry = Join-Path $repoRoot "src\codex_multi.py"

# tomllib needs 3.11+; check each candidate instead of trusting the first hit.
$python = $null
foreach ($name in @("python3.14", "python3.13", "python3.12", "python3.11", "python", "python3", "py")) {
    $found = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $found) { continue }
    & $found.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $python = $found.Source; break }
}

if (-not $python) {
    Write-Error "Python 3.11 or newer is required (tomllib)."
    exit 127
}

& $python $entry @args
exit $LASTEXITCODE
