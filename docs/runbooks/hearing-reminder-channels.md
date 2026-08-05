# Hearing reminder channels — Twilio SMS + WhatsApp setup

**Owner:** mishra.sanjeev@gmail.com.
**Last updated:** 4 August 2026 (IPLF-007C).
**Status:** the durable, multi-channel policy and recovery path is implemented.
External adapters remain fail-closed until their genuine provider, sender/template,
credential, policy, and QA-recipient gates pass.

---

## 1. Default state

| Channel | Enum value | Default | Adapter |
|---|---|---|---|
| Email | `EMAIL` | **enabled** when `CASEOPS_SENDGRID_API_KEY` + sender configured | SendGrid Web API (`_send_via_sendgrid`) |
| SMS | `SMS` | disabled | Twilio Messages API (`_send_via_twilio_sms`) |
| WhatsApp | `WHATSAPP` | disabled | Meta Cloud API (stub — needs template approval) |
| In-app | `IN_APP` | available | Durable intent is delivered without an external provider |

When a channel's adapter is disabled or unconfigured, the worker
records an explicit durable `blocked` outcome and an actionable redacted error. A
critical external intent also creates an in-app fallback/companion where an eligible
membership exists. Provider-disabled work must be recovered through preview plus a
new destination version; operators do not mutate or silently replay the original
attempt.

### 1.1 Hearing policy and time precision

At confirmation time, persist explicit recipients, channels, offsets, timezone,
criticality, and escalation memberships. Hearing time is one of:

- `exact`: a local time and valid IANA timezone are required;
- `session_only`: store the disclosed session label and policy reminder time; or
- `unpublished`: store that no time is published and the policy reminder time.

Never substitute 10:00 IST for a missing hearing time. The policy default for a
date-only reminder is 18:00 local time and is represented as policy, not as a hearing
time. A schedule or recipient-policy change cancels pending child intents and creates
new versioned work in the same transaction.

### 1.2 Production Cloud Run job requirements

The production scheduler drains email reminders through
`caseops-reminders-job` on the `caseops-reminders-cadence` Cloud
Scheduler trigger. The job must use the current API image and these
settings:

```text
CASEOPS_ENV=production
CASEOPS_AUTO_MIGRATE=false
CASEOPS_HEARING_REMINDERS_ENABLED=true
CASEOPS_SENDGRID_SENDER_EMAIL=hearings@caseops.ai
CASEOPS_SENDGRID_SENDER_NAME=CaseOps
CASEOPS_DATABASE_URL=secret:caseops-database-url:latest
CASEOPS_AUTH_SECRET=secret:caseops-auth-secret:latest
CASEOPS_SENDGRID_API_KEY=secret:caseops-sendgrid-api-key:latest
```

Do not store a literal database URL on the job. Password rotation will
break the worker unless `CASEOPS_DATABASE_URL` points at Secret
Manager. After any API image deploy or secret rotation, verify the job:

```bash
gcloud run jobs execute caseops-reminders-job \
  --region asia-south1 --wait

gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="caseops-reminders-job"' \
  --freshness=10m --limit=20 \
  --format='value(timestamp,severity,textPayload,jsonPayload.message)'
```

Expected result: the execution completes successfully, the container
exits `0`, and due rows either remain queued for valid provider-gating
reasons or SendGrid returns `202 Accepted`. For a true delivery smoke,
use only a temporary workspace and a recipient controlled by the
operator, then confirm the reminder row reaches `delivered` through the
SendGrid webhook.

---

## 2. Enabling Twilio SMS

### 2.1 Cost reality check

- ₹0.50 – ₹2.00 per SMS in India depending on length + sender ID
  registration. The worker respects the per-`(hearing_id, channel,
  scheduled_for)` unique constraint so retries never duplicate
  billable messages.
- For a solo lawyer with 30 hearings/month + the default 2 reminder
  offsets = 60 SMS/month = ~₹60–₹120/month. Acceptable.
- For a 100-lawyer firm at 10 hearings/lawyer/month = 6000 SMS/month
  = ₹6000–₹12000/month. Decide pricing accordingly.

### 2.2 Procedure

1. **Create a Twilio account.** `https://console.twilio.com`
2. **Get a sender number.** Either a Twilio India long code (~₹100/mo)
   or, for higher throughput, a registered alphanumeric sender ID
   (`CASEOPS` — DLT registration with TRAI takes ~7 days).
3. **Add three secrets to Secret Manager:**
   ```bash
   for s in caseops-twilio-account-sid caseops-twilio-auth-token \
            caseops-twilio-from-number; do
     printf '%s' "<value>" | gcloud secrets create "$s" \
       --project=perfect-period-305406 \
       --replication-policy=automatic --data-file=-
     gcloud secrets add-iam-policy-binding "$s" \
       --project=perfect-period-305406 \
       --member="serviceAccount:caseops-runtime@perfect-period-305406.iam.gserviceaccount.com" \
       --role=roles/secretmanager.secretAccessor
   done
   ```
