# CaseOps provider setup and verified state (24 September 2026)

This is an operator checklist, not a claim that a configured credential has
completed a live transaction. Production project: `perfect-period-305406`,
region: `asia-south1`, API service: `caseops-api`. Keep credentials in Google
Secret Manager, never in Git, a workbook, a browser variable, or a test log.
Automated tests and the persistent `test-legal` tenant must not make paid
provider calls. Use the existing no-paid-provider marker and deterministic
emulators for regression tests.

## 1. Current inventory

| Provider or facility | Observed production configuration | What is still required |
| --- | --- | --- |
| Google Cloud Run, Cloud SQL, GCS, Secret Manager, Scheduler | In use by CaseOps. The document bucket is `caseops-prod-documents`. | Continue exact-main release, backup, budget, and health checks. |
| Google Workspace APIs | Gmail, Calendar (`calendar-json.googleapis.com`), Pub/Sub, Secret Manager were enabled; **Drive API was enabled and rechecked on 24 September 2026**. | Google Auth Platform OAuth web client, consent/scopes, tenant user connection; Gmail topic/subscription and verified webhook only when ready. API enablement alone does not activate a connector. |
| OpenAI | Cloud Run selects `openai` and `gpt-5.1`; an enabled Secret Manager key version is bound. | Verify account quota, spend limits, and a funded-human canary separately. Google Cloud is not a drop-in key replacement. |
| Voyage AI | Cloud Run selects `voyage`, `voyage-4-large`, 1,024 dimensions; an enabled key version is bound. | Verify billing, quality, and daily spend cap. Switching to Vertex embeddings would require reindexing and quality proof. |
| SendGrid | Sender and Secret Manager API/webhook key bindings present; hearing-reminder job enabled. | Confirm sender authentication, SendGrid event-webhook destination/signature, and delivery evidence. |
| eCourtsIndia | Case tracking enabled, token bound, scheduled polling configured. | Provider account/credit and support-matrix readiness, exact-match result and end-to-end hearing refresh evidence. Do not infer success from HTTP 200 or a configured token. |
| Indian Kanoon | Licensed adapter enabled, token and terms/budget metadata bound. | Recheck current terms, price profiles, prepaid balance, attribution and a funded-human result; automated verification remains read-only. |
| Pine Labs Plural | Payment-link and subscription switches are both **off**. | Merchant account, credentials, base URL, signed webhook, UAT and reviewed production activation. |
| Twilio SMS / Meta WhatsApp | Both disabled; required sender/template credentials are not bound. | Vendor account, approved sender/number or template, region/compliance requirements, signed delivery callbacks, spend limits. |
| Google Calendar / Gmail / Drive connectors | OAuth settings are **not** bound to the production API. | Complete section 2; user consent is required. Drive currently supports bounded metadata discovery, not automatic attachment import. |
| Microsoft 365 / Outlook | OAuth settings are not bound. | Entra app registration, tenant consent, redirect URI and secret; this is not supplied by Google Cloud. |
| IP India / WIPO registry | Adapter contracts are blocked pending licensing/provider contract. | Obtain lawful access and approved technical contract before enabling any live fetch. |
| OCR / durable workflows | Local RapidOCR is the configured OCR path; Temporal flags are separate. | Document AI and Google Workflows are architecture changes, not configuration substitutes. |

The above is a Cloud Run environment/Secret Manager *presence* audit, not a
live credential, delivery, billing, or tenant-consent test. Review the current
`/app/admin/integrations`, `/app/admin/provider-operations`, and
`/api/platform-admin/production-readiness` states before each activation.

## 2. Set up Google Workspace with this Google Cloud project

1. In project `perfect-period-305406`, confirm Gmail, Calendar, Drive, Pub/Sub,
   and Secret Manager APIs are enabled. This API-level step is complete as of
   24 September 2026. Enabling an API can accept terms and billing liability;
   review the project budget before increasing usage.
