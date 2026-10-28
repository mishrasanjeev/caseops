"""Synthetic source/FS/clock doubles only; no service, database or worker run."""
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("local_inbox_unit", Path(__file__).with_name("local-v1-inbox.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
U = lambda n: f"00000000-0000-4000-8000-{n:012d}"


def setup():
    clock = [1793059200.0]
    hearing_at = datetime.fromtimestamp(clock[0], UTC) + timedelta(hours=1, seconds=45)
    body = {"hearing_on": hearing_at.date().isoformat(), "hearing_time": hearing_at.time().replace(tzinfo=None).isoformat(), "timezone": "UTC", "time_status": "exact",
            "reminder_channels": ["in_app"], "reminder_offsets_hours": [1], "reminder_recipient_membership_ids": [U(2)], "notification_critical": False}
    request = {"readyForLive": True, "preparedOnly": False, "environment": "docker-integration", "syntheticDataOnly": True,
               "noPaidMarker": M.MARKER, "manualReceiptInsertion": False, "sourceSha": "a" * 40, "runId": "v1-" + U(9),
               "companyId": U(1), "membershipId": U(2), "matterId": U(3), "hearingId": U(4), "phaseStartedMilliseconds": int(clock[0] * 1000),
               "hearingAcknowledgement": {"method": "POST", "route": f"/api/matters/{U(3)}/hearings", "status": 200, "body": body,
                    "value": {"id": U(4), "matter_id": U(3), "hearing_on": body["hearing_on"], "hearing_time": body["hearing_time"], "reminder_policy": {"channels": ["in_app"], "critical": False}}}}
    env = {"CASEOPS_MOBILE_V1_INBOX_FIXTURE": "1", "CASEOPS_ENV": "local", "CASEOPS_RELEASE_SHA": "a" * 40}
    events, claims, calls = [], set(), []
    state = {"delivered": False, "closed": False, "transaction": False}
    def claim(value):
        assert value not in claims, "already consumed"
        claims.add(value)
    def factory(_request, charged, deadline):
        class Runtime:
            def observe(self, after):
                state["transaction"] = True
                try:
                    charged()
                    return {"intentId": U(5), "companyId": U(1), "membershipId": U(2), "hearingId": U(4), "channel": "in_app",
                            "scheduledFor": datetime.fromtimestamp(request["phaseStartedMilliseconds"] / 1000 + 45, UTC).isoformat(),
                            "status": "delivered" if state["delivered"] else "queued", "notificationId": U(6) if state["delivered"] else None,
                            "deliveredAt": datetime.fromtimestamp(clock[0], UTC).isoformat() if state["delivered"] else None,
                            "attempts": int(state["delivered"]), "notificationCompanyId": U(1) if after else None,
                            "notificationMembershipId": U(2) if after else None, "notificationMatterId": U(3) if after else None}
                finally:
                    state["transaction"] = False
            def deliver(self, identity):
                calls.append(identity); state["delivered"] = True
                return {"delivered": True, "externalCalls": 0}
            def close(self): state["closed"] = True
        return Runtime()
    def sleep(seconds):
        assert state["transaction"] is False
        clock[0] += seconds
    kwargs = {"environment": env, "factory": factory, "claim": claim, "persist": events.append, "now": lambda: clock[0], "sleep": sleep}
    return request, kwargs, clock, events, calls, state


# Exact pre-peer function bytes, retained as the negative namespace control.
FORMER_PUBLIC_BYTES = 'def public_bytes(reference, root):\n    path = Path(reference["path"])\n    assert path.is_absolute() and path == path.resolve() and root in path.parents\n    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)\n    try:\n        before, named = os.fstat(descriptor), os.lstat(path)\n        keys = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")\n        assert stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(named.st_mode)\n        assert all(getattr(before, key) == getattr(named, key) for key in keys)\n        assert 0 < before.st_size <= LIMITS["publicBytes"]\n        chunks, size = [], 0\n        while size <= LIMITS["publicBytes"]:\n            block = os.read(descriptor, min(65536, LIMITS["publicBytes"] + 1 - size))\n            if not block:\n                break\n            chunks.append(block)\n            size += len(block)\n        after, final = os.fstat(descriptor), os.lstat(path)\n        assert size == before.st_size and size <= LIMITS["publicBytes"]\n        assert not stat.S_ISLNK(final.st_mode) and all(getattr(before, key) == getattr(after, key) == getattr(final, key) for key in keys)\n        data = b"".join(chunks)\n        assert hashlib.sha256(data).hexdigest() == reference["sha256"]\n        return data\n    finally:\n        os.close(descriptor)\n\n'


class InboxWorkerControls(unittest.TestCase):
    def test_default_disabled_before_claim_factory_or_import(self):
        request, args, _clock, events, calls, state = setup()
        args["environment"] = {}
        with self.assertRaisesRegex(AssertionError, "V1_INBOX_DISABLED"):
            M.run_inbox_worker(request, **args)
        self.assertEqual(events, []); self.assertEqual(calls, []); self.assertFalse(state["closed"])

    def test_cloud_wrong_source_or_unowned_hearing_request_refuses_before_factory(self):
        for alter in (lambda r, e: e.update(K_SERVICE="cloud"), lambda r, e: e.update(CASEOPS_ENV="production"),
                      lambda r, e: e.update(CASEOPS_RELEASE_SHA="b" * 40), lambda r, e: r.update(readyForLive=False),
                      lambda r, e: r["hearingAcknowledgement"]["body"].update(reminder_channels=["email"]),
                      lambda r, e: r["hearingAcknowledgement"]["body"].update(reminder_recipient_membership_ids=[U(99)])):
            request, args, _clock, events, calls, state = setup(); alter(request, args["environment"])
            with self.assertRaises(AssertionError): M.run_inbox_worker(request, **args)
            self.assertEqual(events, []); self.assertEqual(calls, []); self.assertFalse(state["closed"])

    def test_real_due_wait_model_closes_readonly_transactions_then_calls_canonical_worker_once(self):
        request, args, clock, events, calls, state = setup()
        receipt = M.run_inbox_worker(request, **args)
        self.assertEqual(receipt["notificationId"], U(6)); self.assertEqual(receipt["externalCalls"], 0)
        self.assertEqual(receipt["workerExecutions"], 1); self.assertEqual(calls, [U(5)]); self.assertTrue(state["closed"])
        self.assertEqual(clock[0], request["phaseStartedMilliseconds"] / 1000 + 45)
        self.assertEqual(receipt["observerStatements"], 5)
        self.assertEqual(events[-1]["type"], "v1_inbox_worker_completed")
        with self.assertRaisesRegex(AssertionError, "already consumed"): M.run_inbox_worker(request, **args)
        self.assertEqual(calls, [U(5)])

    def test_unknown_worker_result_is_consumed_and_never_retried(self):
        request, args, _clock, events, calls, state = setup(); factory = args["factory"]
        def failed(*values):
            runtime = factory(*values)
            def deliver(identity): calls.append(identity); raise TimeoutError("synthetic-only")
            runtime.deliver = deliver
            return runtime
        args["factory"] = failed
        with self.assertRaisesRegex(RuntimeError, "^V1_INBOX_WORKER_INCOMPLETE_NO_REPLAY$"): M.run_inbox_worker(request, **args)
        self.assertEqual(calls, [U(5)]); self.assertTrue(events[-1]["mutationUncertain"]); self.assertTrue(state["closed"])

    def test_observer_work_bound_refuses_before_worker(self):
        request, args, _clock, events, calls, _state = setup()
        def over(_request, charged, _deadline):
            for _ in range(21): charged()
        args["factory"] = over
        with self.assertRaisesRegex(RuntimeError, "V1_INBOX_WORKER_INCOMPLETE_NO_REPLAY"): M.run_inbox_worker(request, **args)
        self.assertEqual(calls, []); self.assertFalse(events[-1]["workerStarted"])

    def test_shared_deadline_includes_readback_and_cannot_publish_late_success(self):
        request, args, clock, events, calls, _state = setup(); factory = args["factory"]
        def late(*values):
            runtime = factory(*values); original = runtime.deliver
            def deliver(identity):
                result = original(identity); clock[0] += 50; return result
            runtime.deliver = deliver
            return runtime
        args["factory"] = late
        with self.assertRaisesRegex(RuntimeError, "V1_INBOX_WORKER_INCOMPLETE_NO_REPLAY"): M.run_inbox_worker(request, **args)
        self.assertEqual(calls, [U(5)]); self.assertFalse(any(event["type"] == "v1_inbox_worker_completed" for event in events))

    def test_cleanup_failure_retains_outcome_and_prevents_completion(self):
        request, args, _clock, events, calls, _state = setup(); factory = args["factory"]
        def failing(*values):
            runtime = factory(*values)
            def close(): raise OSError("synthetic-only")
            runtime.close = close
            return runtime
        args["factory"] = failing
        with self.assertRaisesRegex(RuntimeError, "V1_INBOX_CLEANUP_UNVERIFIED_NO_REPLAY"): M.run_inbox_worker(request, **args)
        self.assertEqual(calls, [U(5)]); self.assertEqual(events[-1]["type"], "v1_inbox_cleanup_failed")
        self.assertFalse(any(event["type"] == "v1_inbox_worker_completed" for event in events))

    def test_public_reference_is_bounded_same_descriptor_and_fixed_parse_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); file = root / "public.json"; file.write_bytes(b'{"synthetic":true}')
            reference = {"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
            self.assertEqual(M.public_json(reference, root), {"synthetic": True})
            file.write_bytes(b"{PRIVATE_SYNTHETIC_NOT_FOR_ERROR")
            reference["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "^V1_INBOX_PUBLIC_JSON_REQUIRED$"): M.public_json(reference, root)
            original = M.os.read; total = [0]
            def grow(fd, count):
                if total[0] == 0:
                    with file.open("ab") as stream: stream.write(b"x" * (M.LIMITS["publicBytes"] + 1))
                value = original(fd, count); total[0] += len(value); return value
            with patch.object(M.os, "read", side_effect=grow), self.assertRaises(AssertionError): M.public_json(reference, root)
            self.assertLessEqual(total[0], M.LIMITS["publicBytes"] + 1)


    def test_same_leaf_inode_and_hash_after_parent_symlink_is_refused_and_descriptor_closed(self):
        namespace = {key: getattr(M, key) for key in ("Path", "os", "stat", "hashlib", "LIMITS")}
        exec(compile(FORMER_PUBLIC_BYTES, "<retained-pre-peer-public-reader>", "exec"), namespace)
        for reader, must_refuse in ((namespace["public_bytes"], False), (M.public_bytes, True)):
            with self.subTest(reader="current" if must_refuse else "former"), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                parent, moved = root / "parent", root / "moved"
                parent.mkdir()
                file = parent / "public.json"
                body = b'{"synthetic":true}'
                file.write_bytes(body)
                reference = {"path": str(file), "sha256": hashlib.sha256(body).hexdigest()}
                original_read, original_open = M.os.read, M.os.open
                descriptors, replaced = [], [False]
                def opened(*args, **kwargs):
                    descriptor = original_open(*args, **kwargs)
                    descriptors.append(descriptor)
                    return descriptor
                def swap(fd, count):
                    value = original_read(fd, count)
                    if not replaced[0]:
                        replaced[0] = True
                        parent.rename(moved)
                        parent.symlink_to(moved, target_is_directory=True)
                        self.assertEqual(os.fstat(fd).st_ino, file.stat().st_ino)
                    return value
                with patch.object(M.os, "open", side_effect=opened), patch.object(M.os, "read", side_effect=swap):
                    if must_refuse:
                        with self.assertRaisesRegex(AssertionError, "V1_INBOX_CANONICAL_NAMESPACE_REQUIRED"):
                            reader(reference, root)
                    else:
                        self.assertEqual(reader(reference, root), body)
                self.assertTrue(replaced[0])
                self.assertEqual(len(descriptors), 1)
                with self.assertRaises(OSError): os.fstat(descriptors[0])
                self.assertEqual((moved / "public.json").read_bytes(), body)


if __name__ == "__main__":
    unittest.main()
