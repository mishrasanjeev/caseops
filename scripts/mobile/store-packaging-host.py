"""Fixed local packaging child transport; never writes command output to a log.

The reviewed process owner is loaded from retained checked bytes. Actual host
execution is macOS-only. --worker is an internal stdin protocol, not a build API.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time

OWNER_SHA256 = "eaa036bea90b08ba721deb4ece7286bd93315e8d64d128b646d27b78fa2176cf"
FIELDS = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


def need(value, code):
    if not value:
        raise ValueError(code)


def owner_module():
    p = Path(__file__).absolute().with_name("store_process_owner.py")
    def frame(s):
        return tuple(getattr(s, k) for k in FIELDS)

    def namespace():
        return [(str(v), tuple(getattr(v.lstat(), k) for k in FIELDS[:5])) for v in p.parents]
    need(p.resolve() == p, "PACKAGING_OWNER_CANONICAL_REQUIRED")
    parents = namespace()
    fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid()
             and 0 < before.st_size <= 32768 and frame(before) == frame(p.lstat()), "PACKAGING_OWNER_IDENTITY_REQUIRED")
        body = bytearray()
        while len(body) <= before.st_size:
            part = os.read(fd, min(65536, before.st_size + 1 - len(body)))
            if not part:
                break
            body.extend(part)
        need(len(body) == before.st_size and frame(before) == frame(os.fstat(fd)) == frame(p.lstat())
             and p.resolve() == p and namespace() == parents and hashlib.sha256(body).hexdigest() == OWNER_SHA256,
             "PACKAGING_OWNER_CHANGED")
        scope = {"__name__": "caseops_packaging_owned_process"}
        exec(compile(bytes(body), str(p), "exec"), scope)
        return scope
    finally:
        os.close(fd)


def request(raw):
    need(0 < len(raw) <= 2097152, "PACKAGING_CHILD_INPUT_BOUND")
    value = json.loads(raw)
    need(type(value) is dict and set(value) == {"kind", "argv", "cwd", "timeoutSeconds", "outputLimit", "capture", "inputBase64", "sourceBase64"}
         and value["kind"] == "caseops-local-store-child", "PACKAGING_CHILD_REQUEST_REQUIRED")
    need(type(value["argv"]) is list and 1 <= len(value["argv"]) <= 256
         and all(type(s) is str and 0 < len(s) <= 8192 and "\0" not in s for s in value["argv"])
         and Path(value["argv"][0]).is_absolute(), "PACKAGING_CHILD_ARGV_REQUIRED")
    need(type(value["cwd"]) is str and Path(value["cwd"]).is_absolute()
         and str(Path(value["cwd"]).resolve()) == value["cwd"], "PACKAGING_CHILD_CWD_REQUIRED")
    need(type(value["timeoutSeconds"]) in (float, int) and 0 < value["timeoutSeconds"] <= 1800
         and type(value["outputLimit"]) is int and 0 < value["outputLimit"] <= 67108864
         and type(value["capture"]) is bool and type(value["inputBase64"]) is str
         and len(value["inputBase64"]) <= 1398104, "PACKAGING_CHILD_BOUNDS_REQUIRED")
    decoded = base64.b64decode(value["inputBase64"], validate=True)
    need(len(decoded) <= 1048576, "PACKAGING_CHILD_STDIN_BOUND")
    need(type(value["sourceBase64"]) is str and len(value["sourceBase64"]) <= 43692, "PACKAGING_CHILD_SOURCE_BOUND")
    source = base64.b64decode(value["sourceBase64"], validate=True)
    need(len(source) <= 32768 and (value["argv"].count("@CASEOPS_VERIFIED_SOURCE_FD@") == 1 if source else
                                 "@CASEOPS_VERIFIED_SOURCE_FD@" not in value["argv"]), "PACKAGING_CHILD_SOURCE_REQUIRED")
    return value, decoded


class StreamCapture:
    def __init__(self, limit, retain):
        self.limit, self.retain = limit, retain
        self.count, self.hash, self.chunks = 0, hashlib.sha256(), []
        self.exceeded = threading.Event()
        self.failure = None

    def drain(self, stream):
        try:
            while True:
                chunk = stream.read(min(65536, self.limit + 1 - self.count))
                if not chunk:
                    break
                self.count += len(chunk)
                self.hash.update(chunk)
                if self.count > self.limit:
                    self.exceeded.set()
                    break
                elif self.retain:
                    self.chunks.append(chunk)
        except Exception as exc:
            self.failure = type(exc).__name__
        finally:
            stream.close()

    def result(self):
        value = {"bytes": self.count, "sha256": self.hash.hexdigest(), "readErrorClass": self.failure}
        if self.retain and not self.exceeded.is_set() and self.failure is None:
            value["base64"] = base64.b64encode(b"".join(self.chunks)).decode("ascii")
        return value


WORKER_BOOTSTRAP = """import hashlib,os,sys
p,h,source_fd=sys.argv[1:4];source_fd=int(source_fd);b=bytearray()
try:
 while len(b)<=32768:
  v=os.read(source_fd,min(65536,32769-len(b)))
  if not v:break
  b.extend(v)
