# Staging Enablement Plan - 2026-05-15

Scope: planning and low-risk CI guardrails only. This document does not create
GCP resources, add secret values, deploy staging, or change production runtime.

## Current Finding

`docs/STAGING_PROOF_2026-05-15.md` remains the active staging proof record.
Its verdict is `NO-GO`.

Proven blockers:

- GitHub Actions staging deploy did not authenticate because
  `GCP_WORKLOAD_IDENTITY_PROVIDER` is missing.
- Cloud Run services `caseops-api-staging` and `caseops-web-staging` were not
  found in project `perfect-period-305406`, region `asia-south1`.
- `.github/workflows/ci.yml` has only an API staging deploy skeleton. It does
  not build/deploy staging Web, prove API/Web revisions, run health checks, or
  capture smoke evidence.

Production release signoff remains in
`docs/RELEASE_SIGNOFF_2026-05-14.md` for SHA
`05b3025d63a10a86eb30a1637f4bc9625bb33a65`.

## Required GitHub Actions Configuration

These GitHub Actions secrets/config entries must exist before the staging
deploy path can move beyond a documented skip:

| Name | Type | Purpose |
| --- | --- | --- |
| `GCP_PROJECT_ID` | secret or variable | Target staging GCP project. Current proof used `perfect-period-305406`. |
| `GCP_REGION` | secret or variable | Target Cloud Run region. Current proof used `asia-south1`. |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | secret | Workload Identity provider resource for GitHub Actions. |
| `GCP_DEPLOY_SA` | secret | Deploy service account email used by GitHub Actions auth. |
| `CASEOPS_DATABASE_URL_STAGING` | secret | Migration target used by the current staging skeleton. Prefer moving to a staging Secret Manager binding before final enablement. |
| `CASEOPS_STAGING_API_BASE_URL` | variable | Public or authenticated URL used for API health and Web build-time API base URL. |
| `CASEOPS_STAGING_WEB_BASE_URL` | variable | Web URL used for Web health and smoke proof. |
| `GCP_ARTIFACT_REPOSITORY` | variable | Artifact Registry repository for staging images. Align with production naming only if intentional. |

Required staging runtime secrets must exist in GCP Secret Manager, not as raw
workflow values:

| Secret Manager entry | Purpose |
| --- | --- |
| `caseops-staging-database-url` | API and migration database URL. |
| `caseops-staging-auth-secret` | API auth signing secret. |
| `caseops-staging-llm-api-key` | LLM provider key if staging uses non-mock LLM calls. |
| `caseops-staging-sendgrid-webhook-public-key` | SendGrid webhook verification key, if that route is enabled in staging. |

Do not reuse production Secret Manager entries unless a later, explicit
operator decision accepts that blast radius.

## Required GCP Resources

Create or verify these resources before enabling a real staging deploy:

| Resource | Required state |
| --- | --- |
| Workload Identity provider | Trusts this GitHub repo on `refs/heads/main`; does not trust arbitrary forks. |
| Deploy service account | Least-privilege deploy identity for staging. |
| Artifact Registry repository | Exists in the staging project/region and accepts API/Web image pushes. |
| Runtime service account | Separate Cloud Run runtime identity for staging API/Web. |
| Cloud Run API service | `caseops-api-staging` exists or is created by the first deploy. |
| Cloud Run Web service | `caseops-web-staging` exists or is created by the first deploy. |
| Migration target | Staging migration job or equivalent canonical migration step exists and targets staging DB only. |
| Staging database | PostgreSQL/pgvector database exists and is isolated from production. |
| Secret Manager entries | Staging-specific entries above exist with current versions. |

Minimum IAM for the deploy service account:

- Push images to Artifact Registry.
- Deploy and update Cloud Run services/jobs.
- Act as the staging runtime service account.
- Read only the staging Secret Manager entries needed for deployment binding.
- Connect to the staging database path when migrations execute.

## Workflow Enablement Design

The workflow must remain fail-closed until it can prove a complete staging
runtime, not just an API image push.

Required deploy/proof order:

1. Gate on required staging config without printing values.
2. Authenticate to GCP by Workload Identity.
3. Build and push API image tagged with `${{ github.sha }}`.
4. Build and push Web image tagged with `${{ github.sha }}`, passing the
   staging API base URL to `NEXT_PUBLIC_API_BASE_URL`.
5. Run the staging migration job or canonical Alembic step against staging DB.
6. Deploy `caseops-api-staging` with staging-specific Secret Manager bindings.
7. Deploy `caseops-web-staging` with the intended Web image.
8. Capture API and Web Cloud Run revision names and image tags.
9. Verify API health returns `{"status":"ok"}`.
10. Verify Web health or HTTP 200 response from the staging Web URL.
11. Run the staging smoke proof.
12. Fail if either deployed image tag does not match `${{ github.sha }}`.

API health proof needs an intentional access model. The current skeleton uses
`--no-allow-unauthenticated`, so a public `curl` health check will fail unless
the workflow obtains an identity token or staging exposes a deliberately public
health endpoint.

## Proof Checklist

Use this checklist for the next staging proof doc:

| Evidence | Required value |
| --- | --- |
| Intended commit | Full SHA from the main push run. |
| API image | Artifact Registry image path and tag matching the intended SHA. |
| Web image | Artifact Registry image path and tag matching the intended SHA. |
| API revision | `caseops-api-staging` latest ready revision and 100% traffic target. |
| Web revision | `caseops-web-staging` latest ready revision and 100% traffic target. |
| Migration proof | Job or command id, target, status, and completion timestamp. |
| API health | URL checked, status, and response body. |
| Web health | URL checked and HTTP status. |
| Smoke proof | Command or workflow step, result, and any artifact/run id. |
| Secret safety | Confirmation that logs contain only secret/config names, not values. |

## Changes Made In This Slice

`.github/workflows/ci.yml` now:

- Grants `id-token: write` only to the staging deploy job so Workload Identity
  auth can run once staging is configured.
- Gates on all required staging config names currently used by the skeleton:
  `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WORKLOAD_IDENTITY_PROVIDER`,
  `GCP_DEPLOY_SA`, and `CASEOPS_DATABASE_URL_STAGING`.
- Prints only missing config names, never values.
- Writes an actionable GitHub Step Summary when config is missing.
- Fails closed before deployment if all config is present, because the workflow
  still lacks full API+Web runtime proof.

## Readiness Verdict

`NO-GO`.

Staging enablement is planned and the CI skeleton now reports missing config
more clearly, but staging is not deploy-ready until the GitHub/GCP resources,
staging-specific secrets, API/Web deploy path, migration proof, health checks,
smoke proof, and deployed-SHA verification are all implemented and captured.
