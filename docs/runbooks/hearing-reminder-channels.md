# Hearing reminder channels — Twilio SMS + WhatsApp setup

**Owner:** mishra.sanjeev@gmail.com.
**Status:** SMS via Twilio + WhatsApp via Meta Cloud API are wired
in code (MOD-TS-007 channel breadth, 2026-04-26) but **disabled by
default** so a fresh deployment never burns money on a test message.
This runbook is the procedure to enable each channel when a customer
needs it.

---

## 1. Default state

| Channel | Enum value | Default | Adapter |
|---|---|---|---|
| Email | `EMAIL` | **enabled** when `CASEOPS_SENDGRID_API_KEY` + sender configured | SendGrid Web API (`_send_via_sendgrid`) |
| SMS | `SMS` | disabled | Twilio Messages API (`_send_via_twilio_sms`) |
| WhatsApp | `WHATSAPP` | disabled | Meta Cloud API (stub — needs template approval) |
| In-app | `IN_APP` | n/a | Read by the in-app reminder UI, not the worker |

When a channel's adapter is disabled or unconfigured, the worker
**leaves the row at `QUEUED`** (not `FAILED`) with an actionable
`last_error` pointing the operator at the env vars to set. Flipping
the gate later drains the backlog without re-scheduling.

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

WhatsApp Cloud API utility-template pricing (India, as of 2026):
- ~₹0.39 per template message via Meta Cloud API direct.
- Same cost discipline as SMS — the per-`(hearing_id, channel,
  scheduled_for)` unique constraint prevents duplicate sends on
  retry.

---

## 4. Why both gates default to `false`

CaseOps user memory `feedback_user_bias_in_recommendations.md`
combined with the founder-stage "0 customers, can't waste money"
constraint means **every paid integration must be opt-in**. The
worker's degradation pattern is:

1. Channel adapter not configured → row stays `QUEUED` with
   actionable `last_error` (no spend, no data loss).
2. Operator wires the gate → next worker run drains the backlog.
3. Adverse provider event (Twilio 4xx, etc.) → row goes `FAILED`
   with the provider's response captured for triage.

Per the cost-discipline rule, the worker **never re-tries an
already-`SENT` row** even if the recipient hasn't acknowledged —
delivery confirmation goes through the SendGrid (today) /
Twilio status callback (when wired).

---

## 5. Per-tenant channel preference (future)

Today every tenant uses email by default. Per-tenant channel
preference (e.g. solo lawyer prefers SMS, GC team prefers email +
in-app) is a future scope on `Company.default_reminder_channel` +
`CompanyMembership.notification_channels` columns. Not in v1 because
the value depends on actual customer signal, not speculation.
