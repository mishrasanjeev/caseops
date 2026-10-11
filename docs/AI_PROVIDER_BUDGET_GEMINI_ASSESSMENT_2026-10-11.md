# AI Provider Budget And Gemini Assessment

## Owner Instructions

Updated 11 October 2026. The latest instruction supersedes the earlier INR 5,000
limit and the temporary instruction to pause paid AI:

- Keep October's existing service and spending behavior running.
- Use INR 10,000 per month for the new policy, shared across paid AI providers.
- Assess a full Gemini generation migration and a lower-cost fallback.
- Do not identify a model in the public buyer-facing article.

No production provider configuration or billing limit has been changed by this
assessment. Local source changes are not deployment or model-quality evidence.
The source budget gate starts in November 2026, preserving the October exception.
Release and activation evidence remains required.

## Recommendation

Evaluate **Gemini 3.1 Flash-Lite through Google Cloud's managed endpoint** as the
first Gemini candidate. Google lists it as generally available, with structured
output and configurable thinking. That makes it a reasonable cost-sensitive
candidate, not a certification that its legal answers are correct.

The model page lists global/US/EU availability, not `asia-south1`. The CaseOps
deployment region does not establish the model's processing location. Review
processing, retention, contractual and tenant requirements before sending private
legal records. Google's managed service states that it does not train models on
customer data without permission, but abuse monitoring and other retention
conditions still need review. Do not substitute an unpaid AI Studio account for
this decision or assume zero retention.

### Price Comparison

Official published standard text rates checked on 11 October 2026:

| Candidate | USD / 1M input tokens | USD / 1M output tokens | Illustrative 10K input + 2K total output |
| --- | ---: | ---: | ---: |
| GPT-6 Luna, short context | 0.10 | 0.50 | USD 0.0020 |
| Gemini 3.1 Flash-Lite, global | 0.25 | 1.50 | USD 0.0055 |

This illustration is arithmetic, not an observed legal request or an INR bill.
Output includes billable reasoning, not only visible text. Cache, regional,
priority, long-context, tool, retry, embedding, tax and exchange costs can differ.
On these published text rates, the Gemini candidate is **not cheaper** than Luna.
Do not recommend a provider switch on an unsupported cost-saving claim.

Google Cloud metadata inspection found `generativelanguage.googleapis.com`
enabled in `perfect-period-305406`; it did not find `aiplatform.googleapis.com`
enabled. No API was enabled, IAM role granted or model invoked during that check.
Developer API availability is not proof of managed-endpoint access or consent.

## Fallback And The Total Ceiling

A paid fallback cannot make an exhausted INR 10,000 budget free. A workable
allocation would reserve part of that same total for fallback, for example
INR 8,000 primary and INR 2,000 fallback. Both must consume one account ledger,
including retries, embeddings and system/corpus work. This allocation is a
proposal, not a deployed routing policy. Once the whole allowance is exhausted,
new paid generation stops while existing authorized records remain readable.

Google now documents service-scoped spend-cap budgets, but enforcement is not
instant and overages remain billable. Such a cap is defense in depth, not a
replacement for pre-call reservations. Do not cap Cloud Run to control AI costs:
that could stop the product rather than only the model service. Other hosting
and court-data costs are outside this AI-provider allowance.

## Acceptance Before A Migration

1. Pin the exact endpoint/model, region, terms, IAM and secret/ADC configuration.
2. Use native structured output and validate every nested response contract.
3. Compare against retained, authorized, hash-verified representative evidence:
   forum/authority/remedy/next-step recommendations, weak/contrary sources,
   refusal, prompt injection, lifecycle disposal and access revocation.
4. Require correct source identities, quotations and option-level citations;
   do not treat valid JSON or provider HTTP 200 as correct legal reasoning.
5. Bound total latency and SDK retries, with no database transaction or parent
   lock held over provider transport. Charge every fallback and rejected output.
6. Replay local Docker and the complete dated Playwright inventory. Automated
   suites retain the no-paid-provider marker and deterministic emulators.
7. Use a reviewed human-generated production receipt for actual model-quality
   evidence; offline mocks cannot certify a new paid provider's legal quality.
8. Merge only after green CI; deploy canonical exact main and recheck API/web
   identities and the same live journeys. Keep external dependencies open.

Do not replace the production Voyage vector pipeline just by changing the
generation provider. Existing vector dimensions, corpus provenance, reranking
and the PRD retrieval benchmark remain independently required.

## Source References

- [Google model capabilities and regions](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-lite)
- [Google Cloud managed-model pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)
- [Google managed-service data retention](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention)
- [Google spend caps and their limitations](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- [OpenAI spend-limit enforcement](https://developers.openai.com/api/docs/guides/spend-limits)
- [Voyage pricing](https://docs.voyageai.com/docs/pricing)

PRD mapping: `J09/M07/US-026-028/FT-034-036`, `J14/M14/SEC-011-014`;
public content belongs to `J19/M21/US-063`.