4. **Wire into the API service** (single redeploy, no image change):
   ```bash
   gcloud run services update caseops-api \
     --region asia-south1 --project perfect-period-305406 \
     --update-env-vars CASEOPS_TWILIO_ENABLED=true \
     --update-secrets \
"CASEOPS_TWILIO_ACCOUNT_SID=caseops-twilio-account-sid:latest,\
CASEOPS_TWILIO_AUTH_TOKEN=caseops-twilio-auth-token:latest,\
CASEOPS_TWILIO_FROM_NUMBER=caseops-twilio-from-number:latest"
   ```
5. **Verify with one test row.** Insert a `HearingReminder` with
   `channel='sms'` + your own phone, run the worker manually:
   ```
   python -m caseops_api.scripts.send_hearing_reminders --mode live
   ```
   Confirm SMS arrives + DB row flips to `SENT` with
   `provider='twilio'`.
6. **Enable the docs runbook entry above.** Mark Twilio
   "**enabled** since YYYY-MM-DD".

### 2.3 Rotation

The Twilio auth token rotates per the standard secret-rotation
runbook (`docs/runbooks/secret-rotation.md` §2). Twilio dashboard →
Account → Auth Token → "Request a new auth token" → add as a new
version of `caseops-twilio-auth-token` → redeploy the API service
with `--update-secrets` pointing at `:latest`.

---

## 3. Enabling WhatsApp Cloud API

### 3.1 Why it's harder than Twilio

WhatsApp Cloud API only allows transactional messages outside the
24-hour customer-initiated window via **pre-approved templates**.
Each template gets reviewed by Meta over 1-3 business days. Without
a template, every reminder past the 24h window will fail.

### 3.2 Procedure

1. **Create a WhatsApp Business Account** + Meta Business Manager.
2. **Submit one template** to Meta for review. Suggested:
   ```
   Name: hearing_reminder_v1
   Category: UTILITY
   Body (English):
     Hi {{1}}, your hearing for matter {{2}} is scheduled at
     {{3}} on {{4}}. — CaseOps
   ```
   Wait for approval (typically 1-3 business days).
3. **Add four secrets to Secret Manager:**
   - `caseops-whatsapp-access-token` (long-lived system-user token)
   - `caseops-whatsapp-phone-number-id` (Meta WhatsApp business id)
   - `caseops-whatsapp-template-name` (matches step 2 — e.g. `hearing_reminder_v1`)
   - Grant `caseops-runtime` SA the secretAccessor role on each.
4. **Wire into the API service:**
   ```bash
   gcloud run services update caseops-api \
     --region asia-south1 --project perfect-period-305406 \
     --update-env-vars CASEOPS_WHATSAPP_ENABLED=true \
     --update-secrets \
"CASEOPS_WHATSAPP_ACCESS_TOKEN=caseops-whatsapp-access-token:latest,\
CASEOPS_WHATSAPP_PHONE_NUMBER_ID=caseops-whatsapp-phone-number-id:latest,\
CASEOPS_WHATSAPP_TEMPLATE_NAME=caseops-whatsapp-template-name:latest"
   ```
5. **Implement the adapter.** Today the worker stub returns
   `skipped_provider_disabled`. The adapter (Cloud API HTTP POST to
   `https://graph.facebook.com/v18.0/{phone_number_id}/messages`)
   needs a few hours of work that's gated on the template approval
   anyway — so the implementation lands once you have an approved
   template name.

### 3.3 Cost

Verify current provider pricing and India-specific rules in the provider console at
activation time; this repository does not freeze a market-price claim. Idempotency is
enforced by durable intent key plus destination version, so a retry cannot create a
second effect for the same version.

---

## 4. Why both gates default to `false`

Every paid external integration is opt-in. The degradation pattern is:

1. Channel adapter not configured → durable intent becomes `blocked`, with a
   redacted actionable error and in-app fallback for eligible critical recipients.
2. Operator resolves the genuine gate, previews recovery, and creates a successor
   destination version; the original evidence remains immutable.
3. Adverse provider event → append the provider event, project a typed terminal or
   retry state, populate tenant suppression when applicable, and alert operators.

The worker never retries an already delivered or terminal-negative intent. Delivery
confirmation comes from the signed provider callback; out-of-order or duplicate
callbacks remain evidence but cannot regress terminal state.

---

## 5. Per-hearing recipient and channel policy

The confirmed Matter hearing owns its explicit policy JSON: recipient memberships,
channels, offsets, escalation memberships, timezone, criticality, and date-only
reminder time. Recipients must be active, belong to the same company, and retain
access at dispatch time. The immutable delivery intent snapshots the selected target
and destination version. A self-service channel test is deliberately in-app only and
never calls an external provider.
