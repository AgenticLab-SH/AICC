---
name: repair-browser-launchers
description: Audit or repair a distinct Chrome or Whale launcher's app identity, profile, port, icon, and Dock or taskbar state without changing authentication or browser engines. Use only for launcher installation or identity faults. Not for choosing a browser session, controlling pages, browser QA, or Web GPT jobs.
---

# Repair browser launchers

Treat a launcher identity as the tuple `role + engine + app identity + profile +
port + icon`. Read [references/identity-contract.md](references/identity-contract.md)
before changing a launcher or its visible identity.

## Inspect before changing

Resolve current paths and ports from installed app metadata and
`~/.ai-control-center/guidance/coordination.toml`. Verify:

- app bundle or executable and OS identity;
- main browser process and complete launch arguments;
- user-data root and profile directory;
- CDP listener owner;
- Dock or taskbar target, label, and icon.

Registered authenticated slots are defined only by
`~/.ai-control-center/guidance/coordination.toml`. Resolve each slot's account
alias, profile root and port there; never copy personal aliases into this public
skill. The portable defaults use two separate CDP Chrome profiles and one CDP
Whale session, but the private coordination file is authoritative.

The OS-level default browser on this Mac is fixed to `CDP Whale 9335`
(`com.aicc.whale.cdp.9335`). Preserve that HTTP/HTTPS handler and the matching
`default_browser_bundle_id` in the coordination SSOT. Repairing normal Chrome
does not authorize changing the default browser.

Do not swap registered account aliases, ports, or roots to make a failing task
appear healthy.

Stop if these disagree. Do not attach to another browser, port, or profile as a
fallback.

## Preserve the security boundary

- Keep normal and automation profiles in different user-data roots.
- Keep simultaneous CDP slots on different ports.
- Start the unchanged vendor browser through a lightweight launcher; do not
  clone or re-sign a profile-bearing browser engine.
- Never read, copy, reset, or delete cookies, passwords, tokens, profile
  databases, or unrelated extensions.
- Keep Windows-imported profiles as preservation material on macOS.

Use the bundled icon generator only for a verified launcher asset. Do not modify
the vendor browser icon in place.

When multiple Google Chrome automation instances are running, a Dock tile that points directly
to `com.google.Chrome` can activate the last CDP instance. On this Mac, the normal Dock tile must
point to `~/Applications/Google Chrome (일반).app` (`com.aicc.chrome.normal`). That lightweight
controller starts the unchanged vendor-signed engine with the ordinary Chrome user-data root and
never carries a remote-debugging port. It is a Dock-only controller and must not register or replace
HTTP/HTTPS handlers. The vendor app remains installed as the engine.

The shared, permission-minimal badge source is
`tools/platform/web-automation/extensions/aicc-cdp-port-badge`. A launcher may
reference this AICC path, but must keep its profile and account data outside the
repository.

## Verify

Launch each changed entry and verify the OS identity, process path, profile
arguments, port owner, visible label, icon, and running indicator. Use Computer
Use for the final visual check when available, but do not accept UI appearance
without matching process and listener evidence.

For AICC-managed changes, create a recovery snapshot, edit the canonical AICC
source, run the matching browser identity checks, deploy only the affected
homes, and record the change.

Before replacing a registered launcher, unregister its exact live path with
LaunchServices. A recovery copy must not retain a terminal `.app` suffix: use
an exact leaf such as `CDP Chrome 9223.app.backup`, or place retired material
under a dated `.noindex` archive. Otherwise Spotlight and the Codex app picker
can expose the backup as a second installed browser even though only one Chrome
process is running. After cleanup, query both Spotlight and LaunchServices and
require exactly one canonical registration per active AICC bundle identifier.
Do not treat `ChromeRemoteDesktopHost` or its uninstaller as duplicate Chrome
profiles; they are separate installed applications.

After launcher replacement, inspect LaunchServices for duplicate browser bundle registrations.
Rebuild LaunchServices only after active AICC bundles and the normal controller are registered.
Immediately verify that both HTTP and HTTPS still resolve to `com.aicc.whale.cdp.9335`; stop and
restore that exact handler if they do not.
Do not delete current Chrome/Whale profiles, imported-Windows preservation material, cookies,
password stores, or browser databases. Generated `runtime/browser-smoke` directories, empty
Chrome-for-Testing roots, and unreferenced retired launchers may be moved to a dated `.noindex`
archive or Trash after exact-path and live-process checks.
