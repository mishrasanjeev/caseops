# OCR & Translate: provider enablement and live verification

Feature: Matter Documents "OCR & Translate" (PRD J04/J16, M03/M17, US-048,
US-049, US-066; tests FT-105..FT-110, NFT-025, SEC-025, SEC-033). Code ships disabled. This
runbook covers the steps to turn it on and the proof each step needs.

## What runs where

| Step | Runs | External call |
| --- | --- | --- |
| Inspect PDF pages for a usable text layer | document worker | none |
| OCR of pages without a usable text layer | document worker | Sarvam Document AI Parse API (`api.sarvam.ai`), batches of at most 20 pages |
| Translation of extracted paragraphs | document worker | Google Cloud Translation v3 `translateText`, model `general/translation-llm` |
| Translated PDF | document worker | none (stored in the existing document storage) |

The API only records and queues requests (`matter_attachment_ocr` and
`matter_attachment_translation` jobs on `document_processing_jobs`). In
production the `caseops-document-processing` Cloud Run job drains them through
the existing dispatch and cadence scheduler. A long OCR run that outlasts one
job lease saves its Sarvam job ids and queues a `resume` job, which the cadence
scheduler picks up. It never resubmits.

## Settings (server-side only)

| Setting | Alias accepted | Default | Notes |
| --- | --- | --- | --- |
| `CASEOPS_SARVAM_DOCUMENT_AI_ENABLED` | none | `false` | Kill switch |
| `CASEOPS_SARVAM_API_KEY` | `SARVAM_API_KEY` | empty | Secret Manager only |
| `CASEOPS_GOOGLE_TRANSLATION_ENABLED` | none | `false` | Kill switch |
| `CASEOPS_GOOGLE_TRANSLATION_PROJECT_ID` | `GOOGLE_CLOUD_PROJECT_ID` | falls back to `CASEOPS_GCP_PROJECT_ID` | |
| `CASEOPS_GOOGLE_TRANSLATION_LOCATION` | `GOOGLE_CLOUD_LOCATION` | `us-central1` | Must be a region where Translation LLM is offered |

Google auth uses Application Default Credentials. The Cloud Run runtime service
account authenticates through workload identity, so no key file is needed. Do
not create a service-account key.

## Enablement steps (owner-run)

1. Enable the API: `gcloud services enable translate.googleapis.com --project <project>`.
2. Grant the runtime service account `roles/cloudtranslate.user` on the project.
3. Create the secret `caseops-sarvam-api-key` in Secret Manager. Grant the
   runtime service account `roles/secretmanager.secretAccessor` on it.
4. Bind the secret and settings to both the API service and the
   `caseops-document-processing` job. The worker makes the provider calls; the
   API only reports readiness. `scripts/deploy-prod.sh` does not bind these yet
   on purpose: binding a secret that does not exist would break every release.
   Add `CASEOPS_SARVAM_API_KEY=caseops-sarvam-api-key:latest` to the
   `--update-secrets` lists. Add the enable flags, project and location to
   `--update-env-vars`. Add matching readback assertions in the same change.
5. Record verified prices as provider cost profiles (Admin, Provider costs):
   - category `ocr_page`, provider `sarvam`, unit = INR minor units per page,
     cost basis `actual`, confidence `high`, source URL and evidence ref.
   - category `translation_characters`, provider `google-translation`,
     unit = INR minor units per 1,000 source characters, same evidence rules.
   Without these, readiness reports `cost_not_verified` and no paid call is made.
6. Confirm workspace provider budgets in Billing. OCR and translation reserve
   against the shared paid-provider budget scope.

## Live verification (needs real credentials; never with client documents)

Use a non-confidential test document that you own: a public judgment PDF, and a
scanned page you created yourself. Do not run this check on a QA tenant.
Automated or no-paid requests are blocked by design.

1. As a signed-in human, open a matter, then Documents. Open OCR & Translate on
   the scanned PDF, choose source Hindi and target English, and start.
2. Expect these states in order: OCR processing, then OCR completed (or Review
   required), then Translation processing, then Translation completed (or
   Review required). Pages that already had a text layer show "Text layer" and
   cost nothing.
3. Open Versions. Compare the original with the OCR text and the translation.
   Download the translated PDF. Mark the translation reviewed (requires
   `documents:manage`).
4. Record the Sarvam job id from `provider_jobs_json`, the Google model string
   on the version, the provider spend rows (settled), and the matching audit
   events (`matter_attachment.ocr_*`, `matter_attachment.translation_*`).

Until a real successful call has been recorded this way, the live integration
is unverified. This holds even though mocked contract tests pass. The Sarvam
per-page JSON layout is not published, and the parser reads it defensively: if
a live run reports `provider_page_missing` for pages that Sarvam did read,
capture the output ZIP layout (without content) and adjust
`parse_output_archive`.

## Rollback

Set either kill switch to `false`. Queued runs then fail with a clear reason,
and stored OCR text, translations and PDFs stay readable.
