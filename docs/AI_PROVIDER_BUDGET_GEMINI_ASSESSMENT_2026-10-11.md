# AI Provider Budget And Gemini Assessment

> Superseded in part on 1 November 2026: the owner chose a general OpenAI
> availability fallback to `gemini-3.8-flash` with its own INR 10,000 per IST
> month Gemini cap, independent of the shared guard. See
> [the AI spending runbook](runbooks/ai-spending-reconciliation.md).

## Owner Instructions

Updated 11 October 2026. The latest instruction supersedes the earlier INR 5,000
limit and the temporary instruction to pause paid AI:

- Keep October's existing service and spending behavior running.
- Use INR 10,000 per month for the new policy, shared across paid AI providers.
- Select exactly `gemini-3.5-flash-lite` for the proposed Gemini fallback.
- Promote it to primary only if a comparative legal benchmark proves it better
  than GPT-6 Luna; no such result is available here.
- Do not identify a model in the public buyer-facing article.

No production provider configuration or billing limit has been changed by this
assessment. Local source changes are not deployment or model-quality evidence.
The source budget gate starts in November 2026, preserving the October exception.
Release and activation evidence remains required.

## Selected Fallback, Not A New Primary

The owner's exact choice is **`gemini-3.5-flash-lite` through Google Cloud's
managed endpoint**. It supersedes this assessment's earlier proposal to evaluate
3.1 first. The release owner is implementing a **recommendations-only, opt-in
availability fallback**, disabled until reviewed runtime configuration is
established. The plan is eligible only from November 2026 (IST), while the shared
money guard applies and is enabled, with explicit managed-project configuration.
October keeps its existing behavior. This candidate contract is not a configured
or deployed integration. Do not enable it for drafting, the assistant, embeddings
or corpus work by implication.

