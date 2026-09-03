# Indian Kanoon licensed adapter

**Owner:** Orchestrum Technologies LLP through CaseOps platform operations
**Implementation:** IPLF-054A/B
**Production state:** active for real workspaces; machine-blocked for QA/test workspaces

## Boundary

CaseOps calls only `https://api.indiankanoon.org` through the contracted API.
It does not scrape `indiankanoon.org` search, document, or bare-act HTML.
Public document URLs are generated only as safe source actions and carry the
required official responsive `Powered by IKanoon` logo attribution.

The adapter implements bounded search, processed document, original document,
exact fragment, metadata, health/readiness, import, content-change detection,
tenant cost attribution, and two-person legal-source review. Provider results
remain research aids. A successful provider response is not proof that a case
remains good law or that statutory text is current.

## Provider evidence checked 3 September 2026

The provider documentation describes these authenticated POST endpoints:

- `/search/?formInput=...&pagenum=...`
- `/doc/<docid>/`
- `/origdoc/<docid>/`
- `/docfragment/<docid>/?formInput=...`
- `/docmeta/<docid>/`

Authentication is server-side `Authorization: Token <token>`. The published
pricing checked on that date was INR 0.50/search, INR 0.20/processed document,
INR 0.50/original document, INR 0.05/fragment, and INR 0.02/metadata call.
Indian Kanoon's terms require its supplied logo for direct display and
conspicuous attribution for RAG/model uses. The service is prepaid and its terms
disclaim availability and accuracy warranties. Re-check the current
[`API documentation and pricing`](https://api.indiankanoon.org/) and
[`terms`](https://api.indiankanoon.org/terms/) before every activation or renewal.

## Activation checklist

All prerequisites are machine-verifiable. There is no human approval route or
approval key. A missing or expired item blocks every external request and leaves
the CaseOps corpus available.

1. Create the commercial API account, accept the provider terms, and record the
   permitted-use scope supplied during registration.
2. Record Orchestrum Technologies LLP as terms owner, the acceptance timestamp,
   and a future machine revalidation timestamp.
3. Put the API token in Secret Manager; never place it in Git, a browser env,
   a client response, logs, evidence, or a support ticket.
4. The release-owned `seed_indian_kanoon_costs` job idempotently creates the
   five active `actual`, high-confidence provider cost profiles for provider
   `indian-kanoon`, with the current pricing URL and dated evidence:
   `legal_source_search`, `legal_source_document`,
   `legal_source_original_document`, `legal_source_fragment`, and
   `legal_source_metadata`.
5. Set positive daily and monthly minor-unit budgets and a configured retention
   period. Budgets apply per tenant and are checked before a provider call.
6. Configure `CASEOPS_INDIAN_KANOON_PERMITTED_USES` with at least
   `search,document_display,research_storage`.
7. Bind `CASEOPS_INDIAN_KANOON_API_TOKEN` from Secret Manager and deploy the
   dated terms metadata, permitted uses, retention, budgets and enabled runtime
   switch through the canonical release script.
8. Verify readiness has no missing configuration, invalid terms, missing cost
   categories, or approval keys. Use fixture-backed tests for every endpoint and
   only one INR 0.50 live search canary for credential/provider verification.
   Check the official logo, billing usage, cache state, source opening, content
   hash, and audit records without repeating paid requests.

The API account, prepaid balance and accepted provider terms are configuration
facts, not approval gates. Once supplied, Codex-owned release automation seeds
prices, binds the secret, deploys the runtime and verifies the resulting state.

## Runtime behavior

- Requests use an eight-second default deadline, no redirects, a five MiB
  response ceiling, bounded result/page limits, and the pinned HTTPS API host.
- Search responses are process-cached for the configured TTL. A cache hit incurs
  no new provider cost. During provider timeout/5xx only, a cached response up
  to 24 hours old may be returned with a visible stale warning.
- Successful non-cached calls create tenant-visible `BillingUsageEvent` and
  `BillingUsageAttribution` records. Failed and blocked calls create no usage.
- Imported documents extend `AuthorityDocument`; they do not create a second
  corpus. The provider ID is stable, while the exact normalized content hash
  and source version identify the fetched version.
- A changed content hash resets legal review to `unreviewed` and invalidates
  every indexed frozen research report linked to the previous hash.
- First and second source approvals must be made by different memberships in
  the same workspace against the same content hash.

## Typed failures

| Code | Meaning | Operator response |
| --- | --- | --- |
| `provider_disabled` | Kill switch is off | Keep off until runtime prerequisites are complete |
| `provider_configuration` | Host, token, terms dates, permitted use, retention, or budget missing | Correct config without exposing values |
| `provider_terms` | Terms metadata is absent, invalid, or expired | Refresh the dated terms configuration |
| `provider_cost_policy` | One or more actual costs lacks high-confidence source/evidence | Refresh the machine-verifiable pricing profile |
| `provider_budget_exhausted` | Tenant daily/monthly budget reached | Review usage; do not bypass silently |
| `provider_authentication` | Provider rejected server credential | Rotate/reconcile secret and keep disabled if uncertain |
| `provider_quota` | Prepaid balance or rate quota unavailable | Reconcile provider account and retry after it is funded |
| `source_removed` | Document is absent or withdrawn | Preserve prior lineage; mark unavailable and verify elsewhere |
| `provider_contract_changed` | Redirect, malformed JSON, excess size, or shape drift | Disable, inspect docs/terms, update fixtures and adapter |
| `provider_outage` | Timeout, network error, or provider 5xx | Use visibly stale cache if supplied; otherwise retry later |

## Kill switch and incident response

Set `CASEOPS_INDIAN_KANOON_ENABLED=false` and deploy a new API revision. Confirm
readiness reports `blocked_disabled`, external calls are false, and unrelated
authority search remains responsive. Do not delete source lineage or frozen
reports. Rotate the token if credential exposure is possible, record the
incident and affected call window, reconcile provider invoices against billing
usage, and require fresh terms/cost/canary evidence before re-enabling.

## Release verification

Run the focused API, migration, provider-readiness, source-action, web, and
Playwright tests; regenerate OpenAPI and the data-governance map. After merge,
deploy the exact main SHA with the canonical migration-before-traffic pipeline,
verify API/web image digests and revisions, then run the dated production
acceptance. Production automation uses fixture responses and the no-paid-provider
marker; a single separately recorded live search is the activation canary and
must not be repeated by regression runs.
