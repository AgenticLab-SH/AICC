# Security

AI Control Center operates local account, provider, browser, and desktop tools.
Report vulnerabilities through GitHub private vulnerability reporting. Do not
open a public issue containing credentials, account identifiers, local paths,
authenticated screenshots, or runtime databases.

## Local data boundary

- Source code is public and contains no personal configuration.
- Personal configuration lives in `~/.ai-control-center/config.env` with owner-only permissions.
- Authentication and runtime data remain in the native tool-owned home directories.
- The local server binds to `127.0.0.1` by default.
- Mutating actions require a fresh preview and a one-use confirmation token.

Never commit `.env`, `auth.json`, tokens, API keys, browser profiles, session
databases, or files from `~/.ai-control-center`, `~/.codex`, `~/.codex-multi`,
or `~/.opencodex`.
