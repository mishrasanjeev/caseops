# Shared AI Spending Reconciliation

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
Switching providers does not replenish this balance. A prospective primary and
fallback allocation must fit **inside** INR 10,000; no allocation or automatic
fallback has been deployed by this candidate.

Financial denial must not become a permanent source-data failure:

- Metadata, structured corpus backfill and statute enrichment stop submitting
  later work, drain only an already bounded concurrent window and return a
  nonzero operational status. Previously admitted results remain retained.
- Title embedding, ingestion and reembedding stop without deleting denied or
  unprocessed inputs. Remote HC/SC staging admits one owned batch per temp root;
  retained work blocks further staging rather than accumulating downloads.
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

These are candidate recovery contracts, not production acceptance receipts.

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

## Gemini Evaluation

See [the dated assessment](../AI_PROVIDER_BUDGET_GEMINI_ASSESSMENT_2026-10-11.md).
Managed endpoint access, regional processing, retention, strict output, legal
quality and cost parity remain separate acceptance gates. Never replace a paid
fallback with a free tier that has unreviewed client-data terms.
