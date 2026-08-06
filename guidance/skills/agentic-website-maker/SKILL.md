---
name: agentic-website-maker
description: Build or maintain AgenticFabWorks sites, Cloudflare deployment, domains, and safe public-output boundaries.
---

# Agentic Website Maker

Turn a short site request into a finished, verified, recorded production release.
Recover prior decisions from project and AICC personal records before asking the user.

## Load only what the job needs

- Read `references/release-contract.md` before publishing, changing a domain, or
  recording a release.
- Read `references/ai-readable-web.md` when a model must review the deployed site
  through a link, when a screen is login-gated, or when the user asks whether
  ChatGPT or a crawler can see the site.
- Read `references/design-system.md` before changing visual design, layout,
  spacing, typography, motion, or responsive behavior on any site. It carries the
  concrete token values and the per-screen checklist.
- Run `scripts/audit_sites.mjs` from a directory that has Playwright installed to
  measure undersized text, small hit targets, overflow, and console errors before
  and after a design change. Compare the numbers instead of asserting improvement.
- Read `references/pattern-library.md` when polishing an existing AgenticFabWorks
  screen. It maps concrete interaction patterns from named live products to each
  service, with a "skip if" note per pattern. Verify a pattern against the live
  site before adopting it, and never let a borrowed pattern change the product's
  purpose or hide existing functionality.
- Run `scripts/site_ops.py --help` for deterministic profile, registry, and
  verification operations.
- Use the host's native Sites capability only when the user selects OpenAI Sites
  or a source-root `.openai/hosting.json` matches the recorded provider. Ignore
  manifests under generated `dist` or `build` directories.
- Use `browser-qa` for browser validation and `choose-browser-session` before
  continuing a logged-in Cloudflare tab.
- Use the host's native image-generation capability only when original visual
  assets materially improve the site.

## Resolve context without repeated questions

1. Read the nearest `AGENTS.md`, project docs, source-root `.openai/hosting.json`,
   `.openai/website-profile.json`, and the domain workspace manifest when
   present.
2. Read `~/.ai-control-center/guidance/website-maker.json` plus
   `~/.ai-control-center/guidance/website-projects.json` when present.
3. Inspect the current repository and preserve unrelated dirty work.
4. Reuse recorded brand sources, data policy, provider, project ID, domains,
   aliases, and verification expectations.
5. Ask only for a decision that cannot be discovered and would materially
   change the product, data rights, cost, or public destination.

## Execute the release

### 1. Define the product

Infer a concise brief: audience, primary action, information hierarchy,
responsive behavior, accessibility, brand sources, data mode, and release
host. Prefer progressive disclosure over long walls of text.

When the user supplies a creator or company URL, inspect its visible brand
system and use authorized logos/assets where available. Do not invent brand
claims or scrape private material.

### 2. Protect the data contract

Record one of these modes in the project profile:

- `live`: production uses real API or permitted web data.
- `user-owned`: production uses user-provided files.
- `static`: editorial content with no match/event simulation.
- `fixture-only`: fixtures exist only for automated tests.

Never silently replace requested live data with generated or synthetic data.
Fail clearly and preserve the last verified real result when appropriate.

### 3. Protect the source and build

Keep the product source in a private repository. A browser must receive HTML,
CSS, JavaScript, media, and WebAssembly needed to render the page, so do not
claim those delivered assets are secret. Move actual secrets, paid entitlement
decisions, private datasets, and privileged algorithms behind a server boundary.

Generate an allowlisted production directory. Exclude repository history,
documentation, tests, admin utilities, local configuration, credentials, source
maps, development comments, and unrelated files. Minification raises copying
cost but is not a security boundary.

Implement the complete user flow, responsive layout, loading/empty/error states,
keyboard access, and production metadata. Validate in proportion to risk:

- format, lint, type checks, tests, and production build;
- desktop and mobile critical flows;
- console and network errors;
- real-data source attribution and no fabricated fallback;
- no secret or credential in client code, logs, commits, or archives;
- only allowlisted production files in the deployment directory;
- no source map, private path, or repository-only file in the public response.

### 4. Select the domain once

Treat the chosen primary hostname as durable product identity.

