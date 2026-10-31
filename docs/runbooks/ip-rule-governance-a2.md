# IP Rule Governance A2 Enable And Rollback

## Scope

This is the operator procedure for step A2 of the IPLF-027B rollout protocol
(`docs/ip-implementation/evidence/m2/IPLF-027B/a0-quiescence-2026-08-14.md`,
sections "A1" and "A2 - config-only controlled resume"). A2 turns IP rule
governance on in production with a config-only Cloud Run revision on the exact
A1 image. Rollback is the A1 configuration with the flag false.

Two controls own the production value of `CASEOPS_IP_RULE_GOVERNANCE_ENABLED`
and `CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT`:

- `deploy/ip-rule-governance-state.json` is checked-in release state.
  `scripts/deploy-prod.sh` reads it from the exact commit it releases, refuses
  the release before any cloud call if it is invalid, sets both variables from
  it (removing the expiry when disabled) and reads both back after routing.
  The state is kept outside `infra/cloudrun/` because every JSON file there is
  scanned as a scheduler inventory by `scripts/check_cloudrun_manifest_secrets.py`.
- `scripts/ip-rule-governance-a2.sh` changes only those two variables between
  releases. It runs one `gcloud run services update` on the `api` container and
  nothing else.

The release sequence is:

1. Release A1 with the state file disabled (an ordinary `deploy-prod.sh` run).
2. Complete the A0 drain, legacy-revision deletion and fingerprints.
3. A2: `ip-rule-governance-a2.sh enable` on the same image.
4. Merge the state-flip PR so later releases keep governance on.

Between steps 3 and 4 a canonical release turns governance off again, because
the checked-in state still says disabled. Hold `deploy-prod.sh` until the
state-flip PR merges, or treat such a release as a rollback.

## State file contract

```json
{"schema_version": 1, "enabled": false, "rollout_expires_at": null, "approved_by": null, "evidence": null}
```

The file has exactly these keys. `enabled` is a JSON boolean. When it is
`false`, the other three are `null`. When it is `true`:

- `rollout_expires_at` is a UTC timestamp `YYYY-MM-DDTHH:MM:SSZ`, in the future
  when the release runs and at most 180 days ahead;
- `approved_by` names the approving owner;
- `evidence` is a repository-relative path to a file committed in the release
  commit (the A2 enable evidence JSON);
- the release commit carries A1 migration `20261031_0002` in
  `apps/api/alembic/versions`.

An expired window makes every release fail before any cloud call. Renew it
(same contract, new evidence) or set the state back to disabled.

## Preconditions for enable

Record each item in the release evidence before running the script.

1. A1 is serving through the canonical release with the state file disabled:
   `deploy-prod.sh` finished with `rule governance explicitly false`, and the
   serving revision is 100%, untagged and ready on the exact A1 commit.
2. The A0 drain, deletion and fingerprint steps in the A0 artifact are complete:
   both drain windows, the explicit deletion of the writer-capable legacy
   revisions with the three deletion proofs, `T_FENCE`, and two identical
   fingerprints across the second window.
3. The pre-traffic ownership audit reports zero. Its nine queries are
   `ownership_audit()` in `apps/api/tests/test_ip_rule_governance_postgres.py`
   (unowned, missing-owner and mixed-evidence rule sets, orphaned versions and
   deadlines, and cross-company versions, policies and deadlines). Run them
   against production in a `REPEATABLE READ, READ ONLY` transaction that is
   rolled back, and record every count. Each must be `0`. A1 migration
   `20261031_0002` already refuses to finish while a rule set has no owner or
   conflicting ownership evidence; the audit proves nothing drifted since.
4. `test-legal` holds the `ip_rule_governance` entitlement (the `full_ip`
   grant in `docs/runbooks/test-legal-manual-ip-qa-grant.md`).
5. Optional: a second and a third active `test-legal` member holding
   `ip:rules_activate`, so the distinct reviewer and legal-approver journeys
   can run on the tenant.
6. No `deploy-prod.sh` run or other `caseops-api` change is in flight.
7. The owner has approved the rollout expiry: a UTC `...Z` timestamp in the
   future and at most 180 days away.

## Identify the serving A1 release

Read-only:

```bash
gcloud run services describe caseops-api \
  --region asia-south1 --project perfect-period-305406 --format=json \
  > /tmp/caseops-api-a1.json
python -c 'import json,sys; s=json.load(open(sys.argv[1])); print(s["status"]["latestReadyRevisionName"]); print(s["status"]["traffic"]); print([e for c in s["spec"]["template"]["spec"]["containers"] if c["name"]=="api" for e in c["env"] if e["name"] in ("CASEOPS_RELEASE_SHA","CASEOPS_IP_RULE_GOVERNANCE_ENABLED","CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT")])' /tmp/caseops-api-a1.json
gcloud run revisions describe <latest-ready-revision> \
  --region asia-south1 --project perfect-period-305406 \
  --format='value(spec.containers[0].image)'
```

`CASEOPS_RELEASE_SHA` is the expected SHA. The revision image,
`asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:<digest>`,
is the expected image. It must equal the image `deploy-prod.sh` printed as
`immutable api image=` for the A1 release.

## Enable

```bash
scripts/ip-rule-governance-a2.sh enable \
  --project perfect-period-305406 \
  --region asia-south1 \
  --service caseops-api \
  --expected-sha <40-character A1 commit> \
  --expected-image asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:<A1 digest> \
  --rollout-expires-at <YYYY-MM-DDTHH:MM:SSZ> \
  --evidence-output docs/ip-implementation/evidence/m2/IPLF-027B/a2-enable-<YYYY-MM-DD>.json
```

Run it from a checkout of current `main` (`git fetch origin main` first).
Before changing anything the script requires:

- `--expected-sha` to be a fetched commit that carries A1 migration
  `20261031_0002` in `apps/api/alembic/versions`, the rule `deploy-prod.sh`
  applies to an enabled state;
- the service generation observed and Ready, ConfigurationsReady and
  RoutesReady true;
- one untagged 100% traffic entry on the latest revision, which is the latest
  ready revision;
- that revision's `api` image equal to `--expected-image`, and
  `CASEOPS_RELEASE_SHA` equal to `--expected-sha` on the template and the
  revision;
- the flag `false` and no expiry variable;
- an image the new revision cannot drift from. The release deploys the API
  by tag. On an update without `--image`, gcloud pins a by-tag template to
  the digest Cloud Run reports for the serving revision; when no digest is
  reported, Cloud Run resolves the tag again, so the script then requires the
  tag to still resolve to the expected digest.

It then sets the flag to `true` and the expiry, and only those two variables.
After the update it requires a new revision with the same digest, 100%
untagged traffic, ready, the new values, and a template identical to the
previous one apart from those two variables and the api image reference,
which may change only from the tag to the expected digest. Only then does it
write the evidence file (before/after revision, image, SHA, both values and
timestamps).

Any refusal before the update changes nothing. A failure after the update
writes no evidence and tells the operator to read the service and roll back.

## Verify

1. The script exits 0 and prints the new revision and the evidence path.
2. Re-read the service and revision as in "Identify the serving A1 release":
   the new revision is the only traffic target, the image digest is unchanged,
   the flag is `true` and the expiry matches. The service template may now
   name the image by digest instead of by tag; the next canonical release
   names it by tag again.
3. Health:

   ```bash
   curl -fsS --header 'X-CaseOps-Automated-Test:no-paid-providers' https://api.caseops.ai/api/health
   ```

4. Dispatch exact-release production verification for the unchanged SHA:

   ```bash
   gh workflow run prod-verify.yml --repo mishrasanjeev/caseops --ref main \
     -f expected_release_sha=<40-character A1 commit>
   ```

   Do not run the historical A0 gate (`run_historical_a0_gate`); it asserts
   the governance writers return the A0 `503` and fails once A2 is on.
5. Run the governance and legal-deadline acceptance on `test-legal`: propose,
   review and activate a deadline rule, select the company policy, and confirm
   the five legal-deadline mutations still work. No dated production spec for
   A2 exists in `tests/e2e` yet; record the manual journey and its audit
   events in the evidence.

## Rollback

Rollback restores the A1 configuration on the same image: flag `false`,
expiry removed. It needs no expiry argument.

```bash
scripts/ip-rule-governance-a2.sh rollback \
  --project perfect-period-305406 \
  --region asia-south1 \
  --service caseops-api \
  --expected-sha <40-character A1 commit> \
  --expected-image asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:<A1 digest> \
  --evidence-output docs/ip-implementation/evidence/m2/IPLF-027B/a2-rollback-<YYYY-MM-DD>.json
```

It requires the flag to be `true` now and applies the same identity, traffic
and readback checks. Never roll back by routing to a pre-A0 or other pre-fence
revision, and never downgrade the A1 schema. A canonical `deploy-prod.sh` run
with the state file disabled also turns governance off: it releases current
`main` with the flag `false` and the expiry removed.

## Follow-up state-flip PR

After a verified enable, open one PR that:

1. commits the enable evidence JSON at the path passed to `--evidence-output`;
2. changes `deploy/ip-rule-governance-state.json` to

   ```json
   {"schema_version": 1, "enabled": true, "rollout_expires_at": "<the same expiry>", "approved_by": "<approving owner>", "evidence": "docs/ip-implementation/evidence/m2/IPLF-027B/a2-enable-<YYYY-MM-DD>.json"}
   ```

3. records the verification results in the IPLF-027B evidence.

The first release after it merges must log
`rule governance from deploy/ip-rule-governance-state.json: enabled=true until <expiry>`
and pass the readback. After a rollback, the matching PR sets the state back to
the disabled form.
