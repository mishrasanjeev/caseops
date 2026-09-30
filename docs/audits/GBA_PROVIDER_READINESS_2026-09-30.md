# GBA provider readiness: 2026-09-30

Verdict: **NO-GO** for the claim that every provider works end to end for GBA.
This is a read-only production audit of `gba-law` on the API/web tree
`37d54ec9cffd52100425452f4a4c8235f1674c53`, plus source and local test
inspection. The subsequent code patch is not production evidence until merged,
deployed and tested on the exact serving revision. No paid provider call or GBA
write was made during this audit.

| Capability | Status | Production evidence and remaining gate |
| --- | --- | --- |
| eCourts tracking | Partially implemented | Token and schedule are configured, but connector health is degraded/failed. GBA has 586 tracked cases; only 46 have ever succeeded. Of 583 eligible, 538 were due; 534 lacked CNR and 535 lacked a court code. The last five scheduled runs were partial. The latest checked 0, blocked 44, made 6 provider calls and left 538 backlogged. The Cloud Run job's exit 0 is not a tenant-success signal. Exact case-number search with no code is now blocked locally before transport/spend, and skipped rows remain counted. A reviewed CNR or provider-published court code is still needed for the affected records; no code may be guessed from court name. Require a meaningful returned case, linked hearing date after reload and two clean 18:00-20:00 IST cadences before closure. |
| Indian Kanoon | Partially implemented | Tenant has an active provider-spend exception and production binds a token, terms and positive budgets. Five recent searches do not prove a meaningful legal result, current provider balance or exact-source acceptance. Keep no-paid automated tests and obtain a funded human-owned canary with reviewed attribution and current terms. |
| OpenAI and Voyage | Partially implemented | API key bindings and selected models exist; GBA's assistant policy is enabled. This does not prove quota, grounded output, embedding quality or a complete GBA matter journey. Verify funded account state and exact-source output under the existing review controls. |
| SendGrid email | Partially implemented | Key, sender and webhook public-key bindings exist, but external delivery is disabled at runtime. Four recent GBA email intents were blocked; none was delivered. Verify authenticated sender, consent, callback and delivery before enabling. In-app notifications remain usable. |
| Google Workspace Gmail, Calendar and Drive | Missing | APIs may be enabled in GCP, but production OAuth bindings and GBA user connections are absent; connector health says `missing_config`. Google Cloud ownership cannot grant GBA mailbox/calendar/Drive consent. Complete OAuth and tenant-authorized connections. |
| Microsoft 365, Outlook and OneDrive | Missing | No production Entra OAuth configuration or GBA connection. Requires Microsoft app/tenant consent. |
| SMS and WhatsApp | Missing | Disabled, no approved sender/template or callback credentials. Do not present a user preference toggle as working delivery. |
| Pine Labs Plural | Missing | Payment links and subscriptions are off. Merchant credentials, signed webhook, UAT reconciliation and reviewed activation are absent. |
| IP India / WIPO registry | Missing | Live lawful-access/provider contract and production adapter remain absent. No scraping workaround. |

## Root cause and recurrence

The scheduler admitted legacy Matter-linked bookmarks identified only by a case
number and human court name. The eCourts exact-search API uses a public
registration/filing number plus provider court code; its `courtName` field is
not a safe substitute for the indexed `courtCodes` filter. The search could
therefore consume credit yet return incomplete candidates. Failing closed after
the response prevented a wrong match but did not prevent repeat paid attempts.
The adapter now rejects that query before transport; the service additionally
checks before spend reservation and excludes unsearchable rows from its bounded
scheduled batch without hiding them from blocked/backlog metrics. This is a
prevention fix, not a backfill of verified identities or a claim that GBA is
green. Local regressions cover no transport/spend, short valid codes, CNR,
legacy hearing sync and the GBA PRD.

The human-approved window is **18:00-20:00 Asia/Kolkata for every tenant**.
This supersedes the source GBA document's 16:00-18:00 request. Scheduled
provider eligibility is separate from configured credentials, completed job
exit code, and current browser policy. No paid automated acceptance is allowed.

## Closure gates

1. Obtain the GBA court/identifier inventory from an authorized owner. Review
   official provider codes or CNRs and correct records through audited product
   paths; 280 tracked rows have no court name or code at all. Do not infer a
   mapping from similarly named records or write directly to the tenant DB.
2. Run a funded, authorized **human** eCourts exact-case lookup and hearing
   reload for a specified GBA Matter. Automated verification remains no-paid.
3. Obtain vendor account, sender, OAuth consent and merchant/registry evidence
   for each desired external integration. The guide is
   `docs/runbooks/provider-setup-2026-09-24.md`.
4. Merge the prevention patch to main, run full Docker/PostgreSQL and Playwright
   acceptance, deploy exact main, and verify the actual serving API/web SHA.
   Recheck GBA read-only connector health and two clean scheduled cadences.
   Without these gates, do not mark this audit implemented or production green.
