# Oracle safe-ops verification matrix

| Action | Before | Mutation | Required success evidence | Stop condition |
|---|---|---|---|---|
| Audit | key exists; SSH host key policy intact | none | SSH exit 0; RAM/disk summary; named units and timers reported | authentication or host-key failure |
| Deploy | local tests pass; audit clean; bundle has `deploy.sh` | upload archive; run deploy script | deploy exit 0; every named service active; protected timers active; health 2xx | disk/RAM shortage, missing bundle script, unit or health failure after optional rollback |
| RebootVerify | record named unit/timer states | one `systemctl reboot` | SSH goes away and returns; same units/timers active; health 2xx | SSH timeout; protected timer differs; repeated reboot would be required |
| RecoverSsh | normal SSH failed; existing OCI CLI/config; lifecycle state checked | optional `SOFTRESET` only | OCI command accepted; SSH returns; full status verification | missing explicit approval, terminated instance, cost/network/firewall change needed |

## Failure classification

- `permission denied` or host-key mismatch: stop; do not weaken SSH verification.
- no listener but instance `RUNNING`: one user-approved soft reset can be considered.
- health failure with service active: inspect only the named unit's bounded status/journal and application health response.
- out-of-memory or disk pressure: stop deployment and reduce the artifact/process footprint locally.
- OCI capacity or rate-limit errors from an existing A1 autocreate timer: preserve the timer; those errors are not a reason to modify an unrelated deployed service.

## Evidence record

Record timestamps, action names, exit codes, unit/timer active states, health status, and whether rollback or soft reset ran. Redact targets, instance ids, key paths, tokens, and remote addresses from shareable reports.
