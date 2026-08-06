#!/bin/zsh
set -euo pipefail
aicc_root="${AICC_ROOT:-$HOME/dev/projects/tools/ai-control-center}"
exec pwsh -NoProfile -File "$aicc_root/tools/platform/sync/cross-device-sync-gui/Open-CrossDeviceSyncGui.ps1" -ScanNow
