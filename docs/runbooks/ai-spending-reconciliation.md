# Shared AI Spending Reconciliation

Owner decision, 1 November 2026: the shared guard is **off by default**
(`CASEOPS_AI_MONEY_BUDGET_ENABLED` unset or `false`). OpenAI and Voyage are prepaid
accounts whose monthly spend cannot be reconciled, and an unreconciled November
refused every paid AI action in production that morning. Production was restored
by deferring the start month on caseops-api (revision 00506) and the three AI jobs.
Enable the guard only together with a reconciled month row; the procedure below
applies then.

Status: candidate implementation, not a production activation receipt.
Owner instruction on 11 October 2026: October continues unchanged; the new
allowance is INR 10,000 per month. The candidate defaults to enabled from
November 2026, measured in IST. No monthly policy or provider switch was applied
to production while writing this runbook.

## What The Control Covers

The five paid SDK boundaries share one account-level allowance: OpenAI text and
structured generation, Gemini generation, Voyage embeddings and Gemini
embeddings. Corpus jobs, scripts and tenant requests use those same adapters.
Mock, replay and local embeddings do not spend this allowance. Court-data and
hosting invoices are outside this AI allowance.

Every executor using the provider account must use the **same authoritative
database**. A separately funded workstation database would be a separate
allowance. Do not initialize it with a production key. Calls made outside
CaseOps, another application sharing the account, pricing changes and provider
invoice adjustments cannot be constrained by this application ledger. Reconcile
those liabilities and use dedicated provider projects/keys where possible.

The ledger reserves conservative worst-case liability before transport, using
UTF-8/framing/schema bounds, the effective output ceiling, all SDK attempts and
an all-in currency multiplier. A timeout, rejection, malformed answer, process
crash or rollover refusal does not refund an uncertain charge. These reservations
are **not actual invoiced spend**. The control can stop earlier than the nominal
ceiling; it does not guarantee that an external invoice equals the ledger.

## Monthly Procedure

1. Verify the exact API, web, jobs and workstation release identities. Confirm
   the two financial tables were migrated before enabling the guard. Keep
   October's exception; do not change provider selection as part of this step.
2. Obtain provider-account billing evidence for all AI providers and other users
   of those accounts. Include pending usage, taxes, fees and currency conversion.
   Never infer a zero opening balance from empty application logs.
3. Retain the billing evidence securely and compute its SHA256. The database
   stores only its hash, not invoices, credentials or private client content.
4. Review and pin current official pricing for **every exact provider/model
   identity** in use. Retain the source bytes and their SHA256. Use conservative
   rates covering cache writes, priority/region/context premiums and every
   applicable auxiliary charge. The current initializer supports text-token
   pricing only; do not admit an unsupported billable modality or tool.
5. Prepare a bounded JSON policy with these required keys:

   | Key | Meaning |
   | --- | --- |
   | `month` | Exact IST month, `YYYY-MM` |
   | `limit_minor` | Paise, positive and at most `1000000` |
   | `opening_spend_minor` | Explicit reconciled opening liability in paise, including pending costs |
   | `inr_per_usd_all_in` | Conservative INR/USD multiplier including applicable taxes and fees |
   | `opening_evidence_sha256` | Hash of retained reconciliation evidence |
   | `pricing` | At most 32 exact `provider:model` entries |

   Each price entry requires `input_usd_per_million`,
   `output_usd_per_million`, `source_url` (HTTPS) and `source_sha256`.
   No sample balance, exchange rate or production model price is supplied here:
   those are reviewed evidence, not defaults.
6. From the exact released API runtime, with its authoritative database context,
   run the initializer. It makes no provider request:

   ```powershell
   .\.venv\Scripts\python.exe -m caseops_api.scripts.reconcile_ai_money_budget --policy-file C:\secure\reviewed-ai-policy.json
   ```

   The example path is a placeholder, not a file already created. On Cloud Run
   use the release-owned job/runtime and a securely mounted policy path instead
   of a workstation database. Do not print connection strings or keys.
7. Read back the month, cap, opening liability, admitted liability, evidence
   hashes and pricing keys using authorized read-only access. Exact replay is
   idempotent and cannot reset accumulated charges. A changed baseline, price,
   currency multiplier or cap is refused; investigate rather than editing the
   counter downward or deleting receipts.
8. Prove the missing-policy, unknown-price, exhaustion, concurrency, rollover and
   marker-denial cases with isolated deterministic tests. Automated production
   tests retain `X-CaseOps-Automated-Test: no-paid-providers`; they must not obtain
   a paid success to validate the balance.

