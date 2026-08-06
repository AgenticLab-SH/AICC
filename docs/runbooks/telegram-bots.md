# Telegram bot management

Use this runbook to inventory, provision, reconcile, smoke-test, or retire
Telegram bots managed from AICC. The machine-readable source of truth is
`~/.ai-control-center/telegram/bots.toml`. Never put token values, chat IDs,
pairing codes, cookies, or BotFather message text in the registry, this runbook,
commits, or reports.

## Boundaries

- Use only the guarded Whale CDP path. The manager verifies the BotFather identity and the CDP endpoint; it must not launch or fall back to Chrome.
- Treat BotFather creation, deletion, transfer, and credential rotation as account mutations. Obtain the user's current authorization before those operations.
- Do not infer a bot's purpose from its username. Use `audit_pending` until both current BotFather inventory and local references support a role decision.
- Keep credentials in the existing private file for the owning service. Record only a relative file path and environment-key names in the registry.
- Credential files belong under `~/.ai-control-center/telegram/` or an explicitly
  registered service-owned private path. They are private state, not source
  artifacts.
- Existing service-local credential paths can be verified compatibility hardlinks to a central file. Never replace a hardlink with a copied token file.

## Credential layout

Before a credential change, identify the owning central file and obtain explicit authorization. Do not copy credentials to compatibility paths or guess an unregistered remote-service layout.

## Inventory and reconcile

1. List the current owned-bot inventory. This reads verified BotFather and returns usernames only.

   ```powershell
   pwsh -NoProfile -File tools/platform/telegram/Invoke-TelegramBotManager.ps1 -Action List
   ```

2. Compare that output with `~/.ai-control-center/telegram/bots.toml`. Add a
   missing owned bot as `audit_pending`; do not invent a role or credential
   location.
3. Search active source, configuration, scheduled-task definitions, service documentation, and skill instructions for each candidate username and credential-key name. Exclude `private/`, browser profiles, runtime caches, logs, backups, and `_trash` from content collection; inspect secret files only when essential and never output values.
4. Record one of: `active`, `remote_active`, `dormant_preserved`, `retirement_candidate`, `audit_pending`, or `deleted`. Preserve deleted bots as historical records with `deleted_at` and post-delete inventory verification; do not erase them from the registry.
5. Keep the BotFather list result and the local-reference result as temporary validation artifacts or a change record; do not preserve raw Telegram conversations.

## Provision a bot

1. Add the intended role, service root, relative credential-file path, and key names to the registry before creation. Do not create the credential file manually.
2. Choose several available usernames ending in `bot`, then create only after explicit authorization.

   ```powershell
   pwsh -NoProfile -File tools/platform/telegram/Invoke-TelegramBotManager.ps1 `
     -Action Create -DisplayName '<display name>' `
     -UsernameCandidate '<candidate-one>', '<candidate-two>' `
     -CredentialFile 'C:\absolute\private\credential-file.env'
   ```

   The tool writes the token directly to the specified credential file and emits only a fingerprint. Never copy that fingerprint into the registry.
3. Configure and verify only bots with a live owning service. The former AI Control bot has no local service and remains dormant until explicitly retired through BotFather.
4. Restart or reload only the owning service, create a fresh pairing if required, then run the guarded smoke tool with the bot ID obtained from non-secret service status:

   ```powershell
   pwsh -NoProfile -File tools/platform/telegram/Invoke-TelegramBotSmoke.ps1 -BotId <non-secret-bot-id>
   ```

5. Confirm the manager and `Invoke-TelegramBotSmoke.ps1` output report `ok=true`, `chrome_side_effect=false`, and an owned tab closed. Update the registry state only after this evidence exists.

## Retire or delete a bot

Do not delete solely because no source-code string was found. A bot may serve a hosted service or a manual notification route.

1. Create an evidence bundle for the candidate: current BotFather inventory, local reference search, current registry entry, and an explicit role decision. Mark uncertain cases `audit_pending`.
2. For a replacement, verify that the replacement bot is configured, paired where applicable, and smoke-tested before retirement.
3. Obtain explicit current authorization to delete the named bot. `retirement_candidate` is not authorization.
4. Delete through the guarded manager only:

   ```powershell
   pwsh -NoProfile -File tools/platform/telegram/Invoke-TelegramBotManager.ps1 `
     -Action Delete -BotUsername '@exact_bot_username'
   ```

5. Re-run `Invoke-TelegramBotManager.ps1 -Action List`, verify the exact username is absent, retain the deleted registry record with timestamps, remove credential references only under separate credential-mutation authorization, and update a change record with non-secret evidence.

## Username changes

Audit the live menu before assuming that BotFather supports a username change:

```powershell
pwsh -NoProfile -File tools/platform/telegram/Invoke-BotFatherMenuAudit.ps1 -BotUsername '@current_bot_username'
```

If `username_edit_available=false`, do not guess or use unrecognized BotFather commands. Choose explicitly between retaining the bot, creating/re-pairing a replacement, or contacting Telegram Bot Support.
