---
name: screenshots-source
description: Find requested screenshots only in the current user's Pictures directory, regardless of the current directory. Use when the user asks for recent screenshots or chart screenshots without supplying another path; ignore photo libraries and project-local images unless explicitly requested.
---

# Screenshots Source

When the user asks for recent screenshots or chart screenshots without giving a different path, use:

`~/Pictures`

Default workflow:

1. List files from that directory only.
2. Include image files: `*.png`, `*.jpg`, `*.jpeg`, `*.webp`.
3. Sort by `LastWriteTime` descending.
4. If the user says "최근 스크린샷 2개", select the newest two files.
5. Use absolute paths when opening, analyzing, copying, or rendering images.

PowerShell listing:

```powershell
Get-ChildItem -LiteralPath (Join-Path $HOME 'Pictures') -File |
  Where-Object Extension -In '.png','.jpg','.jpeg','.webp' |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 2 FullName,Length,LastWriteTime
```

Do not search inside the current repository for screenshots unless the user explicitly asks for project-local screenshots.
