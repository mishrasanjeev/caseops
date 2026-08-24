# Indian Kanoon licensed adapter

**Owner:** CaseOps platform operations and Legal jointly
**Implementation:** IPLF-054A/B
**Default state:** deployed, disabled, no external calls

## Boundary

CaseOps calls only `https://api.indiankanoon.org` through the contracted API.
It does not scrape `indiankanoon.org` search, document, or bare-act HTML.
Public document URLs are generated only as safe source actions and carry the
required `Powered by Indian Kanoon` attribution.

The adapter implements bounded search, processed document, original document,
exact fragment, metadata, health/readiness, import, content-change detection,
tenant cost attribution, and two-person legal-source review. Provider results
remain research aids. A successful provider response is not proof that a case
remains good law or that statutory text is current.

## Contract evidence checked 25 August 2026

The provider documentation describes these authenticated POST endpoints:

- `/search/?formInput=...&pagenum=...`
- `/doc/<docid>/`
- `/origdoc/<docid>/`
- `/docfragment/<docid>/?formInput=...`
- `/docmeta/<docid>/`

Authentication is server-side `Authorization: Token <token>`. The published
pricing checked on that date was INR 0.50/search, INR 0.20/processed document,
INR 0.50/original document, INR 0.05/fragment, and INR 0.02/metadata call.
Indian Kanoon's terms require conspicuous attribution for direct display and
attribution for RAG/model uses. The service is prepaid and its terms disclaim
availability and accuracy warranties. Re-check the current
[`API documentation and pricing`](https://api.indiankanoon.org/) and
[`terms`](https://indiankanoon.org/terms.html) before every approval or renewal.

## Activation checklist

All gates are conjunctive. A missing or expired item blocks every external
request and leaves the CaseOps corpus available.

1. Execute and archive the signed provider contract and permitted-use scope.
2. Legal approves coverage, display/attribution, RAG/storage, redistribution,
   retention, deletion, expiry, and incident obligations.
3. Record a named terms owner, approval timestamp, and future expiry timestamp.
4. Put the API token in Secret Manager; never place it in Git, a browser env,
   a client response, logs, evidence, or a support ticket.
5. Create five active `actual` provider cost profiles for provider
   `indian-kanoon`, with source/evidence and explicit platform approval:
   `legal_source_search`, `legal_source_document`,
   `legal_source_original_document`, `legal_source_fragment`, and
   `legal_source_metadata`.
6. Set positive daily and monthly minor-unit budgets and an approved retention
   period. Budgets apply per tenant and are checked before a provider call.
7. Configure `CASEOPS_INDIAN_KANOON_PERMITTED_USES` with at least
   `search,document_display,research_storage`.
8. Deploy with `CASEOPS_INDIAN_KANOON_ENABLED=false`; verify migration, health,
   source URL safety, and exact release identity first.
9. Bind `CASEOPS_INDIAN_KANOON_API_TOKEN` from Secret Manager, set all dated
   approvals and budgets, then change the kill switch to `true`.
10. Verify `/api/authorities/providers/indian-kanoon/readiness` is `ready` and
    run a low-cost canary for every endpoint. Check attribution, billing usage,
    cache state, source opening, content hash, and audit records.

Do not activate from repository fixtures or this runbook alone. Contract,
Legal, Security, Finance, and provider acceptance are external decisions.

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
| `provider_disabled` | Kill switch is off | Keep off until activation is approved |
| `provider_configuration` | Host, token, terms dates, permitted use, retention, or budget missing | Correct config without exposing values |
| `provider_terms` | Terms/coverage absent, invalid, or expired | Legal review and dated renewal |
| `provider_cost_policy` | One or more actual costs are not approved | Finance/platform approval |
| `provider_budget_exhausted` | Tenant daily/monthly budget reached | Review usage; do not bypass silently |
| `provider_authentication` | Provider rejected server credential | Rotate/reconcile secret and keep disabled if uncertain |
| `provider_quota` | Prepaid balance or rate quota unavailable | Reconcile provider account and retry only when approved |
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
acceptance. In production's default-off state, acceptance must prove the
readiness panel is blocked and no provider request occurs. It must not be
reported as live-provider, legal, or pilot-firm acceptance.
