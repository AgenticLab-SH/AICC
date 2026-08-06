# Login verification flow

Use this state model for a single explicitly authorized site login.

| State | Required evidence | Allowed next action | Stop condition |
|---|---|---|---|
| `initialize` | verified origin and intended login control | wait for the same control and adjacent status to settle | wrong origin or a different login surface appears |
| `inspect` | verified origin, intended account, selected task tab | preserve autofill; fill only missing fields | wrong origin/account or unrelated tab |
| `account-chooser` | visible existing account identities | choose the one matching verified task context | two or more accounts remain plausible |
| `autofill` | expected ordinary identifier/password field | focus once; preserve populated values; fill only missing DOM fields | unexpected origin or credential-change flow |
| `native-auth` | expected OS/password-manager sheet | Computer Use enters the task-provided value in native UI | credential change, recovery, or unknown sheet |
| `email-wait` | email challenge triggered now | narrow read-only search; newest unique match | ambiguous account/message or stale code |
| `sms-readiness` | correlated Telegram request exists | bounded wait; independent work may continue | no readiness means no SMS send |
| `sms-sent` | matching readiness received and site send clicked | correlated Telegram code prompt | transport conflict or site changed challenge |
| `code-received` | allowed user replied to the exact force-reply prompt | enter immediately in this challenge only | rejection or expiry routes to fresh readiness |
| `oauth-return` | provider callback returned to the expected site | wait for result exchange and inspect status/network errors | missing result or provider failure after one bounded retry |
| `verify` | expected signed-in account/destination visible | finish Telegram request and report redacted evidence | chooser/callback/redirect alone or uncertain identity |

## Tool ownership

- `choose-browser-session`: browser, account, profile, workspace, target/tab.
- Browser or Chrome control skill: normal page DOM and challenge controls.
- `computer-use`: native macOS/application/password-manager sheets only.
- `gmail-mail` / `naver-mail` / `read-mail`: read-only delivery lookup.
- `telegram-notify`: correlated readiness and one-time-code transport.
- `complete-site-login`: state transitions, freshness, and final login proof.

## Freshness and ambiguity

Record the challenge trigger time mentally or in non-secret task state. Match
mail by sender/domain, recipient, subject/site, and time. Match Telegram by the
helper's request ID and nonce. Never select a candidate solely because it is
newest. One active SMS verification request is allowed per Telegram route so a
bare numeric reply cannot be attributed to the wrong site.

Do not record secret values while tracking state. It is sufficient to record
channel, request ID, stage, timestamps, and redacted success/failure.

## Continuity after a login failure

Keep source edits, local tests, and public read-only research moving when they
do not require the blocked session. Do not claim production UI verification
from local evidence. Preserve the selected browser and account boundary, record
the redacted provider status, and return to production verification after the
login path is healthy.
