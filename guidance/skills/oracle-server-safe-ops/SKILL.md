---
name: oracle-server-safe-ops
description: Audit, deploy, reboot, or recover the existing Oracle Linux server over SSH while preserving unrelated services.
---

# Oracle server safe operations

Operate only an existing server and existing credentials. Never create a paid OCI resource, change a security list, open a port, rotate a key, or delete unrelated data unless the user separately authorizes that exact action.

## Intake

Collect only the values needed for the selected action:

- SSH target and existing private-key path
- deploy bundle directory and its `deploy.sh` for deployment
- systemd services and timers that must remain healthy
- an already-exposed health URL, if one exists
- OCI instance id/config/profile only when SSH recovery is requested

Do not echo key contents, OCI tokens, config contents, server IPs in reports, or environment dumps. Passing paths and target values as process arguments is allowed locally; redact them from summaries.

## Workflow

1. Run local tests for the application or bundle before touching the server.
2. Run the helper `Validate` and `Audit` actions. Treat RAM, disk, failed units, and protected timers as preconditions.
3. For deployment, upload a tarball and a short script file. Do not build long quoted SSH one-liners. The bundle must contain an idempotent `deploy.sh`; include `rollback.sh` when the change is not trivially reversible.
4. Verify the named units, existing timers, bounded status output, and health endpoint.
5. For reboot work, record the protected unit/timer state first, reboot once, wait for SSH to disappear and return, and repeat the same verification.
6. If SSH does not return, inspect the existing OCI instance state before considering `RecoverSsh`. A soft reset is the only built-in control-plane mutation and requires the explicit helper switch plus user approval.

## Helper

```powershell
$O = Join-Path $HOME '.codex/skills/oracle-server-safe-ops/scripts/Invoke-OracleServerSafeOps.ps1'
pwsh -NoProfile -File $O -Action Validate -SshTarget user@host -IdentityFile C:\path\key
pwsh -NoProfile -File $O -Action Audit -SshTarget user@host -IdentityFile C:\path\key -ServiceName app -TimerName existing-a1.timer
pwsh -NoProfile -File $O -Action Deploy -SshTarget user@host -IdentityFile C:\path\key -BundlePath C:\path\bundle -ServiceName app -HealthUrl http://127.0.0.1:PORT/health
pwsh -NoProfile -File $O -Action RebootVerify -SshTarget user@host -IdentityFile C:\path\key -ServiceName app -TimerName existing-a1.timer -HealthUrl http://127.0.0.1:PORT/health
```

Use `-WhatIf` before `Deploy`, `RebootVerify`, or `RecoverSsh`. Do not use `-Confirm:$false` until the current user request clearly authorizes that mutation.

## Low-memory rules

- Check `free -m`, disk space, and current services first.
- Prefer the existing runtime and project lockfile. Avoid broad `dnf upgrade`, global `pip install`, compilation, Docker builds, or parallel package installation on the server.
- Build/package locally when possible and upload only the bounded artifact.
- Keep log reads bounded to the named unit and a small line count; do not ingest databases, full journals, or unrelated logs.

## Recovery boundaries

- A failed health check after deployment triggers `rollback.sh` only when the bundle supplies it.
- A stale SSH connection alone is not proof the VM is down. Check OCI instance lifecycle state using the existing CLI config.
- `RecoverSsh` may issue only `SOFTRESET`; it must not terminate, recreate, resize, change shape, allocate networking, or edit firewall rules.
- Existing A1 retry/autocreate services and timers are protected inputs. Audit them before and after reboot and never stop or edit them as part of an unrelated deployment.

Read [references/verification-matrix.md](references/verification-matrix.md) when planning a deployment, reboot, or recovery. Use `telegram-notify` only when the user asks for a phone notification or the operation is genuinely long-running.
