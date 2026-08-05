# SendGrid Event Webhook — runbook

**Owner:** Operations.
**Last updated:** 2026-08-04 (IPLF-007C).
**Audience:** Anyone configuring CaseOps to receive SendGrid event
notifications in production.

This runbook explains how to enable SendGrid's Signed Event Webhook
against `https://api.caseops.ai/api/webhooks/sendgrid/events` and
how to wire the resulting public key into Cloud Run via Secret
Manager. Until **all** steps are complete, prod will return 503 to
SendGrid event POSTs (fail-closed) and tenant suppression will not
populate from delivery / bounce / unsubscribe events.

## What this webhook does

SendGrid POSTs an array of events to the URL we register. The CaseOps
route at `apps/api/src/caseops_api/api/routes/notifications.py:179` —
`POST /api/webhooks/sendgrid/events` — verifies each batch's ECDSA
signature against the public key we record in Cloud Run, then walks
the events:

| Event | Effect on `HearingReminder` | Effect on `Communication` | Adds `EmailSuppression` row |
|---|---|---|---|
| `delivered` | promotes to `delivered`, sets `delivered_at` | promotes to `delivered`, sets `delivered_at` | no |
| `open` | logged, no state change | promotes to `opened`, sets `opened_at` | no |
| `click`, `deferred`, `processed` | logged, no state change | logged, no state change | no |
| `bounce` | promotes to `failed`, captures reason | promotes to `bounced` | **yes** (`reason=bounce`) |
| `dropped` | promotes to `failed` | promotes to `bounced` | **yes** (`reason=dropped`) |
| `spamreport` | promotes to `failed` | promotes to `bounced` | **yes** (`reason=spam_report`) |
| `unsubscribe` | no state regression | no state regression | **yes** (`reason=unsubscribe`) |
| `group_unsubscribe` | no state regression | no state regression | **yes** (`reason=group_unsubscribe`) |

The webhook also appends every matched event to
`notification_delivery_events`. Its deterministic idempotency key prevents duplicate
provider callbacks from producing duplicate effects. State projection uses provider
occurrence time and terminal-state precedence: a late or duplicate `delivered` event
cannot overwrite `bounced`, `suppressed`, `cancelled`, or `dead_letter`. The event row
records whether it was applied to the current state, so ignored out-of-order evidence
remains auditable.

For durable delivery intents, bounce and suppression are distinct states. A critical
external failure creates an in-app fallback when an eligible membership exists and is
surfaced in the admin queue and metrics. Recovery is preview-first and creates a new
destination version linked to the original intent. Permanent-bounce recovery requires
a different active destination; neither recovery nor suppression clearance rewrites
the original provider events.

`EmailSuppression` is tenant-scoped: a bounce/unsubscribe in tenant A
does not block sends in tenant B. The matching row's `company_id`
defines the scope.

The auth-flow mailers — account-setup link, password-reset link,
portal-access link — **explicitly bypass** the suppression check.
Locking a user out of password reset because they unsubscribed from
matter mail would be wrong. See
`apps/api/src/caseops_api/services/employee_mailer.py` and
`portal_mailer.py`.

## Pre-requisites

1. SendGrid account with API access (we already use one for sending).
2. `gcloud` CLI authenticated against the CaseOps prod GCP project,
   with `roles/secretmanager.admin` on the project.
3. Cloud Run service `caseops-api` deployed at least once (we'll
   redeploy after wiring the secret).

## Step 1 — Enable the Signed Event Webhook in SendGrid

1. Sign in to the SendGrid dashboard.
2. Navigate to **Settings → Mail Settings → Event Webhook**.
3. Toggle **Event Webhook Status** to ON.
4. Set the **HTTP Post URL** to:
   ```
   https://api.caseops.ai/api/webhooks/sendgrid/events
   ```
5. Under **Deliverability Data**, enable:
   - Delivered
   - Bounced
   - Dropped
   - Spam Reports
6. Under **Engagement Data**, enable (recommended for visibility but
   not required for suppression):
   - Open (only persisted on `Communication`, not on
     `HearingReminder`)
   - Group Unsubscribes
   - Unsubscribes
