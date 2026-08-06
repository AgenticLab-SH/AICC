# Directives

`fragments/common.md` generates the shared home rules. Codex appends its agent
fragment to `AGENTS.md`; Claude keeps shared rules in `AGENTS.md` and imports
them from `CLAUDE.md`, where only Claude-specific rules are appended.
`generated/` is output only; do not edit it directly.

```powershell
pwsh -NoProfile -File tools/platform/core/deploy_directives.ps1 -AiccRoot .
pwsh -NoProfile -File tools/platform/test/Test-AgentHomeDirectives.ps1 -AiccRoot . -SummaryOnly
```

Do not add one-off workflow advice here. Keep only stable rules that should be
present in every conversation. Project-specific private preferences belong in
that project's gitignored `CLAUDE.local.md`, not in the global home directives.
