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

Production: project `perfect-period-305406`, region `asia-south1`, runtime
service account `caseops-runtime@perfect-period-305406.iam.gserviceaccount.com`.

### A. Sarvam API key (OCR)

The key must reach two places. The `caseops-api` service needs it to report OCR
as available; without it the dialog says scanned pages will be listed as unread.
The `caseops-document-processing` job needs it because it makes the Sarvam
calls.

1. Create a key in the Sarvam AI dashboard (API keys) under the company account.
   Treat it as a production credential: do not paste it into chat, tickets,
   `.env` files or shell history.
2. Store it in Secret Manager as `caseops-sarvam-api-key`, **with no trailing
   newline**. The value is sent as the `api-subscription-key` header without
   trimming, and a newline makes every request fail. Either paste it in the
   Cloud Console (Secret Manager, Create secret), or from PowerShell:

   ```powershell
   gcloud secrets create caseops-sarvam-api-key --replication-policy=automatic --project perfect-period-305406
   $secure = Read-Host "Sarvam API key" -AsSecureString
   $tmp = New-TemporaryFile
   [IO.File]::WriteAllText($tmp.FullName, [Net.NetworkCredential]::new("", $secure).Password.Trim())
   gcloud secrets versions add caseops-sarvam-api-key --data-file="$($tmp.FullName)" --project perfect-period-305406
   Remove-Item $tmp; Remove-Variable secure
   ```

3. Let the runtime service account read it:

   ```powershell
   gcloud secrets add-iam-policy-binding caseops-sarvam-api-key --member "serviceAccount:caseops-runtime@perfect-period-305406.iam.gserviceaccount.com" --role roles/secretmanager.secretAccessor --project perfect-period-305406
   ```

4. Confirm the version is enabled and is exactly the key length (no newline):

   ```powershell
   gcloud secrets versions describe latest --secret caseops-sarvam-api-key --project perfect-period-305406 --format "value(state)"
   (gcloud secrets versions access latest --secret caseops-sarvam-api-key --project perfect-period-305406).Length
   ```

5. Merge the deploy-contract binding change to `main` **only after steps 2
   to 4 and B.1 to B.2 are done**. Do not bind anything by hand with
   `gcloud run ... update`: every release re-applies the job contract with
   `--set-secrets`, which would erase a manual binding on the job. The change
   binds:
   - `infra/cloudrun/scheduler-inventory.json`, job
     `caseops-document-processing`, `bootstrap`:
     `CASEOPS_SARVAM_API_KEY=caseops-sarvam-api-key:latest` in `secrets`;
     `CASEOPS_SARVAM_DOCUMENT_AI_ENABLED=true`,
     `CASEOPS_GOOGLE_TRANSLATION_ENABLED=true` and
     `CASEOPS_GOOGLE_TRANSLATION_LOCATION=us-central1` in `environment`.
   - `scripts/deploy-prod.sh`, `caseops-api` deploy: the same secret in
     `--update-secrets` and the same three settings in `--update-env-vars`.
     The service readback fails the release unless the secret is bound to
     `caseops-sarvam-api-key` at `latest` and the three settings match.
   - A read-only preflight, before any build or migration, refuses the
     release (exit 2) unless `caseops-sarvam-api-key` has an `ENABLED`
     latest version. A release can therefore not half-apply because the
     secret is missing.
6. Record the Sarvam price as a cost profile (step C). Until then readiness
   reports `cost_not_verified` and no Sarvam call is made.
7. Release from `main`, then check the readback on both targets:

   ```powershell
   gcloud run services describe caseops-api --region asia-south1 --project perfect-period-305406 --format json | Select-String -Context 0,5 CASEOPS_SARVAM
   gcloud run jobs describe caseops-document-processing --region asia-south1 --project perfect-period-305406 --format json | Select-String -Context 0,5 CASEOPS_SARVAM
   ```

   Each should show the enable flag and a `secretKeyRef` to
   `caseops-sarvam-api-key`. Then run the live verification below.

Rotation: add a new secret version and disable the old one. Both targets read
`latest`; new job executions pick the key up at once, and the API picks it up
on its next revision. Revocation: set `CASEOPS_SARVAM_DOCUMENT_AI_ENABLED=false`
(see Rollback), then disable the secret version and the key in the dashboard.

### B. Google Cloud Translation

1. Enable the API: `gcloud services enable translate.googleapis.com --project perfect-period-305406`.
2. Grant the runtime service account `roles/cloudtranslate.user` on the project.
3. `CASEOPS_GOOGLE_TRANSLATION_ENABLED=true` and
   `CASEOPS_GOOGLE_TRANSLATION_LOCATION=us-central1` are bound by the same
   change as A.5, with readback. The project falls back to
   `CASEOPS_GCP_PROJECT_ID`, which both targets already set. No secret is
   needed: Google auth uses the runtime service account. The release does not
   check that the API is enabled or the role is granted; if either is missing,
   translation runs fail with a Google permission error and no charge.
4. Data location: `us-central1` processes the extracted text in the United
   States. The owner confirmed on 2026-11-24 that this is acceptable for
   client documents. Changing the location needs the same confirmation and a
   region where Translation LLM is offered.

### C. Cost profiles and budgets

1. Record verified prices as provider cost profiles (Admin, Provider costs):
   - category `ocr_page`, provider `sarvam`, unit = INR minor units per page,
     cost basis `actual`, confidence `high`, source URL and evidence ref.
   - category `translation_characters`, provider `google-translation`,
     unit = INR minor units per 1,000 source characters, same evidence rules.
   Without these, readiness reports `cost_not_verified` and no paid call is made.
2. Confirm workspace provider budgets in Billing. OCR and translation reserve
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