## Exhaustion And Recovery

New paid work is refused while existing authorized work remains readable.
Switching providers does not replenish this balance. When this shared guard is
enabled, Gemini fallback calls are charged here as well as against the separate
Gemini-only cap described below.

Financial denial must not become a permanent source-data failure:

- Metadata, structured corpus backfill and statute enrichment stop submitting
  later work, drain only an already bounded concurrent window and return a
  nonzero operational status. Previously admitted results remain retained.
- Title embedding, ingestion and reembedding stop without deleting denied or
  unprocessed inputs. Remote HC/SC staging admits one owned batch per temp root;
  retained work blocks further staging rather than accumulating downloads.
  Exceptional run reload/commit also retains the owned staging slot; a missing
  summary is not evidence that pending files were consumed.
  Resume the retained PDFs with the local `--path` workflow after reconciliation;
  remove only confirmed-empty owned workdirs. Do not delete pending sources.
- A hearing-update summary waits 15 minutes after financial denial without
  consuming its transport retry allowance. Earlier uncertain attempts and money
  admissions remain charged. Stale or superseded claims cannot reschedule it.
- Compliance keeps valid deterministic items and exposes the optional AI phase
  as deferred, including its history and audit metadata. A completed deterministic
  run is not evidence that the AI phase completed.
- Predictive classification does not quarantine a valid source or erase its
  earlier accepted classifications solely because financial admission failed.
- Contract clause/obligation extraction, playbook comparison and party-clause
  extraction return the safe financial-denial detail without another financial
  retry. Earlier accepted clauses, obligations and rules remain unchanged.

These are candidate recovery contracts, not production acceptance receipts.

The contract-denial amendment does not change transaction ownership. The
pre-existing contract helper retains the caller transaction across provider I/O;
removing it safely requires separate post-provider access/source revalidation
and races before any model-run or generated-row persistence. Do not add a
rollback opt-in merely to make a denial test green or discard caller writes.

Missing reconciliation is not a transient provider outage. Repeated clicks or
an automatic retry cannot resolve it. Obtain current billing evidence, retain
the original receipts and investigate any mismatch. The initializer deliberately
does not implement arbitrary refunds or policy replacement. A reviewed correction
needs its own audited procedure and regression proof.

A new month does not automatically create a funded row. Reconcile it before
paid work resumes. Admissions and immediate dispatch checks use the IST period;
provider invoice periods and delayed billing may differ and still need account
reconciliation. A populated financial-table downgrade refuses to discard this
evidence. Roll back the application while retaining the additive schema instead.

After the guard's start month, a rollback must retain guarded adapters on every
paid executor. An older pre-guard API image, manual job or ingest VM can bypass
the ledger even while these tables remain present. If no verified guarded
rollback is available, stop paid dispatch at the provider/key boundary and
correct forward; do not certify a ceiling from the schema alone. Repin dormant
paid jobs before they can be invoked and rebuild the stopped ingest VM before
resuming it against production credentials.

## OpenAI Availability Fallback (Gemini 3.8 Flash)

Owner decision, 1 November 2026. When OpenAI's quota is exhausted
(`LLMQuotaExhaustedError`) or OpenAI is transiently unavailable
(`LLMTransientProviderError`), CaseOps may make **one** attempt per request on
`gemini-3.8-flash` through the managed Google Cloud endpoint (Vertex/Agent
Platform, ADC) in project `perfect-period-305406`, location `global`. An API key
or the free AI Studio API is never used. Gemini spend is capped at INR 10,000
(1,000,000 paise) per IST month by a Gemini-only ledger that does **not** depend
on the shared guard above, which stays off.

It is **off by default**. With `CASEOPS_LLM_FALLBACK_ENABLED` unset or `false`,
behaviour is identical to the OpenAI-only release.

### What switches, and what never does

- Switches: typed OpenAI quota exhaustion and transient unavailability only.
- Never switches: a refusal, schema or format failure, safety stop, tenant AI
  policy denial, the shared money guard or Gemini cap refusal, a daily cap, a
  configuration error, or the `X-CaseOps-Automated-Test: no-paid-providers`
  marker. The marker still blocks both providers before any SDK is built.
