$python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $python -and $IsWindows) { $python = Get-Command python.exe -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Error "Python 3를 찾지 못했습니다. PATH를 확인하세요."
    exit 127
}

& $python.Source (Join-Path $PSScriptRoot 'codex_multi.py') @args
exit $LASTEXITCODE
