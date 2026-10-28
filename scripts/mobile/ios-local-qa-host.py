"""Public local-QA transport; not a store/signing or lifetime process inventory.

The persistent worker is admitted before dispatch. The body uses bounded natural
wait; unchanged eaa cleanup then proves current group/recorded identity absence.
Detached or short-lived unobserved descendants are explicitly outside that proof.
"""
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

HOST_SHA256 = "a7c9d00f7e9c87a3e2a27ce758b49464fa4c50da92001aac02ebb20ee2dc71bb"
FIELDS = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


def need(value, code):
    if not value:
        raise ValueError(code)


def host_dependency(deadline):
    path = Path(__file__).absolute().with_name("store-packaging-host.py")
    need(hasattr(os, "getuid") and path.resolve() == path, "IOS_QA_HOST_CANONICAL")
    def frame(s):
        return tuple(getattr(s, key) for key in FIELDS)
    def parents():
        need(time.monotonic() < deadline, "IOS_QA_DEADLINE")
        rows = []
        for parent in path.parents:
            need(len(rows) < 128 and time.monotonic() < deadline, "IOS_QA_NAMESPACE_BOUND")
            value = parent.lstat()
            need(stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode), "IOS_QA_NAMESPACE")
            rows.append((str(parent), tuple(getattr(value, key) for key in FIELDS[:5])))
        return rows
    namespace = parents()
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    body = bytearray()
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
             and not before.st_mode & 0o022 and 0 < before.st_size <= 32768
             and frame(before) == frame(path.lstat()), "IOS_QA_HOST_IDENTITY")
        while len(body) <= before.st_size:
            need(time.monotonic() < deadline, "IOS_QA_DEADLINE")
            part = os.read(fd, min(65536, before.st_size + 1 - len(body)))
            if not part:
                break
            body.extend(part)
        need(len(body) == before.st_size and frame(before) == frame(os.fstat(fd)) == frame(path.lstat())
             and path.resolve() == path and parents() == namespace
             and hashlib.sha256(body).hexdigest() == HOST_SHA256, "IOS_QA_HOST_CHANGED")
        retained = bytes(body)
        scope = {"__name__": "caseops_retained_store_worker", "__file__": str(path), "__caseops_host_source__": retained}
        exec(compile(retained, str(path), "exec"), scope)
        return SimpleNamespace(**scope)
    finally:
        body[:] = b"\0" * len(body)
        os.close(fd)


def request(raw, host=None):
    need(0 < len(raw) <= 2097152, "IOS_QA_INPUT_BOUND")
    value = json.loads(raw)
    need(type(value) is dict and value.get("kind") == "caseops-local-ios-qa-child"
         and value.get("scope") == "public-local-qa-only"
         and set(value) == {"kind", "scope", "deadlineEpochMs", "argv", "cwd", "timeoutSeconds", "outputLimit", "capture", "inputBase64", "sourceBase64"}, "IOS_QA_REQUEST_REQUIRED")
    need(type(value["deadlineEpochMs"]) is int and 0 < value["deadlineEpochMs"] <= 9007199254740991, "IOS_QA_DEADLINE")
    deadline = min(time.monotonic() + 1830, time.monotonic() + value["deadlineEpochMs"] / 1000 - time.time())
    need(math.isfinite(deadline) and deadline > time.monotonic(), "IOS_QA_DEADLINE")
    host = host or host_dependency(deadline)
    translated = {k: v for k, v in value.items() if k not in ("scope", "deadlineEpochMs")}
    translated["kind"] = "caseops-local-store-child"
    checked, _data = host.request(json.dumps(translated).encode())
    return checked, deadline, host


