# AICC deployable skills

This directory is the canonical source for AICC-managed Codex and Claude
skills. Generated copies in agent homes are deployment targets, not edit
targets.

Default deploy: `pwsh -NoProfile -File tools/platform/core/deploy_active_skills.ps1 -AiccRoot . -PruneManaged`

Keep `SKILL.md` focused on trigger, intake, execution, and verification. Move large operational detail to referenced files only when it is actually needed.
Do not add router skills for capabilities already supplied by the host's native
tools or an installed plugin.
