# Project maintenance policy

Use this policy for repositories registered in
`~/.ai-control-center/cross-device/project-portfolio.toml`.
It is a reference, not an always-loaded agent harness.

## Canonical state

- Use the local Git-root directory basename as the GitHub repository name. When
  that basename is not a valid or useful GitHub name, record the exception as
  `github_name_override` in `~/.ai-control-center/cross-device/project-portfolio.toml`;
  do not silently
  invent a second alias.
- Keep active source, tests, architecture decisions, operational documentation,
  lockfiles, schemas, migrations, small fixtures, and reproducible configuration
  in the registered canonical repository. Private is the default; a public
  canonical requires an explicit portfolio visibility declaration and must not
  contain private-only source or data.
- Treat other public repositories as allowlisted deployment or collaboration
  surfaces, never as the only copy of private source.
- Do not bulk-commit migration archives, vendor mirrors, generated homes, or
  nested historical clones. Git history already preserves superseded states.
- Mark a repository `remediation` and record its blocker when its current
  history contains credentials, browser profiles, caches, or unrelated binary
  payloads. Do not clone unsafe history into a newly named private canonical.
- Preserve user branches and dirty work. Inspect each repository and diff before
  staging; never use one cross-repository `git add -A` operation.

## Data that never belongs in Git

Repository privacy is access control, not a secret store. Exclude credentials,
tokens, passwords, private keys, auth files, cookies, browser profiles, account
or session databases, live logs, caches, dependency directories, build output,
and machine runtime state. Use environment variables, OS/keychain secret
storage, GitHub Actions secrets, or a purpose-built encrypted data store.

Track important non-secret material rather than hiding it behind broad ignore
rules. For large durable binaries, use Git LFS or an appropriate release/object
store; do not force oversized blobs into normal Git history.

Before every publication:

1. Confirm the intended canonical remote, visibility, and branch.
2. Review status, untracked files, diff, and files larger than 5 MiB.
3. Run `gitleaks` on the staged content and never bypass a real finding.
4. Run the repository's closest tests, lint, type checks, and build.
5. Commit one coherent scope, push without force, and verify the remote SHA.

## Maintenance and upgrades

- Prefer current official documentation, standards, source repositories, release
  notes, and security advisories over cached trend summaries.
- Upgrade because a supported version, security issue, measurable maintenance
  benefit, or project requirement justifies it—not merely because a version is
  new. Preserve deliberate cost, compatibility, and deployment constraints.
- Make the smallest behavior-preserving upgrade first. Update lockfiles and
  migrations together, add regression coverage, and document breaking changes
  and rollback steps.
- Refactor when ownership, data flow, side effects, or repeated defects justify
  it. Avoid speculative abstractions and full rewrites without measured benefit.
- Review each active project on demand and after meaningful dependency or
  platform changes. Archived, deployment-only, and third-party mirrors are not
  continuously refactored.

## Repository documentation

Each active source repository should have concise root documentation:

- `README.md`: purpose, current status, setup, architecture, run/test/build,
  deployment destination, and data/security boundaries.
- `AGENTS.md`: repository-specific layout, exact validation commands, constraints,
  and completion criteria. Add nested overrides only for real subsystem differences.
- A short change or release record only for material decisions not clear from
  code and Git history.

This follows current Codex guidance to keep `AGENTS.md` short and practical and
to turn only repeated specialized workflows into skills. GitHub recommends push
protection and secret storage even for restricted repositories, and Git LFS for
files beyond normal Git limits:

- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://learn.chatgpt.com/docs/build-skills.md
- https://docs.github.com/en/code-security/concepts/secret-security/push-protection
- https://docs.github.com/en/actions/concepts/security/secrets
- https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage
