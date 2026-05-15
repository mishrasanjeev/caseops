# Staging Proof - 2026-05-15

Branch: `codex/staging-deploy-proof-2026-05-15`
Base: `origin/main` at `ef09d77c13796c1cb73052f080d6cf42681cf46f`

## Verdict

`NO-GO`

Staging deploy remains a credential-gated no-op. No staging API/Web runtime
proof exists for this milestone.

## Evidence

- `origin/main` contains merge commit
  `ef09d77c13796c1cb73052f080d6cf42681cf46f`.
- Main push CI run `25923444136` completed successfully for head SHA
  `ef09d77c13796c1cb73052f080d6cf42681cf46f`.
- CI job `Cloud Run deploy (staging)` / job id `76205390739` completed, but
  the deploy gate reported:
  `GCP_WORKLOAD_IDENTITY_PROVIDER not set - deploy is a visible no-op.`
- In that staging job, these steps were skipped:
  - `Checkout`
  - `Authenticate to GCP via Workload Identity`
  - `Set up gcloud`
  - `Configure Docker for Artifact Registry`
  - `Build + push container image`
  - `Run Alembic migrations against staging`
  - `Deploy to Cloud Run (staging)`
- Local GCP CLI is authenticated against project `perfect-period-305406`,
  region `asia-south1`.
- No Cloud Run services matching `staging` were listed in
  `perfect-period-305406` / `asia-south1`.
- Direct describes for `caseops-api-staging` and `caseops-web-staging` in
  `perfect-period-305406` / `asia-south1` both returned `Cannot find service`.

## Required Config Status

| Config | Status |
| --- | --- |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Missing; proven by main-push CI staging job log. |
| `GCP_PROJECT_ID` | Not evaluated by CI because the credential gate stopped before GCP auth. GitHub secret-name listing was not available to the current token. |
| `GCP_REGION` | Not evaluated by CI because the credential gate stopped before GCP auth. GitHub secret-name listing was not available to the current token. |
| `GCP_DEPLOY_SA` | Not evaluated by CI because the credential gate stopped before GCP auth. GitHub secret-name listing was not available to the current token. |
| `CASEOPS_DATABASE_URL_STAGING` | Not evaluated by CI because the credential gate stopped before migrations. |
| Staging auth/runtime secrets | Not evaluated by CI because the credential gate stopped before deployment. |

## Additional Workflow Gaps

- `.github/workflows/ci.yml` deploys only `caseops-api-staging`; it has no
  staging web image build/deploy step.
- The staging job has no post-deploy health check or smoke step.
- The workflow comment says `CASEOPS_DATABASE_URL (staging)`, while the
  migration step reads `CASEOPS_DATABASE_URL_STAGING`.
- Because `caseops-web-staging` does not exist and no web staging deploy step is
  defined, this workflow cannot currently satisfy Web deployed SHA proof.

## Proof Not Available

- API deployed SHA: unavailable.
- Web deployed SHA: unavailable.
- API image tag: unavailable.
- Web image tag: unavailable.
- Cloud Run revision proof: unavailable.
- Migration proof: unavailable.
- Health check proof: unavailable.
- Smoke proof: unavailable.

## Commands Run

```text
git rev-parse origin/main
git merge-base --is-ancestor ef09d77c13796c1cb73052f080d6cf42681cf46f origin/main
git status --short
git branch --show-current
git switch -c codex/staging-deploy-proof-2026-05-15 origin/main
rg -n "staging|GCP_PROJECT_ID|GCP_REGION|GCP_WORKLOAD_IDENTITY_PROVIDER|GCP_DEPLOY_SA|deploy|Cloud Run|workload|secret" .github/workflows/ci.yml scripts infra docs/RELEASE_SIGNOFF_2026-05-14.md docs/FUTURE_WORKPLAN_2026-05-14.md docs/STRICT_ENTERPRISE_GAP_TASKLIST.md
Get-Content .github/workflows/ci.yml
Get-Content scripts/deploy-prod.sh
Get-Content infra/cloudrun/api-service.yaml
rg --files | rg "(?i)(staging|cloudrun|cloud-run|deploy|service\\.yaml|api-service|web-service|migrate)"
gh run list --branch main --limit 10 --json databaseId,name,status,conclusion,headSha,createdAt,event,url
gh api repos/mishrasanjeev/caseops/actions/secrets --jq ".secrets[].name"
gcloud auth list --format="value(account,status)"
gcloud config list --format="value(core.project,run.region,compute.region)"
gcloud run services list --project perfect-period-305406 --region asia-south1 --filter="metadata.name~staging" --format="table(metadata.name,status.url,status.traffic[0].revisionName,status.traffic[0].percent)"
gcloud run services describe caseops-api-staging --project perfect-period-305406 --region asia-south1 --format="json(metadata.name,status.url,status.latestReadyRevisionName,status.traffic,spec.template.spec.containers[].image)"
gcloud run services describe caseops-web-staging --project perfect-period-305406 --region asia-south1 --format="json(metadata.name,status.url,status.latestReadyRevisionName,status.traffic,spec.template.spec.containers[].image)"
```
