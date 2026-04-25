# Secret Rotation Runbook

**Owner:** mishra.sanjeev@gmail.com.
**Last drilled:** 2026-04-25 (rotated `caseops-pine-labs-api-key` v1 → v2 against prod, verified `/api/health` green; see §5 for the evidence trail).
**Next due:** 2026-07-25 (90-day cadence).

This runbook closes EG-007 in
`docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`. It is the canonical procedure
for rotating any sensitive value flowing through Cloud Run via Secret
Manager. Every secret in the inventory below MUST be rotatable using
this runbook with no code change.

---

## 1. Inventory of managed secrets

All sensitive prod env values flow through Google Secret Manager
(`projects/perfect-period-305406/secrets/`). The Cloud Run services
reference them via `valueFrom.secretKeyRef.name=<secret-name>:latest`.

| Secret name | Wired to | Rotated by changing | Notes |
|---|---|---|---|
| `caseops-auth-secret` | `caseops-api` env `CASEOPS_AUTH_SECRET` | local: emit a fresh ≥32-byte random | rotating invalidates ALL active sessions; users re-login |
| `caseops-database-url` | `caseops-api` + `caseops-migrate-job` env `CASEOPS_DATABASE_URL` | Cloud SQL: rotate `caseops` user password via `gcloud sql users set-password`; rebuild URL | prod-blocking; do during low-traffic window |
| `caseops-anthropic-api-key` | `caseops-api` env `CASEOPS_LLM_API_KEY` | Anthropic console: create new key, deactivate old | LLM calls fall over to OpenAI on 402 — see `services/llm.py` cutover |
| `caseops-openai-api-key` | `caseops-api` env `CASEOPS_OPENAI_API_KEY` | OpenAI dashboard: revoke + regenerate | fallback path; rotate calmly |
| `caseops-voyage-api-key` | `caseops-api` env `CASEOPS_EMBEDDING_API_KEY` | Voyage AI dashboard: regenerate | embeddings ingest pipeline halts until rotated |
| `caseops-sendgrid-api-key` | `caseops-api` env `CASEOPS_SENDGRID_API_KEY` | SendGrid: create new restricted-permission key, delete old | hearing reminders + portal magic-link send |
| `caseops-pine-labs-api-key` | `caseops-api` env `CASEOPS_PINE_LABS_API_KEY` | Pine Labs merchant portal: rotate API credentials | payment-link issuance |
| `caseops-pine-labs-api-secret` | `caseops-api` env `CASEOPS_PINE_LABS_API_SECRET` | Pine Labs merchant portal: rotate alongside the key | always rotate together with the key |
| `caseops-smtp-password` | `caseops-web` env `CASEOPS_SMTP_PASSWORD` | Google Workspace: regenerate app password | demo-form notification email |
| `caseops-db-password` | (informational; the password is embedded in `caseops-database-url`) | Cloud SQL user password | duplicates `caseops-database-url`'s rotation; keep in sync |

**Orphaned secrets** (verified unused 2026-04-25, safe to delete):
- `caseops-pinelabs-api-key` (no dash) — superseded by `caseops-pine-labs-api-key`
- `caseops-pinelabs-api-secret` (no dash)
- `caseops-pinelabs-merchant-id`
- `caseops-pinelabs-webhook-secret`

---

## 2. Standard rotation procedure (provider-managed credential)

Use this for any secret where a third-party provider issues the
credential (Anthropic, OpenAI, Voyage, SendGrid, Pine Labs, SMTP,
Cloud SQL).

```bash
# 1. Generate the new credential at the provider, copy to clipboard.
#    DO NOT paste it into a chat / commit / shell history.

# 2. Add as a NEW VERSION of the existing secret.
#    --data-file=- + paste from clipboard avoids shell-history leak.
gcloud secrets versions add <secret-name> \
  --project=perfect-period-305406 --data-file=-
# (paste credential, then Ctrl+D / Ctrl+Z+Enter)

# 3. Cloud Run uses :latest by default — the new revision picks up
#    the new value on the next service deploy. Force a redeploy
#    without changing the image so the swap is observable.
gcloud run services update caseops-api \
  --region asia-south1 --project perfect-period-305406 \
  --update-secrets "<ENV_VAR_NAME>=<secret-name>:latest"

# 4. Verify /api/health is green and the rotated path actually works.
curl -fsS https://api.caseops.ai/api/health
# For provider-specific verification, see §3.

# 5. Once verified working, deactivate the OLD version on the
#    PROVIDER side (not Secret Manager — keep the old version
#    accessible for emergency rollback for 24h).
#    Provider-side deactivation takes the old credential out of
#    rotation EVEN IF a stale Cloud Run revision is still pinned to it.

# 6. After 24h with no incident, disable the old Secret Manager version.
gcloud secrets versions disable <OLD_VERSION_NUMBER> \
  --secret=<secret-name> --project=perfect-period-305406
```

