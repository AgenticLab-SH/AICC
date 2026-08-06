# Website release contract

## Sources of truth

Use these in order:

1. user instruction in the active request;
2. nearest project `AGENTS.md`;
3. `.openai/website-profile.json`;
4. `.openai/hosting.json`;
5. AICC personal `~/.ai-control-center/guidance/website-projects.json`;
6. current provider and DNS state;
7. project docs and handoff notes.

Do not overwrite a newer provider state with an older note.

## Project profile

Store project-specific durable decisions in `.openai/website-profile.json`:

```json
{
  "schema_version": 1,
  "title": "Example Studio",
  "primary_domain": "example-studio.agenticfabworks.com",
  "aliases": ["example.agenticfabworks.com"],
  "hosting_provider": "openai-sites",
  "provider_project": "appgprj_example",
  "deployment_mode": "saved-version",
  "source_repository": "owner/private-repository",
  "source_visibility": "private",
  "dns_provider": "cloudflare",
  "data_mode": "live",
  "brand_sources": ["https://www.instagram.com/example/"],
  "data_sources": ["Official API"],
  "critical_paths": ["/", "/api/data"],
  "last_verified_at": "2026-07-26T18:00:00+09:00"
}
```

Do not store tokens, cookies, API keys, browser profile paths, or short-lived
repository credentials.

## Provider decision

Reuse the recorded provider unless the user requested migration.

| Provider | Use for | Required identifier |
|---|---|---|
| `cloudflare-pages` | Static sites and browser applications | Pages project name |
| `cloudflare-worker` | Server logic and controlled APIs | Worker script name |
| `firebase-hosting` | Existing Firebase-dependent applications | Firebase project/site |
| `openai-sites` | Projects with `.openai/hosting.json` | Exact opaque Sites project ID |

Before publishing, inspect the account, plan, bindings, custom domains, build
output, and current production deployment. Do not activate paid compute or
automatic billing merely to deploy static files.

## Domain sequence

1. Normalize the candidate to lowercase ASCII.
2. Confirm it is within a root domain allowed by `website-maker.json`.
3. Check `website-projects.json` for ownership conflicts.
4. Query Cloudflare authoritative or public DNS directly. Avoid a system
   `getaddrinfo` lookup before creation because negative DNS caching can outlive
   the record change.
5. Attach the hostname to the selected provider project.
6. For Cloudflare Pages, use the Pages custom-domain route and avoid a competing
   Worker custom domain. For external providers, enter the exact CNAME and
   validation TXT values.
7. Confirm authoritative DNS, then public recursive DNS.
8. Wait for provider routing and SSL status to become active.
9. Verify normal HTTPS resolution and critical paths.
10. Record the release.

Keep the Sites CNAME DNS-only unless the provider explicitly changes the
requirement.

## Source privacy contract

- Keep the canonical product repository private.
- Publish only an allowlisted build directory.
- Exclude Git history, documentation, tests, admin files, credentials, source
  maps, local paths, and unrelated artifacts.
- Treat browser-delivered HTML, CSS, JavaScript, media, and WebAssembly as
  inspectable.
- Keep secrets, paid entitlement checks, private data, and privileged
  algorithms on a server boundary.
- If legacy `github.io` traffic must survive, use a separate public `noindex`
  redirect-only repository with no product history.

## Verification tiers

### Required

- normal DNS resolution;
- valid TLS certificate for the hostname;
- homepage 2xx;
- intended provider project and account;
- production title and primary content;
- critical API paths 2xx;
- no requested-real-data fallback to synthetic content.

### UI release

- desktop and mobile critical flows;
- empty, loading, and error states;
- keyboard focus and readable contrast;
- no relevant browser console errors.

### Indexable release

- unique title, description, H1, and canonical;
- valid host-local `robots.txt` and `sitemap.xml`;
- correct 301/302 targets and real 404/410 responses;
- useful static HTML content before client hydration;
- no canonical conflict between provider and legacy hosts.

### Data release

- source attribution;
- clear freshness/failure state;
- no secrets in client bundles;
- no raw restricted response persisted unless explicitly permitted.

## Failure policy

- NXDOMAIN: inspect authoritative and recursive DNS separately from OS/browser
  cache.
- 403: wait for hostname validation or inspect provider access rules.
- 404: hostname route is not attached to the deployed worker.
- 5xx during activation: continue bounded polling while the provider reports a
  transition; fail if the provider becomes terminal.
- local cache only: keep the canonical hostname. Do not rename the product just
  to hide a cache problem unless the user chooses a new identity.
