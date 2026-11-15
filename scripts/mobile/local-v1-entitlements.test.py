"""Fixture authority contracts only; these doubles never prove a PostgreSQL grant."""
import copy
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("v1_entitlements", Path(__file__).with_name("local-v1-entitlements.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

NOW = 1794495600


def fixture():
    ids = {key: f"00000000-0000-4000-8000-{n:012d}" for n, key in enumerate(
        ("companyId", "membershipId", "userId", "subscriptionId"), 1)}
    source = "a" * 40
    slug = "test-mobile-v1-" + "b" * 12
    profile = datetime.fromtimestamp(NOW + 3600, UTC).isoformat()
    actor = {**{k: ids[k] for k in ("companyId", "membershipId", "userId")}, "companySlug": slug,
             "role": "owner", "membershipActive": True, "userActive": True}
    def ack(method, route, serial):
        return {"method": method, "route": route, "status": 200, "releaseSha": source, "requestId": "synthetic-request-" + str(serial)}
    q = {"schemaVersion": 1, "kind": "isolated-native-v1-entitlements", "readyForLive": True,
         "preparedOnly": False, "sourceSha": source, "runId": "v1-" + "c" * 24, **ids,
         "companySlug": slug, "noPaidMarker": "no-paid-providers", "productionAccessed": False,
         "automaticRetry": False, "startedAt": NOW, "expiresAt": NOW + 30, "profileExpiresAt": profile,
         "bootstrapAcknowledgement": {**ack("POST", "/api/bootstrap/company", 1), **actor, "companyType": "law_firm"},
         "ownerIdentity": {**ack("GET", "/api/auth/me", 2), **actor, "capabilities": ["company:manage_users"]},
         "mfaAcknowledgement": {**ack("POST", "/api/auth/mfa/step-up", 3), "verified": True,
                                **{k: ids[k] for k in ("companyId", "membershipId", "userId")}},
         "postgresIdentity": {"observed": True, "readOnly": True, "database": "caseops_mobile",
                              "systemIdentifier": "123456789", "startedAt": datetime.fromtimestamp(NOW - 60, UTC).isoformat()}}
    env = {"CASEOPS_MOBILE_V1_ENTITLEMENTS_FIXTURE": "1", "CASEOPS_ENV": "local",
           "CASEOPS_LLM_PROVIDER": "mock", "CASEOPS_RELEASE_SHA": source,
           "CASEOPS_IP_WORKSPACE_ENABLED": "true", "CASEOPS_IP_RULE_GOVERNANCE_ENABLED": "true",
           "CASEOPS_IP_WORKSPACE_ROLLOUT_EXPIRES_AT": profile, "CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT": profile,
           "CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS": "test-legal,test-mobile-other," + slug}
    return q, env


class Admission(unittest.TestCase):
    def assert_refused_before_authority(self, q, env, observed=NOW):
        effects = []
        with self.assertRaises((AssertionError, ValueError, TypeError)):
            module.run_grant(q, environment=env, now=lambda: observed,
                claim=lambda _: effects.append("claim"), persist=lambda _: effects.append("persist"),
                factory=lambda *_: effects.append("factory"))
        self.assertEqual(effects, [])

    def test_disabled_and_cloud_environments_refuse_before_claim_or_database_import(self):
        q, env = fixture()
        for key, value in [("CASEOPS_MOBILE_V1_ENTITLEMENTS_FIXTURE", "0"), ("CASEOPS_ENV", "production"),
                           ("CASEOPS_LLM_PROVIDER", "openai"), *[(name, "cloud") for name in (
                               "K_SERVICE", "K_CONFIGURATION", "K_REVISION", "CLOUD_RUN_JOB", "GAE_ENV", "FUNCTION_TARGET")]]:
            with self.subTest(key=key):
                self.assert_refused_before_authority(q, {**env, key: value})

    def test_exact_deadline_boundaries_and_no_implicit_extension(self):
        q, env = fixture()
        self.assertEqual(module.validate_request(q, env, NOW), NOW + 30)
        self.assertEqual(module.validate_request(q, env, NOW + 29.999), NOW + 30)
        for observed in (NOW - 0.001, NOW + 30, NOW + 31):
            self.assert_refused_before_authority(q, env, observed)
        self.assert_refused_before_authority({**q, "expiresAt": NOW + 31}, env)

    def test_source_run_slug_and_owner_identity_substitutions_refuse(self):
        original, env = fixture()
        for key, value in (("sourceSha", "d" * 40), ("runId", "v1-other"), ("companySlug", "test-legal"),
                           ("subscriptionId", original["companyId"]), ("readyForLive", False),
                           ("preparedOnly", True), ("automaticRetry", True), ("productionAccessed", True)):
            self.assert_refused_before_authority({**original, key: value}, env)
        for name in ("bootstrapAcknowledgement", "ownerIdentity"):
            for key, value in (("companyId", original["subscriptionId"]), ("role", "admin"),
                               ("membershipActive", False), ("userActive", False), ("status", 201)):
                q = copy.deepcopy(original); q[name][key] = value
                self.assert_refused_before_authority(q, env)

    def test_mfa_is_bound_to_the_exact_current_owner_and_source(self):
        original, env = fixture()
        for key, value in (("verified", False), ("userId", original["subscriptionId"]),
                           ("membershipId", original["subscriptionId"]), ("companyId", original["subscriptionId"]),
                           ("releaseSha", "d" * 40), ("route", "/api/auth/login")):
            q = copy.deepcopy(original); q["mfaAcknowledgement"][key] = value
            self.assert_refused_before_authority(q, env)

    def test_public_request_rejects_extra_authority_and_unreviewed_ack_fields(self):
        original, env = fixture()
        for key in ("entitlements", "databaseUrl", "table", "credentialEvidence"):
            self.assert_refused_before_authority({**original, key: "unreviewed"}, env)
        for name in ("bootstrapAcknowledgement", "ownerIdentity", "mfaAcknowledgement"):
            q = copy.deepcopy(original); q[name]["unexpected"] = "unreviewed"
            self.assert_refused_before_authority(q, env)

    def test_expired_mismatched_or_disabled_rollout_and_missing_no_paid_scope_refuse(self):
        q, env = fixture()
        for key, value in (("CASEOPS_IP_WORKSPACE_ENABLED", "false"), ("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "false"),
                           ("CASEOPS_IP_WORKSPACE_ROLLOUT_EXPIRES_AT", "different"),
                           ("CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS", "test-legal,test-mobile-other")):
            self.assert_refused_before_authority(q, {**env, key: value})
        self.assert_refused_before_authority({**q, "profileExpiresAt": datetime.fromtimestamp(NOW, UTC).isoformat()}, env)

    def test_postgres_observation_requires_the_exact_private_database_and_live_server(self):
        original, env = fixture()
        for key, value in (("observed", False), ("readOnly", False), ("database", "production"),
                           ("systemIdentifier", "unknown"), ("startedAt", "2026-11-12T15:00:00")):
            q = copy.deepcopy(original); q["postgresIdentity"][key] = value
            self.assert_refused_before_authority(q, env)

    def test_row_has_exactly_two_nonbillable_entitlements_and_no_provider_authority(self):
        q, _ = fixture(); stamp = datetime.fromtimestamp(NOW, UTC)
        row = module.subscription_values(q, stamp)
        self.assertEqual(len(row), 24)
        self.assertEqual(row["entitlement_overrides_json"], {"ip_workspace": True, "ip_rule_governance": True})
        self.assertIs(row["externally_billable"], False)
        self.assertEqual((row["id"], row["company_id"], row["source"], row["status"]),
                         (q["subscriptionId"], q["companyId"], "mobile_v1_fixture", "manual_active"))
        for name in ("billing_account_id", "plan_version_id", "provider", "provider_customer_id",
                     "provider_subscription_id", "provider_mandate_id", "current_period_start", "current_period_end",
                     "trial_start", "trial_end", "cancelled_at", "grace_until"):
            self.assertIsNone(row[name])
        self.assertEqual(row["created_at"], stamp); self.assertEqual(row["updated_at"], stamp)


class Ownership(unittest.TestCase):
    def test_positive_receipt_requires_exact_single_insert_postcommit_and_outbox_evidence(self):
        q, env = fixture(); events = []; effects = []
        outbox = {"rows": 0, "sha256": module.digest([])}
        result = {"committed": True, "subscriptionId": q["subscriptionId"], "businessInserts": 1,
                  "businessUpdates": 0, "businessDeletes": 0, "postgresIdentity": q["postgresIdentity"],
                  "subscriptionSha256": module.digest(module.subscription_values(q, datetime.fromtimestamp(NOW, UTC))),
                  "outboxBefore": outbox, "outboxAfter": dict(outbox), "sqlStatements": 20,
                  "postcommitReadOnlyVerified": True}
        class Runtime:
            def grant(self):
                effects.append("grant"); return result
            def close(self):
                effects.append("close")
        receipt = module.run_grant(q, environment=env, now=lambda: NOW,
            claim=lambda key: effects.append(key), persist=events.append, factory=lambda *_: Runtime())
        self.assertEqual(effects, ["v1-entitlements-company:" + q["companyId"], "grant", "close"])
        self.assertEqual([event["type"] for event in events], ["v1_entitlements_started", "v1_entitlements_committed"])
        self.assertEqual(events[-1]["receiptSha256"], module.digest(receipt))
        self.assertEqual(receipt["normalReadinessReadback"], "pending")
        self.assertEqual(receipt["entitlements"], {"ip_workspace": True, "ip_rule_governance": True})
        self.assertIs(receipt["productionAccessed"], False)
        self.assertIs(receipt["externallyBillable"], False)

    def test_elapsed_commit_cannot_be_reported_complete_or_compensated(self):
        q, env = fixture(); clock = [NOW]; events = []; effects = []; spent = set()
        def claim(key):
            if key in spent:
                raise FileExistsError("synthetic spent company claim")
            spent.add(key)
        class Runtime:
            def grant(self):
                effects.append("acknowledged commit"); clock[0] = NOW + 30
                return {"committed": True}
            def close(self):
                effects.append("close")
        with self.assertRaisesRegex(AssertionError, "V1_ENTITLEMENTS_DEADLINE"):
            module.run_grant(q, environment=env, now=lambda: clock[0], claim=claim,
                             persist=events.append, factory=lambda *_: Runtime())
        self.assertEqual(effects, ["acknowledged commit", "close"])
        self.assertEqual([event["type"] for event in events], ["v1_entitlements_started", "v1_entitlements_incomplete"])
        self.assertEqual(spent, {"v1-entitlements-company:" + q["companyId"]})

    def test_unknown_commit_ack_keeps_the_company_claim_spent_and_never_reexecutes(self):
        q, env = fixture(); spent = set(); events = []; effects = []; original = RuntimeError("synthetic unknown commit acknowledgement")
        def claim(key):
            if key in spent:
                raise FileExistsError("synthetic spent company claim")
            spent.add(key)
        class Runtime:
            def grant(self):
                effects.append("grant"); raise original
            def close(self):
                effects.append("close")
        factory = lambda *_: Runtime()
        with self.assertRaises(RuntimeError) as caught:
            module.run_grant(q, environment=env, now=lambda: NOW, claim=claim, persist=events.append, factory=factory)
        self.assertIs(caught.exception, original)
        self.assertEqual(effects, ["grant", "close"])
        self.assertEqual(events[-1], {"type": "v1_entitlements_incomplete", "outcomeUnknown": True, "automaticRetry": False})
        with self.assertRaises(FileExistsError):
            module.run_grant(q, environment=env, now=lambda: NOW, claim=claim, persist=events.append, factory=factory)
        self.assertEqual(effects, ["grant", "close"])

    def test_body_and_cleanup_failures_are_retained_together(self):
        q, env = fixture(); body = RuntimeError("synthetic grant failed"); cleanup = RuntimeError("synthetic close failed")
        class Runtime:
            def grant(self):
                raise body
            def close(self):
                raise cleanup
        with self.assertRaises(ExceptionGroup) as caught:
            module.run_grant(q, environment=env, now=lambda: NOW, claim=lambda _: None,
                             persist=lambda _: None, factory=lambda *_: Runtime())
        self.assertEqual(caught.exception.exceptions, (body, cleanup))


class DescriptorAndCli(unittest.TestCase):
    def test_held_request_rejects_changed_hash_permissions_links_and_duplicate_keys(self):
        q, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); root.chmod(0o700)
            target = root / "request.json"
            original = json.dumps(q).encode()
            target.write_bytes(original); target.chmod(0o600)
            expected = hashlib.sha256(original).hexdigest()
            self.assertEqual(module.read_request(target, expected, root), q)
            with self.assertRaises(AssertionError):
                module.read_request(target, "0" * 64, root)
            target.chmod(0o644)
            with self.assertRaises(AssertionError):
                module.read_request(target, expected, root)
            target.chmod(0o600)
            link = root / "hard-link.json"; os.link(target, link)
            with self.assertRaises(AssertionError):
                module.read_request(target, expected, root)
            link.unlink()
            duplicate = b'{"runId":"first","runId":"second"}'
            target.write_bytes(duplicate)
            with self.assertRaisesRegex(AssertionError, "V1_ENTITLEMENTS_DUPLICATE_JSON_KEY"):
                module.read_request(target, hashlib.sha256(duplicate).hexdigest(), root)
            target.unlink(); target.symlink_to(root / "missing.json")
            with self.assertRaises((AssertionError, FileNotFoundError)):
                module.read_request(target, expected, root)

    def test_exclusive_output_preserves_existing_bytes_and_exact_private_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); root.chmod(0o700)
            target = root / "receipt.json"
            value = {"synthetic": True}
            proof = module.write_new(target, value)
            self.assertEqual(json.loads(target.read_bytes()), value)
            self.assertEqual(proof["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            original = target.read_bytes()
            with self.assertRaises(FileExistsError):
                module.write_new(target, {"replacement": True})
            self.assertEqual(target.read_bytes(), original)

    def test_cli_disabled_or_cloud_authority_refuses_before_request_io(self):
        _, env = fixture()
        for values in ({}, {**env, "K_REVISION": "cloud"}, {**env, "CASEOPS_ENV": "production"}):
            with self.subTest(environment=tuple(values)):
                with patch.dict(os.environ, values, clear=True), patch.object(module, "read_request") as reader:
                    with self.assertRaises(AssertionError):
                        module.main()
                    reader.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