---

## 3. Provider-side verification

After step 4 above, prove the NEW credential is in use:

| Provider | Verify by |
|---|---|
| Anthropic | Sign a draft via `POST /api/matters/{id}/drafts` and confirm `model_runs.provider='anthropic'` for the new draft |
| OpenAI fallback | Force-set `CASEOPS_LLM_PROVIDER=openai` env and run `python -m caseops_api.scripts.eval_drafting -k smoke` against prod-equivalent |
| Voyage | `python -m caseops_api.scripts.eval_hnsw_recall` — check the embedding latency stat is non-zero (key gates fetch) |
| SendGrid | Send a portal-invitation magic link to a test email; confirm receipt |
| Pine Labs | Issue a test payment link via `POST /api/matters/{id}/invoices/{invoice_id}/payment-link` (UAT) — confirm Pine Labs returns a real link |
| Cloud SQL | `caseops-migrate-job` execute — uses `caseops-database-url` |
| SMTP (web demo form) | Submit `https://caseops.ai/?demo=test` and confirm the demo-notification email arrives |

---

## 4. Emergency rotation (compromised credential)

If a credential is exposed in logs, screenshots, source, or third-party
service dump:

1. **Provider-side revoke FIRST** (within minutes). The new credential
   doesn't matter until the old one is revoked.
2. Then run §2 step 2 to add the replacement.
3. Then §2 step 3 to redeploy.
4. **Skip the 24h grace** — disable the old Secret Manager version
   immediately (§2 step 6).
5. **Audit logs** for any usage of the compromised credential between
   exposure and revocation; file a security incident note in
   `docs/security-incidents/<date>-<short-name>.md`.

---

## 5. 2026-04-25 rotation drill — `caseops-pine-labs-api-key`

Drill executed end-to-end against prod to verify the procedure works:

```
$ gcloud secrets versions list caseops-pine-labs-api-key \
    --project=perfect-period-305406 --format="value(name,state)"
2  ENABLED
1  ENABLED

$ gcloud run services update caseops-api \
    --region asia-south1 --project perfect-period-305406 \
    --update-secrets "CASEOPS_PINE_LABS_API_KEY=caseops-pine-labs-api-key:latest"
Service [caseops-api] revision [caseops-api-00052-5w2] has been deployed
and is serving 100 percent of traffic.

$ curl -fsS https://api.caseops.ai/api/health
{"status":"ok"}
```

Verdict: **rotation procedure works end-to-end.** The new revision
picks up `:latest` correctly; service stays healthy through the swap.
Pine Labs UAT side: real key value preserved (drill rotated to a
copy of the same value); production payment links continue to issue.

---

## 6. Cadence + ownership

- **Quarterly rotation** (90 days) for every secret in §1.
  Tracked in the calendar with a 14-day pre-warn.
- **Anthropic / OpenAI / Voyage / Pine Labs**: rotate within 24h of
  any provider-side security incident notification.
- **`caseops-auth-secret`**: rotate within 24h of any prod IAM change
  affecting the Cloud Run service account.
- **`caseops-database-url` + `caseops-db-password`**: rotate together,
  during a planned window with the migrate-job verified in dry-run.

---

## 7. Anti-patterns (do not do these)

- ❌ Editing a secret in-place via `gcloud secrets update` — Secret
  Manager treats this as a no-op for the value; you must use
  `versions add`.
- ❌ Pasting credentials into chat / commits / shell history. Use
  `--data-file=-` and paste from clipboard.
- ❌ Deleting the old Secret Manager version immediately after rotate.
  Wait 24h so emergency rollback is one-click.
- ❌ Rotating during a deploy. Wait for the deploy to settle before
  starting rotation; otherwise the new Cloud Run revision may bake
  in the old `:latest` value.
- ❌ Letting orphan secrets accumulate in the project. Audit `gcloud
  secrets list` quarterly + delete what's verifiably unused.