7. Toggle **Signed Event Webhook** to ON. SendGrid will display the
   **Verification Public Key** — a base64 string. Copy it. **Do not
   paste it into the repo.**

## Step 2 — Store the public key in Secret Manager

```bash
PROJECT_ID="<your-gcp-project>"
KEY_B64="<paste-the-public-key>"

gcloud secrets create caseops-sendgrid-webhook-public-key \
  --project="${PROJECT_ID}" \
  --replication-policy=automatic \
  --data-file=- <<<"${KEY_B64}"
```

If the secret already exists (re-key after rotation), add a new
version instead:

```bash
gcloud secrets versions add caseops-sendgrid-webhook-public-key \
  --project="${PROJECT_ID}" \
  --data-file=- <<<"${NEW_KEY_B64}"
```

## Step 3 — Confirm the Cloud Run wire

`infra/cloudrun/api-service.yaml` already references
`caseops-sendgrid-webhook-public-key` in two places:

- The top-level `run.googleapis.com/secrets` annotation, so Cloud Run
  mounts the secret into the pod.
- The `CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY` env var with `secretKeyRef`
  pointing at version `latest`.

Redeploy via `scripts/deploy-prod.sh` (the canonical path; never
`gcloud run deploy` ad-hoc — it skips the migrate-job and version
chain):

```bash
scripts/deploy-prod.sh
```

Verify the new Cloud Run revision picked up the env var:

```bash
gcloud run services describe caseops-api \
  --region=asia-south1 \
  --format='value(spec.template.spec.containers[0].env[])' \
  | tr ';' '\n' | grep -i webhook
```

You should see:
```
{'name': 'CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY', 'valueFrom': {'secretKeyRef': {...}}}
```

## Step 4 — Trigger a test event

In SendGrid → Mail Settings → Event Webhook, click **Test Your
Integration**. SendGrid POSTs a sample event batch. Confirm:

```bash
gcloud run services logs read caseops-api \
  --region=asia-south1 --limit=20 \
  | grep -i "sendgrid"
```

You should see no `503` in the access log for that POST. A real
delivery (one matter email or hearing reminder) is the strongest
end-to-end check.

## Step 5 — Verify suppression population

After a real bounce / unsubscribe arrives, the `email_suppressions`
table should grow by one row per `(company_id, recipient_email)`
pair. Quick check via the migrate-job runner or `psql`:

```sql
select reason, count(*)
from email_suppressions
where company_id = '<your-tenant-id>'
group by reason;
```

If you see no rows after a known bounce, walk these in order:

1. Cloud Run revision env var present? (Step 3)
2. SendGrid webhook URL exact match `https://api.caseops.ai/api/webhooks/sendgrid/events`? (Step 1)
3. Secret value matches the SendGrid-shown public key? (Step 2)
4. Cloud Run logs show 401 (signature mismatch) → key rotated on
   one side and not the other.
5. Cloud Run logs show 503 → secret missing or
   `cryptography` lib unavailable; redeploy with the latest base
   image.

## Rollback

To disable signature verification temporarily (e.g., during a key
rotation):

1. Disable the SendGrid Signed Event Webhook toggle.
2. The CaseOps webhook will continue returning 503 in non-local envs
   (fail-closed). It will NOT silently accept unsigned events. To
   accept unsigned events you must also delete the secret AND set
   `CASEOPS_ENV=local` (which is unsafe in prod).

There is no path to silently accept unsigned events in production.
That is by design — it prevents a forged delivery report from
flipping a `HearingReminder` to `delivered` against a tenant.

## Related references

- Code: `apps/api/src/caseops_api/api/routes/notifications.py:113`
  (`_verify_sendgrid_signature`).
- SendGrid docs: <https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/event>
- SendGrid signed-webhook docs: <https://www.twilio.com/docs/sendgrid/api-reference/webhooks/get-signed-event-webhooks-public-key>
- Tests: `apps/api/tests/test_sendgrid_webhook_security.py`,
  `apps/api/tests/test_email_suppression.py`.