- One fallback attempt per provider instance, which is one per request or per
  job item. It must finish inside the primary call's existing worst-case
  deadline (per-attempt timeout x SDK attempts) and, on HTTP requests, inside
  the request deadline: the platform timeout (`CASEOPS_API_REQUEST_TIMEOUT_SECONDS`,
  120, the Cloud Run `--timeout`) minus a 20-second persistence margin. Gemini
  is not started with less than 30 seconds left; the OpenAI failure is reported
  instead, so no allowance is spent on an answer nobody receives.
- Recommendations: a healthy OpenAI call behaves exactly as with the fallback
  off (its normal 100-second timeout, no lineage requirement). Only after an
  OpenAI quota/availability failure does the plan check, in order: sources have
  revalidatable edition evidence, at least 30 seconds remain inside the
  100-second service budget, the tenant policy allows the fallback model, and
  current access/lifecycle/sources are unchanged. Gemini then gets only the
  remaining time. A policy that does not allow the model reports the OpenAI
  failure (no 403) and never fetches credentials.
- Gemini output goes through the same parsers and validators as OpenAI output
  (structured schema, citation verification, legal-safety checks).
- The tenant AI policy must allow `gemini-3.8-flash` for the purpose, or the
  fallback is withheld and the OpenAI failure is reported. A tenant whose
  allow-list for the purpose is empty allows every model, so its content goes
  to Google when the fallback runs. The check also applies through a cassette
  (record/replay) wrapper.
- When the fallback is refused (cap, ledger, shared guard), messages show the
  OpenAI failure and its own retry advice first, then "The monthly Gemini
  fallback allowance is used up. No external request was sent." with no retry
  advice after it.
- Each fallback that does not answer is logged without content: the error
  class, a category and the HTTP status only. Misconfigurations are logged at
  ERROR with `misconfigured=True`: `permission_denied` (API not enabled or
  missing `roles/aiplatform.user`), `model_or_location_not_found`, `credentials`
  (ADC), `client_configuration` and `configuration`.
- `ModelRun` rows record the provider and model that produced each output
  (`gemini` / `gemini-3.8-flash`); recommendations also keep
  `availability_fallback_used` and `provider_attempt_count` in the audit event.

Covered: drafting (and drafting preview), the workspace assistant,
recommendations and litigation strategy, contract intelligence (clauses,
obligations, playbook, party clauses), hearing packs, matter summary, matter
file Q&A, intelligent reviews, predictive classification, and the two job
paths: the case-tracking update summary (its drain
runs only in the full `caseops-document-worker` mode; the production
`caseops-document-processing` job runs `--documents-only` and
`caseops-court-sync` does not drain it) and compliance extraction run by the
document-processing job (its AI phase is itself off in production through
`CASEOPS_COMPLIANCE_AI_EXTRACTION_ENABLED=false`). So enabling the fallback on
the two jobs has no production effect until those switches change.

Deliberately not covered (`build_provider(..., availability_fallback=False)`):
authority metadata extraction (`caseops-extract-authority-metadata`), Layer-2
corpus enrichment, statute enrichment, placeholder-title re-extraction, the
evaluation scripts, legal-update summaries (public sources, not
customer-critical), the LLM reranker and query translation. Corpus enrichment
must stay on its reviewed OpenAI path and the 4.8+/5 per-bucket probe; a corpus
sweep would also spend the account-wide INR 10,000 in one run and leave nothing
for lawyers. When OpenAI is out of quota these jobs stop exactly as before.

### Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `CASEOPS_LLM_FALLBACK_ENABLED` | `false` | Turns the fallback on. Requires an OpenAI primary. |
| `CASEOPS_LLM_GEMINI_PROJECT` | unset | Required when enabled; settings validation fails closed without it. |
| `CASEOPS_LLM_FALLBACK_MODEL` | `gemini-3.8-flash` | Pinned; any other value fails validation. |
| `CASEOPS_LLM_GEMINI_LOCATION` | `global` | Pinned. |
| `CASEOPS_API_REQUEST_TIMEOUT_SECONDS` | `120` | Must equal the Cloud Run request timeout (`API_TIMEOUT_SECONDS` in `scripts/deploy-prod.sh`; a test pins the two together). |

The former `CASEOPS_LLM_RECOMMENDATION_FALLBACK_ENABLED` and
`CASEOPS_LLM_RECOMMENDATION_FALLBACK_MODEL` settings are retired and ignored.

### Model availability (checked 2026-11-01)

The owner first chose `gemini-3.6-flash`, then switched to `gemini-3.8-flash`
the same day because the 3.6 model page lists its retirement on
19 November 2026.

