---
name: choose-browser-session
description: Choose and verify the browser session before UI work that needs a login, account or workspace identity, a persistent automation profile, or shared browser state. Prefer an authenticated in-app browser, use a task-owned registered CDP target when a reusable Chrome profile is required, use isolated Chrome for stateless QA, and use an existing user browser only by explicit request or authoritative exclusive-idle proof. Not for completing login challenges, page QA, Web GPT prompt execution, or launcher repair.
---

# Choose browser session

Choose one verified browser session before UI work that depends on login,
account, workspace, profile, or shared state. Read machine-specific identities
from `~/.ai-control-center/guidance/coordination.toml`; never infer an account,
profile, launcher, or port from an open tab or process alone.

## Selection order

1. Prefer the agent's authenticated in-app browser when its displayed account
   and workspace match the task. Claim only a task-owned or explicitly selected
   tab and keep it in the background unless the user asks to watch.
2. Use a registered CDP Chrome slot when the in-app browser lacks the required
   login or a reusable Chrome profile matters. Acquire a background target with
   `tools/platform/web-automation/Manage-CdpChromeSlotLease.ps1`; let the helper
   choose among matching configured slots.
3. Use isolated QA Chrome for stateless browser verification. Its home and port
   come from the AICC personal configuration and it must not join the
   authenticated slot pool.
4. Use an existing user browser only when the user requests that exact state or
   an authoritative mechanism grants exclusive idle ownership. Minimized state,
   an open port, quiet tabs, or agent inference is not proof of availability.

Prefer a connector, API, or CLI when it can complete the work without browser
UI. Never silently fall back to another browser, account, workspace, profile,
or unregistered port.

## Verify identity

For an in-app session, verify the account and workspace from current UI state.
When visible labels are duplicated, use stable account identifiers and checked
workspace state from the current menu. Stop if the identity is ambiguous.

For CDP Chrome, the private coordination entry must provide the endpoint,
profile directory, launcher, account alias, and workspace. The lease helper
runs `Assert-CdpEndpointIdentity.ps1` and rejects a listener owned by the wrong
browser, profile, or port.

```powershell
pwsh -NoProfile -File tools/platform/web-automation/Manage-CdpChromeSlotLease.ps1 `
  -Action Acquire -AccountAlias <configured-alias> `
  -Workspace <configured-workspace> -Url <url> -AsJson
```

Use the returned `lease_token`, `endpoint`, `port`, `target_id`, and
`control_state_dir` as one unit. Heartbeat during a bounded action interval and
release in cleanup:

```powershell
pwsh -NoProfile -File tools/platform/web-automation/Manage-CdpChromeSlotLease.ps1 -Action Heartbeat -LeaseToken <token> -AsJson
pwsh -NoProfile -File tools/platform/web-automation/Manage-CdpChromeSlotLease.ps1 -Action Release -LeaseToken <token> -AsJson
```

Operate only on the returned target. Do not activate a shared browser window,
select a tab by position, reuse another task's target, inspect cookies, or alter
profiles and extensions. Release closes only the lease-owned target.

## Preserve user download behavior

When continuing the user's existing CDP Whale, do not attach the default
Playwright `connectOverCDP()` behavior to the user's default browser context.
Older Playwright runtimes install `Browser.setDownloadBehavior` with an
artifact-directory path, which redirects subsequent human downloads until the
browser process is restarted or the policy is restored.

- Prefer the raw CDP/browser-client control path for ordinary tab actions.
- If Playwright is required, use Playwright 1.60+ with
  `connectOverCDP(endpoint, { noDefaults: true, isLocal: true,
  artifactsDir: taskArtifactsDir })` and do not create or close the user's
  default context.
- If a legacy runtime must attach, acquire the single-writer browser lease,
  restore browser-level download behavior to `default` in a `finally` block,
  and fail clearly if the restore cannot be confirmed. Never leave
  `allowAndName` or a task temporary path installed on the user context.
- Agent-owned downloads must use a task artifact directory and an explicit
  `saveAs` to the requested final path; they must not repurpose the user's
  normal Downloads directory as an automation sink.

After selection, use `browser-qa` for page evidence, `use-web-gpt` for Web GPT,
`complete-site-login` for login challenges, and `repair-browser-launchers` for
launcher identity. Those workflows must keep the selected identity.

Report the selected surface, verified account/workspace or profile, and whether
a task-owned target was created and released. Never report the lease token.
