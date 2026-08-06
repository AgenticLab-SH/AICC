# Security Policy

Codex Account Manager works with local Codex authentication state. Treat any
unexpected credential exposure, account crossover, unsafe file permissions, or
command execution as a security-sensitive report.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository when it is
available. If that option is unavailable, open a public issue containing only
a request to establish private contact. Do not include vulnerability details
until a private channel has been agreed.

Do not open a public issue containing:

- access, refresh, API, or session tokens;
- real `auth.json` or account-store files;
- cookies, browser profiles, or session databases;
- unredacted email addresses, account IDs, or private filesystem paths.

Provide synthetic reproduction data where possible. The maintainer will
acknowledge a complete report, investigate impact, and coordinate a fix and
disclosure timeline before public discussion.

## Supported versions

Until tagged releases begin, only the latest commit on the default branch is
supported. Security fixes will be documented in the first appropriate release
or repository advisory.

## Security boundaries

The project is designed to keep credentials on the local machine, avoid
printing token material, and compare credentials by digest. It does not grant
permission to automate accounts in ways prohibited by a service's terms. Users
remain responsible for reviewing those terms and securing their local machine.
