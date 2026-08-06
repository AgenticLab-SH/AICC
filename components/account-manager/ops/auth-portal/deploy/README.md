# CM auth portal deployment

The public hostname is protected by Cloudflare Tunnel and Access. The broker
must remain loopback-only. Runtime secrets belong in `/etc/cm-auth-broker.env`
with mode `0600`; never add them to this repository.

The human portal verifies a configured Firebase ID token server-side and
requires a verified email in the server allowlist. Configure a separate random
`CM_AUTH_SESSION_SECRET`, an exact `CM_AUTH_PUBLIC_ORIGIN`, and all Firebase web
client fields shown in `../broker.env.example`. The Firebase web API key is
public client configuration; Firebase/Google session cookies and ID tokens are
never copied from another service.

`CM_AUTH_ALLOWED_EMAIL` is the portal administrator's Google identity. It is
independent from `CM_AUTH_EXPECTED_ACCOUNT_ID_SHA256`, which pins the Codex
OAuth account allowed into `latest.json`. An administrator change must update
only the allowlisted Google email; do not rotate the expected Codex hash,
machine bearer, retained OAuth, local cm target, or OCX slot as a side effect.

The Mac fetcher template is
`com.codex-account-manager.auth-sync.plist`. It is installed as a LaunchAgent
and reads its machine token from the macOS Keychain service named by
`CM_AUTH_KEYCHAIN_SERVICE`. Existing machines may temporarily retain the
historical `com.agenthub.cm-auth-sync` label during migration; changing a
loaded label requires an unload/load cycle and can trigger `RunAtLoad`, so do
that only during an intentional auth-sync maintenance window.
Replace `__CM_LAUNCHER__`, `__NODE_BIN__`, `__PYTHON_BIN__`, and `__HOME__` with
verified absolute paths. The explicit Node and Python bin directories are
required because LaunchAgents do not inherit the interactive shell's `PATH`;
without them an npm-installed `cm` launcher either exits with status 127 or
falls back to an unsupported system Python before synchronization starts.

The broker keeps exactly one `latest.json` credential envelope in its private
`CM_AUTH_STATE_DIR` (directory mode `0700`, file mode `0600`). A successful Mac
acknowledgement records `last-ack.json`; it does not delete the latest OAuth.
This lets the owner replace the retained login later and lets a rebuilt Mac
recover the most recent approved credential. The Mac records the applied job id
in `~/.ai-control-center/account-manager/auth-portal-sync.json`, so the
LaunchAgent does not repeatedly stop OCX for the same login.

The same portal page exposes **나중에 Mac으로 가져오기** after a successful
login. The authenticated, CSRF-protected action writes a mode-`0600`
`deferred.json` marker containing only the retained job id and request time.
It is idempotent and does not copy or rewrite the OAuth envelope. The existing
Mac pending endpoint remains compatible and the latest login is still retained
while the Mac is powered off. The LaunchAgent fetches it at the next macOS
login and subsequently at 900-second intervals; booting without a user login
does not run a LaunchAgent.

When `CM_AUTH_SYNC_OPENCODEX=1`, `cm auth-sync` runs the guarded OCX importer.
It checks the server checkpoint before touching OCX, stops only the OCX service,
starts a one-shot process with `OPENCODEX_ENABLE_UNVERIFIED_CODEX_IMPORT=1`, and
creates or replaces the explicit `CM_AUTH_OCX_TARGET_ACCOUNT`. Replacement
requires the existing slot's full email and ChatGPT account id to match the
incoming OAuth. The importer retains bounded private snapshots under
`~/.opencodex/cm-auth-backups`, preserves the previous active slot, alias,
plan, and paused state, verifies the refreshed account, then restores the normal
gate-free service. A failed update is rolled back through the native API and,
after the one-shot process stops, from the pre-import file snapshot if needed.
The import gate must never be persisted in a service definition.

For an existing pool entry, set `CM_AUTH_OCX_TARGET_ACCOUNT` to its exact stable
id from `ocx account list openai --json`. Do not create a new label for the same
owner: that would add a duplicate instead of refreshing the intended slot.
See `../../../docs/auth-portal-ocx-sync.md` for the full state machine and
recovery procedure.

Tunnel ingress must map the configured public hostname to
`http://127.0.0.1:8110`. An access proxy may protect the human portal, but
`/api/mac/*` must bypass Access and rely on the broker bearer; `/health` may
also bypass. Add the exact public hostname to the configured Firebase project's
authorized domains. Reuse only public Firebase web config and the server-side
allowlist, never another session or credential.

The portal uses Firebase redirect authentication so it also works in browsers
that block or cannot host popups. After the redirect, the Firebase ID token is
exchanged with the broker, which re-verifies the exact allowed email
server-side before creating a short-lived portal session.
The response CSP permits frames only from that exact configured Firebase auth
hostname; omitting this `frame-src` prevents Firebase redirect initialization.

The deployment script selects the pinned Codex package for either `aarch64` or
`x86_64` and verifies its SHA-256 before installation. The optional
`cm-auth-cloudflared.service` runs a pre-created named tunnel from
`/etc/cloudflared/config.yml`; keep the tunnel credential JSON mode `0600` and
the containing directory mode `0700`. Its ingress must contain the one exact
portal hostname followed by a terminal `http_status:404` rule. Do not expose
port 8110 in the host firewall.
