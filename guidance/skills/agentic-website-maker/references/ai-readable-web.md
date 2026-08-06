# AI-readable web surface

Make a site readable by an external web-browsing model (ChatGPT web, search
crawlers) without exposing private product source or user data. Apply when the
user wants a model to review, audit, or discuss a deployed site through a link.

## Contents

- [Why this is needed](#why-this-is-needed)
- [Verify actual visibility](#verify-actual-visibility-before-claiming-it)
- [Publish a public specification](#publish-a-public-specification-not-a-scraped-screen)
- [Priority order](#priority-order)
- [Confirm and record](#confirm-with-the-model-then-record)

## Why this is needed

A model that opens a URL usually receives the first HTML response only. It does
not authenticate, does not run long client-side flows, and cannot see anything
behind a login gate. A client-rendered app or a gated editor therefore looks
empty or unavailable even when the product works.

URL fragments are never sent to the server. `#data` and `#passmap` resolve to
the same document, so hash-routed screens cannot be inspected as separate pages.

## Verify actual visibility before claiming it

Do not infer reachability from a normal browser request. OpenAI currently
documents `OAI-SearchBot` for ChatGPT search discovery and `GPTBot` for model
training. Their controls are independent. Verify the exact, current user-agent
tokens against the [official OpenAI crawler documentation](https://developers.openai.com/api/docs/bots)
before testing because the documented versions can change.

Check each crawler path explicitly and report the real status per host. The
following loop deliberately uses the stable product tokens rather than pinning
an obsolete version string:

```bash
for ua in OAI-SearchBot GPTBot; do
  curl -sS -o /dev/null -w "%{http_code} $ua\n" -A "$ua" "https://example.com/"
done
```

Allowing `OAI-SearchBot` does not opt a site into training, and blocking
`GPTBot` does not remove it from search. Do not add or test an undocumented
client user agent as though it were a published crawler. A model opening a
user-provided link may use a separate client fetch path; verify that behavior
through the product itself and label the result separately.

A `403` with `server: cloudflare` and a permissive `robots.txt` indicates an
edge AI-bot rule, not a site bug. Edge bot rules can run before any allow rule,
so `robots.txt` alone does not grant access. Treat the zone setting as the fix
and say so instead of editing site files that cannot change the outcome.

Thus, "the model could read it in chat" does not prove a published crawler is
allowed. Report the interactive-link and crawler results separately.

## Publish a public specification, not a scraped screen

For any login-gated screen, ship a public document that describes it. This is
the highest-value artifact because it works with zero authentication.

Serve each document as HTML plus a plain-text mirror at stable paths:

```
/public-spec/            # human-readable HTML, indexable
/public-spec/index.txt   # same content as text/plain
/public-spec/screens.txt # per-screen controls and states
/public-spec/index.md    # authored markdown source, secondary
/llms.txt                # index of the above with absolute URLs
```

Requirements:

- Prefer `text/plain` for machine-readable mirrors. A reviewing model confirmed
  that `text/markdown` responses fail with `Unsupported content-type` even when
  the server returns HTTP 200, while `text/plain` and `text/html` parse as body
  content. Keep `.md` as the authored source and generate `.txt` from it.
- Link the `.txt` paths first from both `llms.txt` and the HTML page.
- Use absolute URLs inside `llms.txt` so a model can follow them from any context.
- Keep the HTML version meaningful without JavaScript.
- Write plain-text mirrors without markdown pipe tables or code fences, since
  nothing renders them. Flatten a table to `헤더: 값` pairs per row.
- Generate the mirrors in the build pipeline so they cannot drift from the source.
- Include no user data, credentials, private endpoints, or paid-entitlement logic.

Cover at minimum: purpose, tab/screen map with the control names, data providers
and what each actually supplies, output formats, save/preset rules, loading and
empty and error states, accessibility affordances, and responsive behavior.

For a review that can find real defects, add three more documents. A reviewing
model used exactly these to identify concrete bugs without ever logging in:

- `workflows.txt`: each step's entry condition, completion condition, next step,
  and failure behavior.
- `controls.txt`: per control the display name, type, default, allowed range with
  units, dependencies, side effects, and whether it persists to project, preset,
  device, or only the session. Read real defaults and slider bounds from code.
- `data-contract.txt`: how official provider totals and locally computed totals
  are each defined, and every reason the two can differ.

## Priority order

1. Meaningful first-response HTML for public pages (SSR, SSG, or prerender).
2. Public specification pages plus plain-text mirrors for gated screens.
3. `sitemap.xml` listing only the public documents you want read.
4. JSON-LD (`WebSite`, `SoftwareApplication`, `TechArticle`) as a supplement.
5. `llms.txt` as a discovery index. It is a convention, not a standard, so never
   rely on it as the only path.

Real routes beat hash fragments when a model must inspect screens separately.
Prefer `/data` over `#data` when the screen has publishable content. When the
screen is gated anyway, a public specification document is the better investment
and should be built first.

## Confirm with the model, then record

Ask the reviewing model to quote a specific line from each published document.
An answer without a quotation is not evidence that the document was read. Record
the verified paths and the confirmation in the project profile or handoff so the
next agent does not repeat the discovery.