2. In [Google Auth Platform](https://console.cloud.google.com/auth/overview),
   configure the application's branding/audience and consent screen. Request
   only the scopes CaseOps uses: `calendar.events`, `gmail.metadata`, and
   `drive.readonly`. Complete any Google verification required by the chosen
   audience and sensitive/restricted scopes.
3. Create a **Web application** OAuth client. Register exactly these redirects:
   `https://api.caseops.ai/api/calendar/connections/google-calendar/callback`,
   `https://api.caseops.ai/api/mailbox/gmail/callback`, and
   `https://api.caseops.ai/api/drive/google/callback`. Record the client ID in
   release configuration and the client secret in Secret Manager. Do not paste
   either into this document.
4. Through the canonical release configuration, bind the matching
   `CASEOPS_GOOGLE_CALENDAR_*`, `CASEOPS_GMAIL_*`, and
   `CASEOPS_GOOGLE_DRIVE_*` OAuth settings. Do not use the seven-day UAT setup
   script as an unattended permanent production rollout. Deploy from current
   `origin/main` and confirm the exact API revision before asking a tenant user
   to connect an account.
5. If Gmail watch is needed, create a dedicated Pub/Sub topic and grant only
   `roles/pubsub.publisher` on that topic to
   `gmail-api-push@system.gserviceaccount.com`. Create a push subscription to
   the CaseOps Gmail webhook, store a random verification token in Secret
   Manager, bind `CASEOPS_GMAIL_PUBSUB_TOPIC` and
   `CASEOPS_GMAIL_WEBHOOK_VERIFICATION_TOKEN`, and verify authentication,
   delivery and renewal. Do not create a paid idle subscription or expose the
   webhook before OAuth and receiver validation are ready.
6. A tenant administrator reviews `/app/admin/integrations`; an authorized user
   completes each Google OAuth connection. Confirm calendar event sync, Gmail
   metadata import/watch, and Drive metadata discovery with that user's consent.
   Do not describe Drive metadata listing as document import or durable sync.

The existing [Google UAT runbook](google-workspace-gcp-uat-setup-2026-06-08.md)
documents a short-lived scripted setup. Google's current
[OAuth consent guide](https://developers.google.com/workspace/guides/configure-oauth-consent),
[web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server),
and [Gmail push guide](https://developers.google.com/workspace/gmail/api/guides/push)
are the authoritative provider instructions.

## 3. Configure non-Google vendors

1. **OpenAI / Voyage:** confirm the account owner, terms, current invoice and
   quota; rotate keys into Secret Manager; keep CaseOps spend caps positive and
   test with offline fixtures first. A human-owned funded tenant may perform a
   single documented live canary under the budget gate. Google Vertex AI is a
   separate model/embedding implementation and requires a quality and safety
   migration, not an environment-variable switch.
2. **SendGrid:** authenticate the sender domain, set the server-side API key
   and webhook public key, register the signed event destination, then verify
   queued, delivered and failed transitions. Follow
   [SendGrid event-webhook runbook](sendgrid-event-webhook.md).
3. **eCourtsIndia:** acquire/renew the provider contract and credits, configure
   the token and supported courts, then check readiness and recorded budget.
   A valid live acceptance needs an exact meaningful case result and the linked
   Matter's hearing after reload. Never substitute a zero-result HTTP 200. QA,
   Docker and automated production checks must stay no-paid.
4. **Indian Kanoon:** follow the
   [licensed adapter checklist](indian-kanoon-licensed-adapter.md): dated terms,
   permitted uses, pricing profiles, positive budgets, retention, token and
   supplied attribution. A configured token alone is not legal-source approval.
5. **Pine Labs Plural:** leave both switches off until merchant credentials,
   UAT payment and webhook signatures, reconciliation, refund/failure paths and
   a production cutover are reviewed. GCP can host the service and store secrets
   but cannot issue a merchant account.
6. **Twilio / Meta WhatsApp:** leave channels off until approved sending
   identities/templates, regional messaging compliance, budgets, secrets and
   callback verification are complete. GCP is infrastructure, not an SMS or
   WhatsApp sender credential.
7. **Microsoft 365 / Outlook and IP registries:** obtain the respective Entra
   tenant consent or registry licensing/contract. Do not enable a placeholder
   adapter or infer access from Google Cloud ownership.

## 4. Completion evidence

For each provider record a dated owner, enabled runtime revision, Secret Manager
version reference (never the value), provider-side account/consent status,
tenant policy, spend/retention controls, signed callback result where relevant,
and a meaningful user-visible result. Recheck current release identity after
every deploy. A no-paid-provider rejection is successful test isolation, not
evidence of provider outage. Any missing commercial or user-consent evidence
keeps that provider `provider-gated`, not `operational`.