1. Check the central registry and Cloudflare before claiming it.
2. Query public or authoritative DNS directly; do not prime the OS resolver with
   a not-yet-created hostname.
3. Prefer a memorable brand-led hostname such as `{brand}-studio`.
4. Keep old working hosts as aliases unless the user asks to remove them.
5. Record the primary host in application metadata, documentation, and the
   project profile.

### 5. Select and verify the provider

Reuse the recorded provider unless the user requested a migration. Check the
actual provider state before publishing:

- `cloudflare-pages`: static sites and client applications. Prefer direct upload
  from a verified private checkout and record the Pages project name.
- `cloudflare-worker`: server logic or controlled API boundaries. Inspect
  routes, custom domains, plan, limits, and bindings before deployment.
- `firebase-hosting`: keep only when the application depends on Firebase
  deployment or backend services and the cost is justified.
- `openai-sites`: use only when selected by the user or confirmed by a
  source-root `.openai/hosting.json`. Reuse its opaque `project_id`; never
  create a duplicate site from a generated-output manifest.

Do not silently migrate providers, accounts, zones, repositories, or regions.
Do not enable a paid Workers plan, Pages Function, Firebase Blaze resource, or
automatic billing feature merely to complete a static deployment.

### 6. Publish the exact validated source

For Cloudflare Pages, confirm `wrangler whoami`, the account, existing project,
production branch policy, and the allowlisted output directory before direct
upload. Poll the deployment and custom-domain status until terminal.

For OpenAI Sites, push the exact validated source, package that same source, save
one version, and deploy only the saved version.

A request to publish or connect a public domain authorizes the matching public
deployment. Do not broaden access beyond the requested site.

### 7. Connect Cloudflare DNS

Use the native browser capability selected for the task. If the user explicitly
asks to continue an existing signed-in browser tab, apply
`choose-browser-session` and do not switch browsers, profiles, or accounts.

1. Confirm the hostname is unoccupied in the central registry, Cloudflare
   custom domains, DNS records, Pages, and Workers.
2. Attach the custom domain in the selected provider first.
3. For Cloudflare Pages, use the provider-created Pages custom-domain route and
   do not add a competing Worker custom domain.
4. For OpenAI Sites or another external provider, copy the exact CNAME and TXT
   values and use the proxy mode required by that provider.
5. Preserve unrelated DNS, email, verification, and security records.
6. Verify authoritative DNS, public recursive DNS, provider status, and TLS.
7. Do not create or close unrelated Whale tabs.

### 8. Prove the real URL and indexing contract

Run `site_ops.py verify` against the normal hostname, not only an IP override.
Check the homepage and critical APIs. Open the primary URL in a browser and
confirm the critical real-data or content flow plus zero relevant console
errors.

For indexable sites also verify unique title, description, H1, canonical,
`robots.txt`, host-local `sitemap.xml`, real 404 behavior, redirect targets, and
static HTML content. Do not submit a sitemap or request re-indexing until the
production hostname and canonical structure are stable.

Do not call a domain complete while the user's normal browser still returns
`ERR_NAME_NOT_RESOLVED`, 403, 404, or 5xx. Diagnose DNS propagation, negative
cache, certificate validation, and provider routing separately.

### 9. Record only verified state

After production succeeds:

1. Run `site_ops.py record` to update `.openai/website-profile.json` and the
   central registry atomically.
2. Include the primary hostname, aliases, project path, provider project,
   private source repository, deployment mode, data mode, verification time,
   and successful checks.
3. Update project handoff/release docs when they exist.
4. Report the primary URL, preserved aliases, data mode, tests, and any
   unresolved licensing or external dependency.

## Fast invocation examples

- “이 사람 스타일로 사이트 만들어서 내 도메인에 배포해.”
- “이 프로젝트 남은 것 완성하고 `{brand}-studio`로 연결해.”
- “대표 도메인 바꾸고 기존 주소는 보조로 남겨.”
- “새 Pages 프로젝트를 만들고 하위 도메인과 DNS를 연결해.”
- “공개 GitHub Pages 코드를 private 정본과 이동 전용 저장소로 분리해.”
- “전에 만든 사이트 기록을 읽고 같은 방식으로 새 사이트 만들어.”