The [Agent Platform model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash)
(last updated 2026-10-30) lists `gemini-3.8-flash` as GA, released
2 September 2026, retirement "2 September 2027 or later", served from `global`
and the `us` and `eu` multi-regions only (Standard PayGo and Provisioned
Throughput). No India region is listed, so `global` stays; this is not
India-only processing: client content sent to the fallback may be processed
in any Google region worldwide, and Google is an added subprocessor. Maximum
output is 65,536 tokens.

The [developer guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-3-8-flash)
(last updated 2026-10-30) gives the same request rules CaseOps already applied
to the Gemini 3 family: temperature, top-k and top-p are ignored (CaseOps does
not send them); a history ending in a model turn (prefill) is rejected (CaseOps
refuses it before reserving spend); empty turns are dropped; `thinking_level`
accepts `LOW`, `MEDIUM` (default) and `HIGH`, and `MINIMAL` is a validation
error (CaseOps sends `LOW`); `frequency_penalty`, `presence_penalty` and
`candidate_count` are errors (CaseOps sends none). Changing the pinned model
again is an owner decision and a code change (`llm_fallback_model`, the price
table in `services/gemini_spend_cap.py`, tests).

### The Gemini cap

`services/gemini_spend_cap.py`, tables `ai_gemini_spend_months` and
`ai_gemini_spend_admissions` (migration `20261101_0002`):

- One account-level row per IST month, created on first use with zero opening
  liability and a 1,000,000-paise limit (owner-authorized fresh Gemini spend).
- The cap covers only the pinned fallback model (`gemini-3.8-flash`); another
  Gemini model used for evaluation is outside it. Before every transport of
  that model, after the shared guard's own checks and immediately before the
  HTTP call, the worst-case cost is committed in its own transaction with a row
  lock and a compare-and-set update; a reservation
  that would exceed the limit is refused with: "The monthly Gemini fallback
  allowance is used up. No external request was sent." The user then sees the
  OpenAI failure's safe message followed by that sentence.
- Admissions are content-free: month, model, paise, time. No tenant, matter,
  user, prompt or output. Nothing is refunded. Credential (ADC) and client
  configuration failures happen before the reservation, so they cost nothing.
  An HTTP error from Google (for example 403 or 404) happens after the
  reservation and keeps it: Google says it charges only for 200 responses, but
  the ledger treats every sent request as uncertain and never refunds.
- Pricing, pinned in code: USD 1.50 input / USD 7.50 output per 1M tokens, the
  standard global Standard-PayGo price from
  https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing
  (checked 2026-11-01). The introductory USD 0.75 / 3.75 that runs to
  31 December 2026 is deliberately not used. Output includes thinking tokens.
- Currency: a reviewed all-in multiplier of INR 110.0 per USD: an assumed
  market-rate ceiling of about INR 88 x 1.18 (18% GST on Google Cloud services)
  = about INR 104, plus about 6% for card/bank FX fees and rate movement.
  Revisit it if the market rate exceeds about INR 88. It is a constant; change
  it only in a reviewed commit.
- Bounds: input by UTF-8 request bytes plus 4,096 bytes of framing (always at
  least the token count), output by the effective `max_output_tokens`, which
  includes thinking. CaseOps requests low thinking for this model. Example: a
  10,000-byte request with an 8,192-token cap reserves 841 paise (INR 8.41).

Read-only check of the month (authorized database access):

```sql
SELECT month, limit_minor, admitted_minor FROM ai_gemini_spend_months ORDER BY month;
SELECT month, model, count(*), sum(upper_bound_minor)
FROM ai_gemini_spend_admissions GROUP BY month, model ORDER BY month;
```

To stop Gemini spend for the rest of a month, set
`CASEOPS_LLM_FALLBACK_ENABLED=false`. Do not edit or delete admissions.

## GCP Guard Rail For The Gemini Fallback (operator-run)

These commands are for the owner. They were written, not run, with this change.
Both the API service and every job run as
`caseops-runtime@perfect-period-305406.iam.gserviceaccount.com`
(`scripts/deploy-prod.sh`, `infra/cloudrun/scheduler-inventory.json`).

1. Enable the managed endpoint:

   ```bash
   gcloud services enable aiplatform.googleapis.com --project perfect-period-305406
   ```

2. Grant Vertex AI use to the runtime identity (API and jobs share it):

   ```bash
   gcloud projects add-iam-policy-binding perfect-period-305406 \
     --member "serviceAccount:caseops-runtime@perfect-period-305406.iam.gserviceaccount.com" \
     --role roles/aiplatform.user --condition=None
   ```