finally:os.close(source_fd)
if not 0<len(b)<=32768 or hashlib.sha256(b).hexdigest()!=h:raise ValueError('PACKAGING_WORKER_SOURCE_REFUSED')
sys.argv=[p,'--worker']
exec(compile(bytes(b),p,'exec'),{'__name__':'__main__','__file__':p,'__caseops_host_source__':bytes(b)})
"""


def host_program():
    retained = globals().get("__caseops_host_source__")
    if retained is not None:
        need(type(retained) is bytes and 0 < len(retained) <= 32768, "PACKAGING_HOST_SOURCE_REQUIRED")
        return retained
    # Direct test/diagnostic invocation; the public runner always passes its
    # descriptor-verified retained program through a separate inherited pipe.
    p = Path(__file__).absolute()
    need(p.resolve() == p, "PACKAGING_HOST_CANONICAL_REQUIRED")
    fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        a = os.fstat(fd)
        def frame(s):
            return tuple(getattr(s, k) for k in FIELDS)
        need(stat.S_ISREG(a.st_mode) and a.st_uid == os.getuid() and a.st_nlink == 1 and 0 < a.st_size <= 32768
             and frame(a) == frame(p.lstat()), "PACKAGING_HOST_IDENTITY_REQUIRED")
        body = bytearray()
        while len(body) <= a.st_size:
            part = os.read(fd, min(65536, a.st_size+1-len(body)))
            if not part:
                break
            body.extend(part)
        need(len(body) == a.st_size and frame(a) == frame(os.fstat(fd)) == frame(p.lstat())
             and p.resolve() == p, "PACKAGING_HOST_CHANGED")
        return bytes(body)
    finally:
        os.close(fd)


def run(value, module=None):
    need(sys.platform == "darwin" or module is not None, "PACKAGING_MACOS_HOST_REQUIRED")
    module = module or owner_module()
    end = time.monotonic() + value["timeoutSeconds"] + 30
    source = host_program()
    status_read, status_write = os.pipe()
    try:
        source_read, source_write = os.pipe()
    except Exception:
        os.close(status_read)
        os.close(status_write)
        raise
    argv = [sys.executable, "-c", WORKER_BOOTSTRAP, str(Path(__file__).resolve()), hashlib.sha256(source).hexdigest(), str(source_read)]
    env = dict(os.environ, CASEOPS_STORE_CHILD_STATUS_FD=str(status_write))
    try:
        proc = subprocess.Popen(argv, cwd=value["cwd"], env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, pass_fds=(status_write, source_read))
    except Exception:
        os.close(status_read)
        os.close(status_write)
        os.close(source_read)
        os.close(source_write)
        raise
    os.close(status_write)
    os.close(source_read)
    group = None
    streams = [StreamCapture(min(value["outputLimit"], 1048576) if value["capture"] else value["outputLimit"], value["capture"]) for _ in range(2)]
    readers = [threading.Thread(target=stream.drain, args=(pipe,), daemon=True)
               for stream, pipe in zip(streams, (proc.stdout, proc.stderr), strict=True)]
    for thread in readers:
        thread.start()
    result = {"exitCode": None, "timedOut": False, "outputExceeded": False, "failureClass": None,
              "workerDispatched": False, "cleanup": {"complete": False}}
    try:
        group = module["OwnedGroup"](proc, argv, value["cwd"], deadline=end)
        count = 0
        while count < len(source):
            amount = os.write(source_write, source[count:])
            need(amount > 0, "PACKAGING_WORKER_SOURCE_NO_PROGRESS")
            count += amount
        os.close(source_write)
        source_write = None
        proc.stdin.write((json.dumps(value) + "\n").encode())
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
            group.sample(child_end)
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
        if group is not None:
            result["cleanup"] = group.finish(end)
        else:
            # No unproved PID/group is signalled. Preserve an unknown launch.
            result["cleanup"] = {"complete": False, "errorCode": "PACKAGING_WORKER_OWNERSHIP_UNPROVEN", "signals": []}
        for thread in readers:
            thread.join(timeout=max(0, min(1, end - time.monotonic())))
        result["streamCleanupComplete"] = all(not t.is_alive() for t in readers)
        result["stdout"], result["stderr"] = (s.result() for s in streams)
        result["workerExitCode"] = proc.poll()
        os.set_blocking(status_read, False)
        try:
            raw = os.read(status_read, 129)
            status = json.loads(raw) if raw else None
            if type(status) is dict and set(status) == {"exitCode"} and type(status["exitCode"]) is int:
                result["exitCode"] = status["exitCode"]
            else:
                result["exitCode"] = None
        except (OSError, ValueError):
            result["exitCode"] = None
        finally:
            os.close(status_read)
        result["outputExceeded"] = result["outputExceeded"] or any(s.exceeded.is_set() for s in streams)
    return result


def source_descriptor(source, cwd):
    source_file = tempfile.TemporaryFile(mode="w+b", dir=cwd)
    try:
        # JDK source-file mode seeks. A pipe fails before the verifier runs.
        # This anonymous owned regular file has no pathname to replace; its
        # checked retained bytes and the same seekable FD reach the JVM.
        fd = source_file.fileno()
        count = 0
        while count < len(source):
            amount = os.write(fd, source[count:])
            need(amount > 0, "PACKAGING_TOOL_SOURCE_NO_PROGRESS")
            count += amount
        os.fsync(fd)
        s = os.fstat(fd)
        need(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and s.st_size == len(source)
             and s.st_nlink == 0 and s.st_mode & 0o077 == 0, "PACKAGING_TOOL_SOURCE_IDENTITY")
        os.lseek(fd, 0, 0)
        body = bytearray()
        while len(body) <= len(source):
            part = os.read(fd, len(source)+1-len(body))
            if not part:
                break
            body.extend(part)
        need(bytes(body) == source and all(getattr(os.fstat(fd), k) == getattr(s, k) for k in FIELDS), "PACKAGING_TOOL_SOURCE_CHANGED")
        os.lseek(fd, 0, 0)
        source_file.caseops_frame = tuple(getattr(s, k) for k in FIELDS)
        return source_file
    except BaseException:
        source_file.close()
        raise


def worker(value, data):
    # The persistent leader was admitted before this request was written. A
    # short-lived tool remains in that leader's already owned process group.
    source = base64.b64decode(value["sourceBase64"], validate=True)
    source_file = None
    argv = list(value["argv"])
    if source:
        source_file = source_descriptor(source, value["cwd"])
        argv[argv.index("@CASEOPS_VERIFIED_SOURCE_FD@")] = "/dev/fd/" + str(source_file.fileno())
    try:
        proc = subprocess.Popen(argv, cwd=value["cwd"], stdin=subprocess.PIPE, pass_fds=(() if source_file is None else (source_file.fileno(),)))
        proc.communicate(input=data)
        fd = int(os.environ["CASEOPS_STORE_CHILD_STATUS_FD"])
        try:
            os.write(fd, json.dumps({"exitCode": proc.returncode}).encode())
        finally:
            os.close(fd)
        if source_file is not None:
            fd = source_file.fileno()
            need(tuple(getattr(os.fstat(fd), k) for k in FIELDS) == source_file.caseops_frame, "PACKAGING_TOOL_SOURCE_CHANGED")
            os.lseek(fd, 0, 0)
            body = bytearray()
            while len(body) <= len(source):
                part = os.read(fd, len(source)+1-len(body))
                if not part:
                    break
                body.extend(part)
            need(bytes(body) == source, "PACKAGING_TOOL_SOURCE_CHANGED")
    finally:
        if source_file is not None:
            source_file.close()
    return proc.returncode


def main():
    try:
        value, data = request(sys.stdin.buffer.readline(2097153))
        if sys.argv[1:] == ["--worker"]:
            return worker(value, data)
        need(sys.argv[1:] == [], "PACKAGING_HOST_ARGUMENTS_REFUSED")
        result = run(value)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"failureClass": type(exc).__name__, "errorCode": "PACKAGING_HOST_REFUSED",
                          "exitCode": None, "cleanup": {"complete": False}}))
        return 70


if __name__ == "__main__":
    sys.exit(main())
