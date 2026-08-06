#requires -Version 7.0
<#
.SYNOPSIS
  Build the Windows .ico variants of the CDP slot launcher icons from their
  tracked PNG sources.
.DESCRIPTION
  The repository ships both the 1024px PNG masters (used by the macOS launcher
  bundles) and multi-size .ico files (used by the Windows launchers), so a fresh
  checkout never has to recreate launcher artwork by hand.

  Run this only when a PNG master changes. It writes a multi-resolution .ico
  containing 16/32/48/64/128/256 px frames with PNG-compressed payloads, which
  matches the existing cdp_whale.ico layout.
#>
[CmdletBinding()]
param(
    [string]$IconRoot = $PSScriptRoot,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not $IsMacOS) {
    throw 'Icon rendering uses the macOS sips utility. Run this on the Mac host and commit the generated .ico files.'
}

$sources = @(
    [ordered]@{ png = 'cdp_chrome_9222.png'; ico = 'cdp_chrome_9222.ico' },
    [ordered]@{ png = 'cdp_chrome_9223.png'; ico = 'cdp_chrome_9223.ico' }
)
$sizes = @(16, 32, 48, 64, 128, 256)

function New-IcoFromPng {
    param([string]$Source, [string]$Destination)

    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Icon PNG source is missing: $Source"
    }

    $stage = Join-Path ([IO.Path]::GetTempPath()) ("cdp-slot-ico-{0}" -f [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        $frames = foreach ($size in $sizes) {
            $framePath = Join-Path $stage ("frame-{0}.png" -f $size)
            & /usr/bin/sips -s format png -z $size $size $Source --out $framePath *> $null
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $framePath -PathType Leaf)) {
                throw "Failed to render the $size px frame for $Source"
            }
            [ordered]@{ size = $size; bytes = [IO.File]::ReadAllBytes($framePath) }
        }

        $stream = [IO.MemoryStream]::new()
        $writer = [IO.BinaryWriter]::new($stream)
        try {
            # ICONDIR: reserved, type 1 (icon), image count.
            $writer.Write([uint16]0)
            $writer.Write([uint16]1)
            $writer.Write([uint16]$frames.Count)

            # ICONDIRENTRY is 16 bytes each and follows the 6-byte header.
            $offset = 6 + (16 * $frames.Count)
            foreach ($frame in $frames) {
                # 256 px is encoded as 0 in the single-byte width/height fields.
                $dimension = if ($frame.size -ge 256) { 0 } else { $frame.size }
                $writer.Write([byte]$dimension)
                $writer.Write([byte]$dimension)
                $writer.Write([byte]0)   # palette count (0 = no palette)
                $writer.Write([byte]0)   # reserved
                $writer.Write([uint16]1) # color planes
                $writer.Write([uint16]32)# bits per pixel
                $writer.Write([uint32]$frame.bytes.Length)
                $writer.Write([uint32]$offset)
                $offset += $frame.bytes.Length
            }
            foreach ($frame in $frames) {
                $writer.Write($frame.bytes)
            }
            $writer.Flush()
            [IO.File]::WriteAllBytes($Destination, $stream.ToArray())
        } finally {
            $writer.Dispose()
            $stream.Dispose()
        }
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    }
}

$results = foreach ($source in $sources) {
    $pngPath = Join-Path $IconRoot $source.png
    $icoPath = Join-Path $IconRoot $source.ico
    New-IcoFromPng -Source $pngPath -Destination $icoPath
    [ordered]@{
        png = $pngPath
        ico = $icoPath
        sizes = $sizes
        bytes = (Get-Item -LiteralPath $icoPath).Length
    }
}

$report = [ordered]@{
    ok = $true
    icon_root = $IconRoot
    icons = @($results)
}
if ($AsJson) { $report | ConvertTo-Json -Compress -Depth 5 } else { $report | ConvertTo-Json -Depth 5 }
