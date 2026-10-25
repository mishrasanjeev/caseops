"""Offline import/authority regressions; no Docker, database or fixture mutation."""

import builtins
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location("local_owner", Path(__file__).with_name("local-owner.py"))
owner_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner_module)
MUTATION_MODULES = {
    "caseops_api.schemas.matters", "caseops_api.services.identity",
    "caseops_api.services.matter_access", "caseops_api.services.matters",
}


class Column:
    def __eq__(self, value):
        return (self, value)


class Query:
    def __init__(self, selected):
        self.selected = selected

    def where(self, *_conditions):
        return self

    def order_by(self, *_columns):
        return self

    def limit(self, count):
        self.count = count
        return self


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    return result


class OwnerImportTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="caseops-owner-unit-")))
        self.company = SimpleNamespace(id="unit-company", slug="test-legal", is_active=True)
        self.owner = SimpleNamespace(id="unit-owner", role="owner", is_active=True, user=SimpleNamespace(is_active=True))
        self.member = SimpleNamespace(id="unit-member", role="member", is_active=True, user=SimpleNamespace(is_active=True))
        self.target = SimpleNamespace(id="unit-target", matter_code="UNIT-TARGET", status="intake",
            is_active=True, lifecycle_version=0, updated_at="unit-updated", restricted_access=True,
            assignee_membership_id=self.owner.id)
        self.notes = []
        self.access = True
        self.queries = []
        self.session = Mock()
        self.session.__enter__ = Mock(return_value=self.session)
        self.session.__exit__ = Mock(return_value=False)
        self.session.scalar.side_effect = self.scalar
        self.session.scalars.side_effect = lambda query: self.note_query(query)
        self.factory = Mock(return_value=Mock(return_value=self.session))
        self.context = Mock(side_effect=self.session_context)
        self.transition = Mock(side_effect=self.dispose)
        self.remove = Mock(side_effect=self.revoke)
        self.can_access = Mock(side_effect=lambda *_args, **_kwargs: self.access)
        self.schema = Mock(side_effect=lambda **values: SimpleNamespace(**values))
        self.mappers = Mock()
        self.company_model = type("Company", (), {"id": Column()})
        self.member_model = type("CompanyMembership", (), {"id": Column(), "company_id": Column()})
        self.matter_model = type("Matter", (), {"id": Column(), "company_id": Column()})
        self.note_model = type("MatterNote", (), {"id": Column(), "matter_id": Column()})
        modules = {
            "sqlalchemy": module("sqlalchemy", select=Query, text=lambda value: value),
            "sqlalchemy.engine": module("sqlalchemy.engine", make_url=lambda _url: SimpleNamespace(host="postgres", database="caseops_mobile")),
            "sqlalchemy.orm": module("sqlalchemy.orm", configure_mappers=self.mappers),
            "caseops_api": module("caseops_api"), "caseops_api.db": module("caseops_api.db"),
            "caseops_api.schemas": module("caseops_api.schemas"), "caseops_api.services": module("caseops_api.services"),
            "caseops_api.db.models": module("caseops_api.db.models", Company=self.company_model,
                CompanyMembership=self.member_model, Matter=self.matter_model, MatterNote=self.note_model,
                MembershipRole=SimpleNamespace(OWNER="owner")),
            "caseops_api.db.session": module("caseops_api.db.session", get_session_factory=self.factory),
            "caseops_api.schemas.matters": module("caseops_api.schemas.matters", MatterLifecycleStatusRequest=self.schema),
            "caseops_api.services.identity": module("caseops_api.services.identity", get_session_context=self.context),
            "caseops_api.services.matter_access": module("caseops_api.services.matter_access", can_access=self.can_access, remove_access_grant=self.remove),
            "caseops_api.services.matters": module("caseops_api.services.matters", transition_matter_lifecycle_status=self.transition),
        }
        self.stack.enter_context(patch.dict(sys.modules, modules))
        self.stack.enter_context(patch.dict(owner_module.os.environ, {"CASEOPS_ENV": "local", "CASEOPS_DATABASE_URL": "unit-only"}))
        self.stack.enter_context(patch.object(owner_module, "ROOT", self.root))
        self.stack.enter_context(patch.object(owner_module, "digest", return_value="unit-source-hash"))
        self.stack.enter_context(patch.object(owner_module.time, "time", return_value=100))
        self.stack.enter_context(patch.object(owner_module.signal, "SIGALRM", 14, create=True))
        self.stack.enter_context(patch.object(owner_module.signal, "ITIMER_REAL", 0, create=True))
        self.signal = self.stack.enter_context(patch.object(owner_module.signal, "signal"))
        self.timer = self.stack.enter_context(patch.object(owner_module.signal, "setitimer", create=True))
        self.build = {"release_sha": "d" * 40, "revision": "unit-api"}
        self.urlopen = self.stack.enter_context(patch.object(owner_module, "urlopen", side_effect=lambda *_args, **_kwargs: io.StringIO(json.dumps(self.build))))
        self.binding = {"backendSha": "d" * 40, "backendRevision": "unit-api", "pythonSha256": "unit-source-hash",
            "extensionFile": "unit-extension.json", "extensionSha256": "unit-extension-hash",
            "syntheticDataOnly": True, "environment": "docker-integration", "project": "unit-project",
            "apiContainerId": "a" * 64, "apiImage": "sha256:" + "b" * 64, "moduleSha256": "c" * 64}
        self.extension = {"companyId": self.company.id, "ownerMembershipId": self.owner.id,
            "membershipId": self.member.id, "accessGrantId": "unit-grant",
            **{kind: {"id": self.target.id, "identityLabel": self.target.matter_code} for kind in ("lifecycleMatter", "accessMatter")}}
        self.stack.enter_context(patch.object(owner_module, "load_hashed", side_effect=lambda name, _hash: self.binding if name == "unit-binding.json" else self.extension))
        self.imports = []
        self.forbid_mutations = False
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            self.imports.append(name)
            if self.forbid_mutations and name in MUTATION_MODULES:
                raise AssertionError(f"READ_IMPORTED_MUTATION_DEPENDENCY:{name}")
            return original_import(name, *args, **kwargs)

        self.stack.enter_context(patch("builtins.__import__", side_effect=guarded_import))

    def scalar(self, query):
        self.queries.append(query)
        self.assertEqual(query.count, 1)
        if query.selected is self.company_model:
            return self.company
        if query.selected is self.member_model:
            return self.owner if sum(q.selected is self.member_model for q in self.queries) % 2 else self.member
        self.assertIs(query.selected, self.matter_model)
        return self.target

    def note_query(self, query):
        self.assertIs(query.selected, self.note_model.id)
        self.assertEqual(query.count, 101)
        return self.notes

    def session_context(self, _session, membership_id):
        membership = self.owner if membership_id == self.owner.id else self.member
        assert membership.is_active and membership.user.is_active and self.company.is_active
        return SimpleNamespace(membership_id=membership_id)

    def dispose(self, _session, **kwargs):
        self.assertEqual(kwargs["context"].membership_id, self.owner.id)
        self.assertEqual(kwargs["matter_id"], self.target.id)
        self.assertEqual(kwargs["payload"].to_status, "disposed")
        self.assertEqual(kwargs["payload"].expected_from_status, "intake")
        self.assertEqual(kwargs["payload"].expected_updated_at, "unit-updated")
        self.target.status, self.target.is_active, self.target.lifecycle_version = "disposed", False, 1

    def revoke(self, _session, **kwargs):
        self.assertEqual(kwargs["context"].membership_id, self.owner.id)
        self.assertEqual((kwargs["matter_id"], kwargs["grant_id"]), (self.target.id, "unit-grant"))
        self.access = False

    def invoke(self, operation, **overrides):
        request = {"operation": operation, "targetId": self.target.id, "runId": "unit-run",
            "requestId": "unit-request", "backendSha": "d" * 40, "marker": "no-paid-providers",
            "deadlineMs": 108000, "bindingFile": "unit-binding.json", "bindingSha256": "unit-binding-hash", **overrides}
        output = io.StringIO()
        with patch.object(owner_module.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode()))), redirect_stdout(output):
            owner_module.main()
        self.assertEqual([call.args for call in self.timer.call_args_list],
            [(owner_module.signal.ITIMER_REAL, 8), (owner_module.signal.ITIMER_REAL, 0)])
        self.urlopen.assert_called_once_with("http://127.0.0.1:8000/api/build", timeout=0.7)
        self.assertEqual([args.args[0] for args in self.session.execute.call_args_list],
            ["SET LOCAL statement_timeout = '1200ms'", "SET LOCAL lock_timeout = '800ms'"])
        for key, expected in (("CONNECT_TIMEOUT_SECONDS", "1"), ("STATEMENT_TIMEOUT_MS", "1200"),
                              ("LOCK_TIMEOUT_MS", "800"), ("IDLE_TRANSACTION_TIMEOUT_MS", "3000")):
            self.assertEqual(owner_module.os.environ["CASEOPS_DB_" + key], expected)
        return json.loads(output.getvalue())

    def assert_read(self, operation):
        self.forbid_mutations = True
        result = self.invoke(operation)["result"]
        self.assertEqual(result, {"status": "intake", "isActive": True, "lifecycleVersion": 0, "noteIds": []})
        self.assertFalse(MUTATION_MODULES.intersection(self.imports))
        self.assertEqual(list(self.root.glob("owner-attempt-*.json")), [])
        self.context.assert_not_called()
        self.transition.assert_not_called()
        self.remove.assert_not_called()
        self.session.rollback.assert_called_once()
        self.session.commit.assert_not_called()

    def test_read_matter_state_never_imports_mutation_or_identity_services(self):
        self.assert_read("readMatterState")

    def test_read_note_state_never_imports_mutation_or_identity_services(self):
        self.assert_read("readNoteState")

    def test_dispose_still_uses_canonical_transition_and_locked_version_payload(self):
        result = self.invoke("disposeMatter")["result"]
        self.assertEqual((result["status"], result["lifecycleVersion"]), ("disposed", 1))
        self.transition.assert_called_once()
        self.schema.assert_called_once()
        self.context.assert_called_once_with(self.session, self.owner.id)
        self.assertIn("caseops_api.services.matters", self.imports)
        self.assertNotIn("caseops_api.services.matter_access", self.imports)
        self.assertEqual(len(list(self.root.glob("owner-attempt-*.json"))), 1)

    def test_revoke_still_uses_canonical_grant_service_and_postchecks_access(self):
        self.assertEqual(self.invoke("revokeMatterAccess")["result"], {"accessAllowed": False})
        self.remove.assert_called_once()
        self.assertEqual(self.can_access.call_count, 2)
        self.assertIn("caseops_api.services.matter_access", self.imports)
        self.assertNotIn("caseops_api.services.matters", self.imports)
        self.assertNotIn("caseops_api.schemas.matters", self.imports)
        self.assertEqual(len(list(self.root.glob("owner-attempt-*.json"))), 1)

    def test_read_rejects_inactive_owner_user(self):
        self.owner.user.is_active = False
        with self.assertRaises(AssertionError):
            self.invoke("readMatterState")
        self.assertEqual(list(self.root.glob("owner-evidence-*.json")), [])

    def test_read_rejects_inactive_company(self):
        self.company.is_active = False
        with self.assertRaises(AssertionError):
            self.invoke("readNoteState")
        self.assertEqual(list(self.root.glob("owner-evidence-*.json")), [])

    def test_expired_request_is_rejected_before_imports_sql_or_claims(self):
        with self.assertRaisesRegex(AssertionError, "Expired owner command"):
            self.invoke("disposeMatter", deadlineMs=100000)
        self.factory.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_uncertain_mutation_keeps_exclusive_claim_and_is_never_replayed(self):
        self.transition.side_effect = RuntimeError("UNIT_UNCERTAIN_MUTATION")
        with self.assertRaisesRegex(RuntimeError, "UNIT_UNCERTAIN_MUTATION"):
            self.invoke("disposeMatter")
        self.assertEqual(len(list(self.root.glob("owner-attempt-*.json"))), 1)
        with self.assertRaises(FileExistsError):
            self.invoke("disposeMatter", requestId="unit-second-request")
        self.transition.assert_called_once()

    def test_read_note_history_retains_the_existing_100_row_bound(self):
        self.notes = [f"note-{index}" for index in range(101)]
        with self.assertRaisesRegex(AssertionError, "note-state bound"):
            self.invoke("readNoteState")
        self.assertEqual(list(self.root.glob("owner-evidence-*.json")), [])

    def test_signal_expiry_stays_fail_closed(self):
        with self.assertRaisesRegex(TimeoutError, "OWNER_CONTROL_DEADLINE"):
            owner_module.expired(None, None)

    def startup(self):
        return {"type": "prepare", "workerId": "a" * 24, "requestId": "b" * 24,
            "bindingFile": "unit-binding.json", "bindingSha256": "unit-binding-hash", "backendSha": "d" * 40,
            "marker": "no-paid-providers", "deadlineMs": 130000,
            **{key: self.binding[key] for key in ("apiContainerId", "apiImage", "project")}}

    def protocol_worker(self):
        return {"workerId": "a" * 24, "readySha256": "e" * 64, "readyFile": "unit-ready.json", "commandCount": 0}

    def protocol_request(self, index=1, **values):
        return {"type": "control", "workerId": "a" * 24, "readySha256": "e" * 64,
            "requestId": f"{index:024x}", "operation": "readMatterState", "deadlineMs": 108000, **values}

    def protocol_run(self, requests):
        stream = io.BytesIO(b"".join(json.dumps(row).encode() + b"\n" for row in [self.startup(), *requests]))
        output = io.StringIO()
        worker = self.protocol_worker()
        with patch.object(owner_module, "prepare_worker", return_value=worker), patch.object(
            owner_module, "run_operation", return_value={"evidenceFile": "unit-evidence.json", "result": {}}) as execute:
            owner_module.worker_main(stream, output)
        return execute, [json.loads(line) for line in output.getvalue().splitlines()], worker

    def test_readiness_preloads_all_services_and_mappers_with_only_a_rolled_back_read(self):
        worker = owner_module.prepare_worker(self.startup())
        self.assertTrue(MUTATION_MODULES.issubset(self.imports))
        self.mappers.assert_called_once()
        self.context.assert_not_called()
        self.transition.assert_not_called()
        self.remove.assert_not_called()
        self.session.rollback.assert_called_once()
        self.assertEqual([call.args[0] for call in self.session.execute.call_args_list], [
            "SET TRANSACTION READ ONLY", "SET LOCAL statement_timeout = '1200ms'",
            "SET LOCAL lock_timeout = '800ms'", "SELECT 1"])
        self.assertEqual(worker["maxCommands"], 16)
        self.assertEqual(worker["operationDeadlineMs"], 8000)
        self.assertEqual(worker["lifetimeSeconds"], 1200)
        proof = json.loads((self.root / worker["readyFile"]).read_text())
        self.assertFalse(proof["databaseSessionRetained"])
        self.assertEqual(proof["bindingSha256"], "unit-binding-hash")
        self.assertEqual(list(self.root.glob("owner-attempt-*.json")), [])

    def test_readiness_timeout_never_emits_ready_or_attempts_a_mutation(self):
        self.mappers.side_effect = TimeoutError("UNIT_READINESS_TIMEOUT")
        with self.assertRaisesRegex(TimeoutError, "READINESS_TIMEOUT"):
            owner_module.prepare_worker(self.startup())
        self.assertEqual(list(self.root.glob("owner-ready-*.json")), [])
        self.assertEqual(list(self.root.glob("owner-attempt-*.json")), [])
        self.transition.assert_not_called()
        self.remove.assert_not_called()

    def test_worker_line_bound_rejects_oversize_partial_invalid_and_nonobject_frames(self):
        for raw in (b"x" * 4096 + b"\n", b"{}", b"not-json\n", b"[]\n"):
            with self.subTest(rawLength=len(raw)), self.assertRaises((AssertionError, ValueError)):
                owner_module.bounded_line(io.BytesIO(raw))
        self.assertIsNone(owner_module.bounded_line(io.BytesIO()))
        self.assertEqual(owner_module.bounded_line(io.BytesIO(b"{}\n")), {})

    def test_worker_16_sequential_commands_keep_all_results_and_allow_close(self):
        execute, rows, worker = self.protocol_run([
            *(self.protocol_request(index) for index in range(1, 17)), self.protocol_request(17, type="close")])
        self.assertEqual(execute.call_count, 16)
        self.assertEqual(worker["commandCount"], 16)
        self.assertEqual([row["commandIndex"] for row in rows if row["type"] == "result"], list(range(1, 17)))
        self.assertEqual(rows[-1]["type"], "closed")
        self.assertTrue(all(call.args[1] <= 1200 for call in self.timer.call_args_list))

    def test_worker_command_17_is_rejected_without_execution_or_replay(self):
        requests = [self.startup(), *(self.protocol_request(index) for index in range(1, 18))]
        stream = io.BytesIO(b"".join(json.dumps(row).encode() + b"\n" for row in requests))
        with patch.object(owner_module, "prepare_worker", return_value=self.protocol_worker()), patch.object(
            owner_module, "run_operation", return_value={}) as execute:
            with self.assertRaisesRegex(AssertionError, "command bound"):
                owner_module.worker_main(stream, io.StringIO())
        self.assertEqual(execute.call_count, 16)

    def test_worker_unknown_operation_fails_closed_before_execution(self):
        with self.assertRaisesRegex(AssertionError, "Unknown worker operation"):
            self.protocol_run([self.protocol_request(operation="reopenMatter")])
        self.factory.assert_not_called()

    def test_worker_wrong_readiness_hash_fails_closed_before_execution(self):
        with self.assertRaises(AssertionError):
            self.protocol_run([self.protocol_request(readySha256="f" * 64)])
        self.factory.assert_not_called()

    def test_worker_disconnect_retains_no_open_session_or_mutation(self):
        execute, rows, _worker = self.protocol_run([])
        execute.assert_not_called()
        self.assertEqual([row["type"] for row in rows], ["ready"])
        self.factory.assert_not_called()
        self.assertEqual(self.timer.call_args.args, (owner_module.signal.ITIMER_REAL, 0))

    def test_worker_close_is_acknowledged_without_running_a_command(self):
        execute, rows, _worker = self.protocol_run([self.protocol_request(type="close")])
        execute.assert_not_called()
        self.assertEqual([row["type"] for row in rows], ["ready", "closed"])
        self.assertEqual(rows[-1]["requestId"], self.protocol_request()["requestId"])

    def test_worker_lifetime_expires_before_a_command_and_clears_timer(self):
        with patch.object(owner_module.time, "monotonic", side_effect=[0, 1201]):
            with self.assertRaisesRegex(AssertionError, "lifetime expired"):
                self.protocol_run([self.protocol_request()])
        self.assertEqual(self.timer.call_args.args, (owner_module.signal.ITIMER_REAL, 0))

    def warm_request(self, **values):
        return {"operation": "disposeMatter", "targetId": self.target.id, "runId": "unit-warm-run",
            "requestId": "unit-warm-request", "backendSha": "d" * 40, "marker": "no-paid-providers",
            "deadlineMs": 108000, "bindingFile": "unit-binding.json", "bindingSha256": "unit-binding-hash",
            "workerId": "a" * 24, "readySha256": "unit-source-hash", **values}

    def warm_context(self):
        return {"workerId": "a" * 24, "readySha256": "unit-source-hash", "readyFile": "unit-ready.json",
            "bindingFile": "unit-binding.json", "bindingSha256": "unit-binding-hash", "commandCount": 1}

    def test_warm_uncertain_mutation_retains_claim_and_cannot_be_replayed(self):
        self.transition.side_effect = RuntimeError("UNIT_WARM_UNCERTAIN_MUTATION")
        with self.assertRaisesRegex(RuntimeError, "WARM_UNCERTAIN"):
            owner_module.run_operation(self.warm_request(), self.warm_context())
        self.assertEqual(len(list(self.root.glob("owner-attempt-*.json"))), 1)
        with self.assertRaises(FileExistsError):
            owner_module.run_operation(self.warm_request(requestId="unit-warm-second"), self.warm_context())
        self.transition.assert_called_once()

    def test_warm_request_rechecks_readiness_hash_before_build_or_database(self):
        with patch.object(owner_module, "digest", side_effect=lambda path: "changed-ready-proof"
                          if path.name == "unit-ready.json" else "unit-source-hash"):
            with self.assertRaisesRegex(AssertionError, "readiness evidence changed"):
                owner_module.run_operation(self.warm_request(), self.warm_context())
        self.factory.assert_not_called()
        self.urlopen.assert_not_called()
        self.assertEqual(list(self.root.glob("owner-attempt-*.json")), [])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OwnerImportTests)
    identities = [test.id() for test in suite]
    result = unittest.TestResult()
    suite.run(result)
    print(json.dumps({"offlineOnly": True, "collected": identities, "testsRun": result.testsRun,
        "successful": result.wasSuccessful(), "skipped": result.skipped,
        "failures": [{"id": case.id(), "traceback": detail} for case, detail in result.failures],
        "errors": [{"id": case.id(), "traceback": detail} for case, detail in result.errors]}))
    sys.exit(0 if result.wasSuccessful() else 1)