Google lists 3.5 Flash-Lite as GA from 21 July 2026, with GenerateContent,
structured output and system instructions. Those capabilities do not certify
legal correctness. [Google's managed model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite)
lists `global`, `us` and `eu`, not `asia-south1`; the CaseOps deployment region
does not establish where model processing occurs.

**Do not promote it to primary.** No retained like-for-like legal benchmark
establishes superiority over Luna. Luna is the comparison target, not a claim
that production currently serves it. October's existing primary and behavior
remain unchanged; a later promotion requires comparative evidence and the
normal release gates, not the model's release date or persuasive examples.

Do not start a managed Gemini 2.5 Flash-Lite migration: Google lists its
retirement on 20 October 2026. That managed-service date does not establish the
Developer API's retirement. Do not substitute a different Gemini model for the
selected fallback without a reviewed change.

Review processing, retention, contractual and tenant requirements before sending
private legal records. Google's managed service states that it does not train models on
customer data without permission, but abuse monitoring and other retention
conditions still need review. [Google's retention guidance](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention)
does not establish this project's approved configuration. **Never send private
legal data to a free Gemini/AI Studio API to evade the paid budget**, or assume
zero retention from an account being available.

### Price Comparison

Official published standard text rates checked on 11 October 2026, from
[OpenAI pricing](https://developers.openai.com/api/docs/pricing) and
[Google Cloud managed-model pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing):

| Candidate | USD / 1M input tokens | USD / 1M output tokens | Illustrative 10K input + 2K total output |
| --- | ---: | ---: | ---: |
| GPT-6 Luna, short context | 0.10 | 0.50 | USD 0.0020 |
| Gemini 3.5 Flash-Lite, selected fallback, global | 0.30 | 2.50 | USD 0.0080 |

This illustration is arithmetic, not an observed legal request or an INR bill.
Output includes billable reasoning, not only visible text. Cache, regional,
priority, long-context, tool, retry, embedding, tax and exchange costs can differ.
On these published text rates, the selected Gemini fallback is **not cheaper**
than Luna. Do not recommend a provider switch on an unsupported cost-saving claim.

Google Cloud metadata inspection found `generativelanguage.googleapis.com`
enabled in `perfect-period-305406`; it did not find `aiplatform.googleapis.com`
enabled. No API was enabled, IAM role granted or model invoked during that check.
Developer API availability is not proof of managed-endpoint access or consent.
This is an earlier read-only finding, not a fresh runtime verification by this
documentation update. Effective API flags, billed-project access, service-account
IAM/ADC, endpoint location, privacy/retention policy and live activation remain
open until the release owner supplies evidence. Owner confirmation of global
processing location and retention is pending, with no reply to the Google global
endpoint authorization request. Keep
`CASEOPS_LLM_RECOMMENDATION_FALLBACK_ENABLED=false`; November's arrival does not
activate fallback automatically. Do not treat the request for confirmation as
approval. No API or IAM changes were made by this documentation update.

### Exact Candidate Configuration

These server-side settings define the candidate contract, not observed production
values or instructions to activate it now:

| Variable | Candidate value and requirement |
| --- | --- |
| `CASEOPS_LLM_RECOMMENDATION_FALLBACK_ENABLED` | `false` by default; runtime fallback remains off pending reviewed activation. |
| `CASEOPS_LLM_RECOMMENDATION_FALLBACK_MODEL` | Pinned to `gemini-3.5-flash-lite`. |
| `CASEOPS_LLM_GEMINI_PROJECT` | Explicit managed Google Cloud project required only when opting in; it does not establish API, billing or IAM readiness by itself. |
| `CASEOPS_LLM_GEMINI_LOCATION` | Pinned to `global`; owner location/retention confirmation remains pending. |

The plan also requires the applicable enabled November-or-later money guard,
funded shared admission and current request authorization. A configuration flag
alone cannot satisfy those requirements or waive the no-paid-provider marker.

### 3.5 Request Compatibility

Use native GenerateContent JSON-schema output and system instructions, with
CaseOps' nested-schema and legal-safety validation still enforced. Do not rely
on a free-form JSON prompt or a final model-role prefill to force the format.
[Google's migration guidance](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.6#api-changes-and-parameter-updates)
requires omitting `temperature`, `top_p` and `top_k`: these deprecated settings
are ignored for 3.5 and may error in future generations. A final nonempty
`model` turn is rejected with HTTP 400. SDK compatibility, actual emitted payloads,
native schema behavior, refusal handling and bounded deadlines must be tested;
the existing Gemini adapter alone is not that proof.

## Fallback And The Total Ceiling

A paid fallback cannot make an exhausted INR 10,000 budget free. A workable
allocation would reserve part of that same total for fallback, for example
INR 8,000 primary and INR 2,000 fallback. Both must consume one account ledger,
including retries, embeddings and system/corpus work. This allocation is a
proposal, not a deployed routing policy. Once the whole allowance is exhausted,
new paid generation stops while existing authorized records remain readable.

Fallback eligibility is typed and limited to a primary network timeout or
connection failure, or HTTP **408, 429 without quota/credit exhaustion, 500, 502,
503 or 504**. **Upstream quota or credit exhaustion never triggers this
implemented fallback**, including a quota-bearing HTTP 429. A successful HTTP
response with invalid output is not an availability failure.

Authentication, configuration, financial admission, the no-paid-provider marker,
tenant policy, access/lifecycle/source denial, schema/content rejection and
legal-safety refusal are not fallback-eligible and remain fail-closed. Do not
send refused or malformed output to another model to make it pass. Charge each
attempt, including rejected outputs, against the same applicable monthly policy.

### Shared Attempt And Deadline Bounds

The candidate routing plan permits **at most two total provider attempts** for
one recommendation request, shared with existing bounded format/safety repair.
Repair does not grant a separate retry allowance; after it consumes the second
attempt there is no fallback attempt left. After primary plus fallback there is
no third attempt, even for output repair. Provider SDK retries are **zero**.

One **100-second deadline starts before retrieval**, not at the first SDK call.
Each primary attempt is limited to **45 seconds** and each fallback attempt to
**40 seconds**, clipped to the remaining deadline. Retrieval and preflight time
therefore reduce the available provider time. These are candidate routing bounds,
not an end-to-end latency acceptance result or an authorization to retry a
failed browser mutation.

The amendment applies the remaining allowance to credential discovery/refresh,
provider construction, serialization, financial admission, dispatch and result
return. Managed authentication uses bounded public transport and a token-only
SDK credential; an expired attempt cannot acquire hidden refresh retries.
Admission already recorded is not refunded merely because dispatch or the
response misses its deadline. These checks do not forcibly preempt synchronous
local work and are not live end-to-end latency certification.

Source integrity also spans both attempts: capture the original retrieved
edition, displayed metadata and excerpt hashes, compare bounded current source
bytes, and retain parent/child locks through final persistence. Changed,
withdrawn, missing or oversized evidence prevents another disclosure or saved
output. No request transaction is held across provider transport.

Google now documents service-scoped spend-cap budgets, but enforcement is not
instant and overages remain billable. Such a cap is defense in depth, not a
replacement for pre-call reservations. Do not cap Cloud Run to control AI costs:
that could stop the product rather than only the model service. Other hosting
and court-data costs are outside this AI-provider allowance.

## Acceptance Before A Migration

1. Pin `gemini-3.5-flash-lite`, the managed endpoint/location, terms, billed
   project and least-privilege IAM/ADC configuration. Keep fallback opt-in off
   until reviewed runtime evidence is present; preserve October's primary.
2. Use native structured output and validate every nested response contract.
3. Compare Luna and the selected fallback against the same retained, authorized,
   hash-verified representative evidence:
   forum/authority/remedy/next-step recommendations, weak/contrary sources,
   refusal, prompt injection, lifecycle disposal and access revocation.
4. Require correct source identities, quotations and option-level citations;
   do not treat valid JSON or provider HTTP 200 as correct legal reasoning.
5. Prove the shared two-attempt maximum, zero SDK retries and 45/40-second
   per-attempt limits within the remaining pre-retrieval 100-second deadline,
   with no database transaction or parent lock held over provider transport.
   Charge every fallback and rejected output; never add a third repair attempt.
6. Replay local Docker and the complete dated Playwright inventory. Automated
   suites retain the no-paid-provider marker and deterministic emulators.
7. Retain reviewed human-generated receipts, exact model/configuration, measured
   latency/cost and reviewer findings for actual legal-quality evidence. Offline
   mocks cannot establish superiority or certify a paid provider's legal quality.
8. Merge only after green CI; deploy canonical exact main and recheck API/web
   identities and the same live journeys. Keep external dependencies open.

Do not replace the production Voyage vector pipeline just by changing the
generation provider. Existing vector dimensions, corpus provenance, reranking
and the PRD retrieval benchmark remain independently required.

## Release Evidence Checkpoint

The release owner's checkpoint records that the full Docker R3 gate on
`5a66c0910c0d0c6243b18ceb2446a1f23c843fcf` was intentionally interrupted for
this fallback scope change. It is **incomplete**, not accepted. The earlier 26
public-content Playwright passes and scoped green suites apply only to their
recorded candidate and inventory; they prove neither the new fallback nor
production deployment. Fresh amended Docker, CI, canonical-main deployment and
exact-serving-revision replay remain required. See the
[release ledger](runbooks/AI_BUDGET_RELEASE_2026-10-11.md); this document changes
no runtime configuration and invokes no paid provider.

The later `67fab368` PostgreSQL CI failed four fake-route cases because its
isolated client correctly retains the no-paid marker. Corrected offline human
emulation preserves that marker and the real native spending guards. R4 was
also deliberately interrupted for source-integrity/deadline amendments; it has
no completion event. Neither the earlier CI nor scoped passes supersede a full
failed/interrupted gate. Current proof is tracked in the linked release ledger.

## Source References

- [Selected Google 3.5 model capabilities, GA date and regions](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite)
- [Google 3.5 request compatibility changes](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.6#api-changes-and-parameter-updates)
- [Google managed-model lifecycle](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions)
- [Google 2.5 Flash-Lite retirement](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/2-5-flash-lite)
- [Google Cloud managed-model pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)
- [Google managed-service data retention](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention)
- [Google spend caps and their limitations](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- [OpenAI spend-limit enforcement](https://developers.openai.com/api/docs/guides/spend-limits)
- [Voyage pricing](https://docs.voyageai.com/docs/pricing)

PRD mapping: `J09/M07/US-026-028/FT-034-036`, `J14/M14/SEC-011-014`;
public content belongs to `J19/M21/US-063`.