3. Create a Cloud Billing budget of INR 10,000 with alerts. Budgets alert; they
   do not stop spend (the CaseOps ledger does). The amount's currency must match
   the billing account's currency.

   ```bash
   BILLING_ACCOUNT=$(gcloud billing projects describe perfect-period-305406 \
     --format='value(billingAccountName)' | sed 's#billingAccounts/##')
   # Find the Vertex AI / Agent Platform billing service id (read-only):
   curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
     "https://cloudbilling.googleapis.com/v1/services?pageSize=5000" \
     | jq -r '.services[] | select(.displayName | test("Vertex|Agent Platform"; "i")) | "\(.name) \(.displayName)"'
   VERTEX_SERVICE=services/REPLACE_WITH_ID_FROM_ABOVE
   gcloud billing budgets create \
     --billing-account "${BILLING_ACCOUNT}" \
     --display-name "CaseOps Gemini fallback INR 10000 monthly" \
     --budget-amount 10000INR \
     --calendar-period month \
     --filter-projects projects/perfect-period-305406 \
     --filter-services "${VERTEX_SERVICE}" \
     --threshold-rule percent=0.5 \
     --threshold-rule percent=0.75 \
     --threshold-rule percent=0.9 \
     --threshold-rule percent=1.0 \
     --threshold-rule percent=1.0,basis=forecasted-spend
   ```

4. Turn the fallback on.

   - `caseops-api` (releases use `--update-env-vars`, which keeps these values;
     the release readback does not check them, so read them back yourself):

     ```bash
     gcloud run services update caseops-api --region asia-south1 \
       --project perfect-period-305406 \
       --update-env-vars CASEOPS_LLM_FALLBACK_ENABLED=true,CASEOPS_LLM_GEMINI_PROJECT=perfect-period-305406
     ```

   - `caseops-document-processing` and `caseops-court-sync`: their environment
     is owned by `infra/cloudrun/scheduler-inventory.json` and is reset to it,
     exactly, on every release; a manual `gcloud run jobs update` would be
     reverted. Add `"CASEOPS_LLM_FALLBACK_ENABLED": "true"` and
     `"CASEOPS_LLM_GEMINI_PROJECT": "perfect-period-305406"` to both jobs'
     `bootstrap.environment` in a reviewed commit (update
     `apps/api/tests/test_scheduler_inventory.py` if it pins the map) and
     release it.
   - `caseops-extract-authority-metadata`: leave unset. The code never uses the
     fallback for authority metadata extraction, so the setting has no effect.

   `scripts/deploy-prod.sh` was not changed: with no setting present the
   fallback stays off, and nothing in the release enables it.

5. Verify without paid calls:

   ```bash
   gcloud services list --enabled --project perfect-period-305406 \
     --filter "config.name=aiplatform.googleapis.com" --format "value(config.name)"
   gcloud projects get-iam-policy perfect-period-305406 --flatten bindings \
     --filter "bindings.role=roles/aiplatform.user" --format "value(bindings.members)"
   gcloud run services describe caseops-api --region asia-south1 \
     --project perfect-period-305406 --format json \
     | jq '.spec.template.spec.containers[0].env[] | select(.name | startswith("CASEOPS_LLM_"))'
   gcloud billing budgets list --billing-account "${BILLING_ACCOUNT}" \
     --format "table(displayName,amount.specifiedAmount)"
   ```

   Automated production checks keep `X-CaseOps-Automated-Test: no-paid-providers`;
   they must show `ModelRun.provider = mock` and leave `ai_gemini_spend_admissions`
   unchanged. Do not force an OpenAI outage or send a paid Gemini probe to prove
   the switch; the offline tests cover it. The first real fallback will show as
   a `gemini` / `gemini-3.8-flash` `ModelRun` and one admission row.

Rollback: `gcloud run services update caseops-api --region asia-south1
--project perfect-period-305406 --update-env-vars CASEOPS_LLM_FALLBACK_ENABLED=false`
and revert the inventory change for the jobs. Keep the ledger tables.

Background: see [the dated assessment](../AI_PROVIDER_BUDGET_GEMINI_ASSESSMENT_2026-10-11.md).
Managed endpoint access, regional processing, retention, strict output, legal
quality and cost parity remain separate acceptance gates. Never replace a paid
fallback with a free tier that has unreviewed client-data terms.