def run(value, deadline, host, module=None):
    need(sys.platform == "darwin" or module is not None, "IOS_QA_MACOS_REQUIRED")
    module = module or host.owner_module()
    end = min(deadline, time.monotonic() + value["timeoutSeconds"] + 30)
    source = host.host_program()
    status_read, status_write = os.pipe()
    try:
        source_read, source_write = os.pipe()
    except Exception:
        os.close(status_read)
        os.close(status_write)
        raise
    argv = [sys.executable, "-c", host.WORKER_BOOTSTRAP, host.__file__, hashlib.sha256(source).hexdigest(), str(source_read)]
    try:
        proc = subprocess.Popen(argv, cwd=value["cwd"], env=dict(os.environ, CASEOPS_STORE_CHILD_STATUS_FD=str(status_write)),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, pass_fds=(status_write, source_read))
    except Exception:
        for fd in (status_read, status_write, source_read, source_write):
            os.close(fd)
        raise
    os.close(status_write)
    os.close(source_read)
    group = None
    streams = [host.StreamCapture(min(value["outputLimit"], 1048576) if value["capture"] else value["outputLimit"], value["capture"]) for _ in range(2)]
    readers = [threading.Thread(target=s.drain, args=(pipe,), daemon=True) for s, pipe in zip(streams, (proc.stdout, proc.stderr), strict=True)]
    for thread in readers:
        thread.start()
    result = {"exitCode": None, "timedOut": False, "outputExceeded": False, "failureClass": None,
              "workerDispatched": False, "cleanup": {"complete": False}, "scope": "public-local-qa-only",
              "liveDescendantInventory": False, "exhaustiveLifetimeOrDetachedProof": False}
    try:
        group = module["OwnedGroup"](proc, argv, value["cwd"], deadline=end)
        os.set_blocking(source_write, False)
        count = 0
        while count < len(source):
            need(time.monotonic() < end - 30, "IOS_QA_DEADLINE")
            try:
                amount = os.write(source_write, source[count:])
            except BlockingIOError:
                time.sleep(min(0.005, max(0, end - 30 - time.monotonic())))
                continue
            need(amount > 0, "IOS_QA_SOURCE_WRITE_PROGRESS")
            count += amount
        os.close(source_write)
        source_write = None
        payload = (json.dumps(value) + "\n").encode()
        count = 0
        os.set_blocking(proc.stdin.fileno(), False)
        while count < len(payload):
            need(time.monotonic() < end - 30, "IOS_QA_DEADLINE")
            try:
                amount = os.write(proc.stdin.fileno(), payload[count:])
            except BlockingIOError:
                time.sleep(min(0.005, max(0, end - 30 - time.monotonic())))
                continue
            need(amount > 0, "IOS_QA_REQUEST_WRITE_PROGRESS")
            count += amount
        proc.stdin.close()
        result["workerDispatched"] = True
        child_end = min(end - 30, time.monotonic() + value["timeoutSeconds"])
        while proc.poll() is None:
            if time.monotonic() >= child_end:
                result["timedOut"] = True
                break
            if any(s.exceeded.is_set() for s in streams):
                result["outputExceeded"] = True
                break
            # No running sample: Git/Xcode legitimately exec and change cwd.
            # Only strict finish may inventory/admit/signal current descendants.
            time.sleep(min(0.05, max(0, child_end - time.monotonic())))
        result["exitCode"] = proc.poll()
    except Exception as exc:
        result["failureClass"] = type(exc).__name__
    finally:
        if source_write is not None:
            os.close(source_write)
        if not proc.stdin.closed:
            try:
                proc.stdin.close()
            except OSError:
                result["stdinCloseIncomplete"] = True
        result["cleanup"] = group.finish(end) if group is not None else {"complete": False, "signals": [], "errorCode": "IOS_QA_OWNERSHIP_UNPROVEN"}
        for thread in readers:
            thread.join(timeout=max(0, min(1, end - time.monotonic())))
        result["streamCleanupComplete"] = all(not t.is_alive() for t in readers)
        result["stdout"], result["stderr"] = (s.result() for s in streams)
        result["workerExitCode"] = proc.poll()
        os.set_blocking(status_read, False)
        try:
            raw = os.read(status_read, 129)
            status = json.loads(raw) if raw else None
            result["exitCode"] = status["exitCode"] if type(status) is dict and set(status) == {"exitCode"} and type(status["exitCode"]) is int else None
        except (OSError, ValueError):
            result["exitCode"] = None
        finally:
            os.close(status_read)
        result["outputExceeded"] = result["outputExceeded"] or any(s.exceeded.is_set() for s in streams)
    return result


def main():
    try:
        need(not sys.argv[1:], "IOS_QA_ARGUMENTS_REFUSED")
        value, deadline, host = request(sys.stdin.buffer.readline(2097153))
        print(json.dumps(run(value, deadline, host), separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"failureClass": type(exc).__name__, "errorCode": "IOS_QA_HOST_REFUSED", "exitCode": None, "cleanup": {"complete": False}}))
        return 70


if __name__ == "__main__":
    sys.exit(main())
