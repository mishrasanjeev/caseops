"""Finite offline Git inventory transport; no TLS, owner configuration or mutation.

Loaded only from its hash-checked retained source by the generated Git shim.
Executable pathname use is qualified by frozen owned writers and before/after
same-descriptor and namespace observations; this is not atomic exec-by-FD proof.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import select
import stat
import subprocess
import sys
import time

FIELDS = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
IDENTITY = FIELDS[:5]
LIMIT = 1048576


def require(value, code="IOS_GIT_READONLY_REFUSED"):
    if not value:
        raise ValueError(code)


def check(end):
    require(time.monotonic() < end, "IOS_GIT_READONLY_DEADLINE")


def frame(value, keys=FIELDS):
    return tuple(getattr(value, key) for key in keys)


def namespace(file, end):
    check(end)
    require(os.path.isabs(file) and os.path.normpath(file) == file and os.path.realpath(file) == file)
    rows = []
    parent = os.path.dirname(file)
    while True:
        check(end)
        value = os.lstat(parent)
        require(stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode) and len(rows) < 128)
        rows.append((parent, frame(value, IDENTITY)))
        above = os.path.dirname(parent)
        if above == parent:
            return tuple(rows)
        parent = above


class Held:
    def __init__(self, ref, end, maximum, *, system=False, private=False):
        self.fd = None
        self.data = bytearray()
        self.ref = ref
        self.end = end
        try:
            require(type(ref) is dict and set(ref) == {"path", "sha256", "sizeBytes"})
            require(type(ref["sizeBytes"]) is int and 0 < ref["sizeBytes"] <= maximum
                    and type(ref["sha256"]) is str and re.fullmatch("[a-f0-9]{64}", ref["sha256"]))
            self.path = ref["path"]
            check(end)
            self.fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            actual, named = os.fstat(self.fd), os.lstat(self.path)
            self.before, self.named = frame(actual), frame(named)
            require(stat.S_ISREG(actual.st_mode) and not stat.S_ISLNK(named.st_mode) and actual.st_nlink == 1
                    and self.before == self.named and actual.st_size == ref["sizeBytes"]
                    and actual.st_uid in ({os.getuid(), 0} if system else {os.getuid()})
                    and actual.st_mode & 0o022 == 0)
            if private:
                require(actual.st_mode & 0o777 == 0o600)
            self.ns = namespace(self.path, end)
            while len(self.data) < ref["sizeBytes"] + 1:
                check(end)
                block = os.read(self.fd, min(65536, ref["sizeBytes"] + 1 - len(self.data)))
                if not block:
                    break
                self.data.extend(block)
            require(len(self.data) == ref["sizeBytes"] and hashlib.sha256(self.data).hexdigest() == ref["sha256"])
            self.verify()
        except BaseException:
            self.close()
            raise

    def verify(self):
        check(self.end)
        require(frame(os.fstat(self.fd)) == self.before and frame(os.lstat(self.path)) == self.named
                and namespace(self.path, self.end) == self.ns, "IOS_GIT_READONLY_INPUT_CHANGED")

    def close(self):
        self.data[:] = b"\0" * len(self.data)
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def arguments(args):
    require(type(args) is list and 0 < len(args) <= 256
            and all(type(arg) is str and 0 < len(arg.encode()) <= 8192 and not re.search(r"[\0\r\n]", arg) for arg in args))
    def relative(value):
        return (not value.startswith(("-", "/", ":")) and "\\" not in value
                and all(part not in ("", ".", "..") and re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in value.split("/")))
    allowed = (args == ["--version"] or args == ["rev-parse", "HEAD"] or args == ["check-ignore", "-z", "--stdin"]
               or len(args) > 6 and args[:6] == ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--"] and all(map(relative, args[6:]))
               or len(args) > 4 and args[:4] == ["status", "--porcelain", "--untracked-files=all", "--"] and all(map(relative, args[4:])))
    require(allowed, "IOS_GIT_READONLY_ARGUMENTS")
    return ["-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c", "core.hooksPath=/dev/null",
            "-c", "credential.helper=", "-c", "protocol.allow=never", "-c", "protocol.file.allow=never", *args]


def stdin_bytes(fd, end):
    value = bytearray()
    while True:
        check(end)
        ready, _, _ = select.select([fd], [], [], max(0, end-time.monotonic()))
        require(bool(ready), "IOS_GIT_READONLY_STDIN_DEADLINE")
        block = os.read(fd, min(65536, LIMIT+1-len(value)))
        if not block:
            break
        value.extend(block)
        require(len(value) <= LIMIT, "IOS_GIT_READONLY_STDIN_BOUND")
    return value


def repository(root, end):
    require(namespace(root, end) is not None)
    for item in (root, os.path.join(root, ".git")):
        value = os.lstat(item)
        require(stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode) and value.st_uid == os.getuid() and value.st_mode & 0o022 == 0)
    for name in ("commondir", "objects/info/alternates"):
        require(not os.path.lexists(os.path.join(root, ".git", name)), "IOS_GIT_READONLY_EXTERNAL_REPOSITORY")
    config = os.path.join(root, ".git/config")
    fd = os.open(config, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    data = bytearray()
    try:
        actual, named_stat = os.fstat(fd), os.lstat(config)
        before, named = frame(actual), frame(named_stat)
        require(stat.S_ISREG(actual.st_mode) and not stat.S_ISLNK(named_stat.st_mode)
                and actual.st_uid == os.getuid() and actual.st_nlink == 1
                and actual.st_mode & 0o022 == 0 and 0 <= actual.st_size <= 65536
                and before == named, "IOS_GIT_READONLY_CONFIG_ADMISSION")
        ns = namespace(config, end)
        while len(data) < actual.st_size+1:
            check(end)
            block = os.read(fd, min(65536, actual.st_size+1-len(data)))
            if not block:
                break
            data.extend(block)
        require(len(data) == actual.st_size and before == frame(os.fstat(fd)) and named == frame(os.lstat(config)) and ns == namespace(config, end))
        text = data.decode("utf-8", "strict")
        section = ""
        for row in text.splitlines():
            check(end)
            line = row.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if re.fullmatch(r'\[(core|remote "origin"|branch "[A-Za-z0-9][A-Za-z0-9._/-]*")\]', line):
                section = line
                continue
            match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)\s*=\s*(.+)", line)
            require(match is not None, "IOS_GIT_READONLY_CONFIG")
            key, value = match.groups()
            if section == "[core]":
                require(value in {"repositoryformatversion": ("0",), "filemode": ("true", "false"), "bare": ("false",),
                        "logallrefupdates": ("true",), "ignorecase": ("true", "false"), "precomposeunicode": ("true", "false")}.get(key, ()), "IOS_GIT_READONLY_CONFIG")
            elif section == '[remote "origin"]':
                require(key in ("url", "fetch") and not re.search(r"[\0\r\n]", value), "IOS_GIT_READONLY_CONFIG")
            elif section.startswith("[branch "):
                require(key == "remote" and value == "origin" or key == "merge" and value.startswith("refs/heads/"), "IOS_GIT_READONLY_CONFIG")
            else:
                require(False, "IOS_GIT_READONLY_CONFIG")
        return before, named, ns
    finally:
        data[:] = b"\0"*len(data)
        os.close(fd)


def run(context, args, *, incoming=None, deadline=None):
    require(sys.version_info[:3] == (3, 13, 17), "IOS_GIT_READONLY_PYTHON")
    argv = arguments(args)
    incoming = os.environ if incoming is None else incoming
    held = []
    end = min(time.monotonic()+5, deadline) if deadline is not None else time.monotonic()+5
    data = None
    try:
        require(set(context) == {"source", "python", "git"})
        raw_file, raw_sha, raw_size = (incoming.get("CASEOPS_IOS_HOST_POLICY_"+key) for key in ("FILE", "SHA256", "SIZE"))
        require(type(raw_size) is str and re.fullmatch("[1-9][0-9]{0,5}", raw_size))
        policy = Held({"path": raw_file, "sha256": raw_sha, "sizeBytes": int(raw_size)}, end, 65536, private=True)
        held.append(policy)
        value = json.loads(policy.data.decode("utf-8", "strict"))
        require(value.get("schemaVersion") == 1 and value.get("kind") == "caseops-ios-host-launch-v1" and value.get("requiresOwnedOuterController") is True)
        require(type(value.get("deadlineEpochMs")) in (int, float) and time.time()*1000 < value["deadlineEpochMs"])
        end = min(end, time.monotonic()+(value["deadlineEpochMs"]-time.time()*1000)/1000)
        for item in held:
            item.end = end
        require(value["source"]["ios-git-readonly.py"] == context["source"] and value["tools"]["git"] == context["git"]
                and value["tools"]["python"] == context["python"])
        require(context["python"]["version"] == "3.13.17" and os.path.realpath(sys.executable) == context["python"]["path"])
        for role in ("python", "git"):
            ref = {key: context[role][key] for key in ("path", "sha256", "sizeBytes")}
            item = Held(ref, end, 32*1024*1024, system=True)
            held.append(item)
        parent = os.path.dirname(raw_file)
        require(os.path.realpath(parent) == parent)
        root_stat = os.lstat(parent)
        require(root_stat.st_uid == os.getuid() and stat.S_ISDIR(root_stat.st_mode) and root_stat.st_mode & 0o777 == 0o700)
        home = os.path.join(parent, "empty")
        require(value["paths"]["empty"] == home and os.path.realpath(home) == home)
        home_stat = os.lstat(home)
        require(stat.S_ISDIR(home_stat.st_mode) and home_stat.st_uid == os.getuid() and home_stat.st_mode & 0o777 == 0o700)
        home_ns = namespace(home, end)
        with os.scandir(home) as entries:
            check(end)
            require(next(entries, None) is None)
        source = str(Path(value["helper"]["path"]).parent.parent.parent)
        require(source == str(Path(context["source"]["path"]).parent.parent.parent)
                and value["helper"]["path"] == str(Path(context["source"]["path"]).with_name("ios-host-launch.mjs"))
                and (args == ["--version"] or os.getcwd() == source), "IOS_GIT_READONLY_SOURCE_ROOT")
        repo_frame = repository(source, end)
        source_ns = namespace(source, end)
        data = stdin_bytes(0, end) if args == ["check-ignore", "-z", "--stdin"] else None
        environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "HOME": home,
                       "XDG_CONFIG_HOME": home, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/usr/bin/false", "SSH_ASKPASS": "/usr/bin/false",
                       "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "", "GIT_ATTR_NOSYSTEM": "1"}
        check(end)
        # Normal stdout/stderr/status flow directly to the existing bounded
        # SourceSnapshot caller; this transport adds no framing or log content.
        result = subprocess.run([context["git"]["path"], *argv], cwd=source, env=environment,
                                input=data, stdin=subprocess.DEVNULL if data is None else None,
                                timeout=max(0.001, end-time.monotonic()), check=False)
        if data is not None:
            data[:] = b"\0"*len(data)
        for item in held:
            item.verify()
        require(source_ns == namespace(source, end) and repo_frame == repository(source, end)
                and home_ns == namespace(home, end) and frame(home_stat) == frame(os.lstat(home)), "IOS_GIT_READONLY_NAMESPACE_CHANGED")
        return result.returncode
    finally:
        if data is not None:
            data[:] = b"\0"*len(data)
        for item in reversed(held):
            item.close()


def main(context, args, *, deadline=None):
    try:
        return run(context, args, deadline=deadline)
    except BaseException:
        print("IOS_GIT_READONLY_REFUSED", file=sys.stderr)
        return 1
