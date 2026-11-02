"""Bounded stdin adapter for the canonical private fixture writer; no networking."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

FIELDS = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


def held(path, expected, limit):
    path = Path(path)
    assert path.is_absolute() and path.resolve(strict=True) == path
    with path.open("rb") as stream:
        first, named = os.fstat(stream.fileno()), path.lstat()
        assert stat.S_ISREG(named.st_mode) and not stat.S_ISLNK(named.st_mode)
        assert first.st_uid == os.getuid() and first.st_nlink == 1
        assert all(getattr(first, k) == getattr(named, k) for k in FIELDS)
        data = stream.read(limit + 1)
        assert 0 < len(data) <= limit and len(data) == first.st_size
        assert hashlib.sha256(data).hexdigest() == expected
        assert all(getattr(first, k) == getattr(os.fstat(stream.fileno()), k) == getattr(path.lstat(), k) for k in FIELDS)
        return data


def main():
    assert len(sys.argv) == 5
    source, digest, root, name = sys.argv[1:]
    root = Path(root)
    assert root.is_absolute() and root.resolve(strict=True) == root
    before = root.lstat()
    assert stat.S_ISDIR(before.st_mode) and before.st_uid == os.getuid() and stat.S_IMODE(before.st_mode) == 0o700
    request = json.loads(sys.stdin.buffer.read(16385))
    assert set(request) == {"value", "expected"}
    scope = {"__name__": "caseops_producer_private", "__file__": source}
    exec(compile(held(source, digest, 131072), source, "exec"), scope)
    scope["ROOT"] = root
    result = scope["_write_private"](name, request["value"], update=request["expected"] is not None, expected=request["expected"],
                                     expected_root={key: str(getattr(before, key)) for key in ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode")})
    assert (root.lstat().st_dev, root.lstat().st_ino) == (before.st_dev, before.st_ino)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("PRODUCER_PRIVATE_WRITE_REFUSED", file=sys.stderr)
        sys.exit(1)
