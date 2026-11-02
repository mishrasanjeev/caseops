"""Synthetic fixture creation and real HTTP verification inside the owned API."""

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time

ROOT = Path(os.environ.get("CASEOPS_MOBILE_STATE", "/fixture-state"))
HEADERS = {"X-CaseOps-Automated-Test": "no-paid-providers"}
CLEAN = b"Synthetic CaseOps mobile source. No legal authority or customer data.\n"
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def _load_local_transport():
    import hashlib as _hashlib
    import os as _os
    import stat as _stat
    _path = Path(__file__).absolute().with_name("local-transport.py")
    _keys = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    _frame = lambda value: tuple(getattr(value, key) for key in _keys)
    assert _path.resolve(strict=True) == _path, "Canonical local transport source required"
    def _namespace():
        rows = []
        for parent in _path.parents:
            value = parent.lstat()
            assert len(rows) < 128 and _stat.S_ISDIR(value.st_mode) and not _stat.S_ISLNK(value.st_mode), "Local transport source namespace required"
            rows.append((str(parent), *(getattr(value, key) for key in _keys[:5])))
        return rows
    _parents = _namespace()
    _named = _path.lstat()
    _fd = _os.open(_path, _os.O_RDONLY | getattr(_os, "O_NOFOLLOW", 0) | getattr(_os, "O_NONBLOCK", 0) | getattr(_os, "O_BINARY", 0))
    try:
        _first = _os.fstat(_fd)
        assert _stat.S_ISREG(_first.st_mode) and not _stat.S_ISLNK(_named.st_mode) and _first.st_nlink == 1 and _first.st_uid == Path(__file__).lstat().st_uid, "Local transport source identity required"
        assert 0 < _first.st_size <= 16384 and all(getattr(_first, key) == getattr(_named, key) for key in _keys if not (_os.name == "nt" and key == "st_dev" and _named.st_dev == 0)), "Local transport named descriptor mismatch"
        _data = bytearray()
        while len(_data) <= _first.st_size:
            _part = _os.read(_fd, min(65536, _first.st_size + 1 - len(_data)))
            if not _part:
                break
            _data.extend(_part)
        _raw = bytes(_data)
        assert len(_raw) == _first.st_size and _hashlib.sha256(_raw).hexdigest() == "95180cd961891d9056d2a4d491e9239c6f49d4de2562c35e6d48610d767dd6ae" and _frame(_first) == _frame(_os.fstat(_fd)) and _frame(_named) == _frame(_path.lstat()) and _parents == _namespace(), "Local transport source changed"
    finally:
        _os.close(_fd)
    _scope = {"__name__": "caseops_local_transport", "__file__": str(_path)}
    exec(compile(_raw, str(_path), "exec"), _scope)
    return _scope

_LOCAL_TRANSPORT = _load_local_transport()

def initial_gateway_routes(matter_id, draft_id):
    # Exact method/path admission only. Query validation and native authority
    # remain API contracts; this public policy GET still needs the no-paid marker.
    return {"GET /api/build", "GET /api/health", "GET /api/auth/me", "GET /api/auth/security",
            "GET /api/auth/native/compatibility",
            "POST /api/auth/native/token", "POST /api/auth/native/refresh", "POST /api/auth/native/logout",
            "GET /api/me/today", "GET /api/matters/", "GET /api/calendar/events",
            "GET /api/auth/native/sessions", f"GET /api/matters/{matter_id}",
            f"GET /api/matters/{matter_id}/workspace", f"POST /api/matters/{matter_id}/notes",
            f"GET /api/matters/{matter_id}/drafts", f"GET /api/matters/{matter_id}/drafts/{draft_id}"}


def private_name(name):
    leaf = Path(name).name if isinstance(name, (str, os.PathLike)) else None
    return leaf in ("credentials.json", "compose-secrets.json", "supplied-credentials.json") or bool(
        leaf and re.fullmatch(r"core-credentials-[a-f0-9]{12}\.json", leaf))


def _private_metadata(value, *, mode=True):
    assert stat.S_ISREG(value.st_mode) and value.st_nlink == 1, "Single-link regular private fixture required"
    if os.name != "nt":
        assert value.st_uid == os.getuid(), "Owned private fixture required"
        assert not mode or stat.S_IMODE(value.st_mode) == 0o600, "Private fixture mode must remain 0600"


def private_metadata_equal(first, second, *, named_path=False, windows=False):
    assert type(named_path) is bool and type(windows) is bool, "Explicit private metadata comparison mode required"
    fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    return all(getattr(first, key) == getattr(second, key) for key in fields
               if not (windows and named_path and key == "st_dev" and second.st_dev == 0))


def _write_private(name, value, *, update=False, expected=None, expected_root=None):
    assert isinstance(name, str) and private_name(name) and Path(name).name == name, "Direct owned secret filename required"
    content = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    target = ROOT / name
    # Optional external producer admission is checked through the descriptor
    # that will be truncated, never by a hash-then-reopen sequence.
    identity_fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    namespace = None
    def namespace_frame():
        rows = []
        assert ROOT.is_absolute() and ROOT.resolve(strict=True) == ROOT, "Canonical private root required"
        for parent in (ROOT, *ROOT.parents):
            item = parent.lstat()
            assert stat.S_ISDIR(item.st_mode) and not stat.S_ISLNK(item.st_mode), "Private namespace required"
            rows.append((str(parent), item.st_dev, item.st_ino, item.st_uid, item.st_gid, item.st_mode))
        return rows
    if expected_root is not None:
        root_fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode")
        assert set(expected_root) == set(root_fields) and all(isinstance(item, str) and re.fullmatch(r"0|[1-9][0-9]*", item) for item in expected_root.values()), "Expected private root required"
        namespace = namespace_frame()
        assert all(getattr(ROOT.lstat(), key) == int(expected_root[key]) for key in root_fields), "Expected private root changed"
    if expected is not None:
        assert update and set(expected) == {"identity", "sha256"}, "Expected private update required"
        assert set(expected["identity"]) == set(identity_fields), "Complete expected private identity required"
        assert all(isinstance(item, str) and re.fullmatch(r"0|[1-9][0-9]*", item) for item in expected["identity"].values()), "Lossless private identity required"
        assert re.fullmatch(r"[a-f0-9]{64}", expected["sha256"]), "Expected private digest required"
        namespace = namespace_frame()
    previous = target.lstat() if update else None
    if previous is not None:
        _private_metadata(previous)
    assert os.name == "nt" or hasattr(os, "O_NOFOLLOW"), "No-follow private file support required"
    flags = os.O_RDWR if update else (os.O_RDWR if expected_root is not None else os.O_WRONLY) | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(target, flags, 0o600)
    try:
        opened = os.fstat(descriptor)
        _private_metadata(opened, mode=update)
        if not update and os.name != "nt":
            # Creation is already at most 0600, including under umask 0.
            # Restore owner access before the first byte if umask was stricter.
            os.fchmod(descriptor, 0o600)
            opened = os.fstat(descriptor)
        named = target.lstat()
        _private_metadata(opened)
        _private_metadata(named)
        assert private_metadata_equal(opened, named, named_path=True, windows=os.name == "nt"), "Private fixture path changed"
        if namespace is not None:
            assert namespace_frame() == namespace, "Private namespace changed before write"
        if previous is not None:
            assert private_metadata_equal(opened, previous, named_path=True, windows=os.name == "nt"), "Private fixture changed before update"
            if expected is not None:
                assert all(getattr(opened, key) == int(expected["identity"][key]) for key in identity_fields), "Expected private identity changed"
                assert 0 < opened.st_size <= 16384, "Bounded private update required"
                original = bytearray()
                while len(original) <= opened.st_size:
                    part = os.read(descriptor, min(65536, opened.st_size + 1 - len(original)))
                    if not part:
                        break
                    original.extend(part)
                try:
                    assert len(original) == opened.st_size and hashlib.sha256(original).hexdigest() == expected["sha256"], "Expected private bytes changed"
                    assert private_metadata_equal(opened, os.fstat(descriptor)), "Private fixture changed during admission"
                    assert private_metadata_equal(opened, target.lstat(), named_path=True, windows=os.name == "nt"), "Private fixture path changed during admission"
                    assert namespace_frame() == namespace, "Private namespace changed during admission"
                finally:
                    original[:] = b"\0" * len(original)
                os.lseek(descriptor, 0, os.SEEK_SET)
            # Never use O_TRUNC: all ownership/path/descriptor checks precede it.
            os.ftruncate(descriptor, 0)
        remaining = memoryview(content)
        while remaining:
            count = os.write(descriptor, remaining)
            assert 0 < count <= len(remaining), "Private fixture write incomplete"
            remaining = remaining[count:]
        os.fsync(descriptor)
        final, named = os.fstat(descriptor), target.lstat()
        _private_metadata(final)
        _private_metadata(named)
        assert private_metadata_equal(final, named, named_path=True, windows=os.name == "nt"), "Private fixture path changed during write"
        assert (final.st_dev, final.st_ino, final.st_uid, final.st_gid, final.st_mode, final.st_nlink) == (
            opened.st_dev, opened.st_ino, opened.st_uid, opened.st_gid, opened.st_mode, opened.st_nlink), "Private fixture identity changed"
        assert final.st_size == len(content), "Private fixture write incomplete"
        if namespace is not None:
            assert namespace_frame() == namespace, "Private namespace changed during write"
        if expected_root is not None:
            # Publish the writer's own descriptor observation. A later path
            # reopen cannot supply creation or update provenance.
            assert 0 < final.st_size <= 16384, "Bounded private publication required"
            os.lseek(descriptor, 0, os.SEEK_SET)
            actual = bytearray()
            try:
                while len(actual) <= final.st_size:
                    part = os.read(descriptor, min(65536, final.st_size + 1 - len(actual)))
                    if not part:
                        break
                    actual.extend(part)
                assert bytes(actual) == content, "Private descriptor publication bytes changed"
                assert private_metadata_equal(final, os.fstat(descriptor)), "Private descriptor changed before publication"
                assert private_metadata_equal(final, target.lstat(), named_path=True, windows=os.name == "nt"), "Private publication pathname changed"
                assert namespace_frame() == namespace, "Private publication namespace changed"
                return {"evidence": {"path": str(target), "sha256": hashlib.sha256(actual).hexdigest(), "uid": final.st_uid},
                        "mode": stat.S_IMODE(final.st_mode), "canonicalWriter": "local-fixture.py",
                        "identity": {"dev": str(final.st_dev), "ino": str(final.st_ino), "uid": final.st_uid},
                        "frame": {key: str(getattr(final, key)) for key in identity_fields}, "ownedNoFollowSingleLink": True}
            finally:
                actual[:] = b"\0" * len(actual)
    finally:
        os.close(descriptor)


def update_private(name, value):
    _write_private(name, value, update=True)


def save(name, value):
    if private_name(name):
        _write_private(name, value)
        return
    with (ROOT / name).open("x", encoding="utf-8") as target:
        json.dump(value, target, indent=2)
        target.write("\n")


def certificate_time_utc(certificate, attribute):
    """X.509 legacy validity fields are naive UTC; never local wall time."""
    if attribute not in ("not_valid_before", "not_valid_after"):
        raise ValueError("INVALID_CERTIFICATE_TIME_FIELD")
    try:
        value = getattr(certificate, attribute + "_utc")
    except AttributeError:
        value = getattr(certificate, attribute)
        if not isinstance(value, datetime) or value.tzinfo is not None:
            raise ValueError("INVALID_LEGACY_CERTIFICATE_TIME")
        return value.replace(tzinfo=UTC)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("INVALID_CERTIFICATE_UTC_TIME")
    return value.astimezone(UTC)


def prepare(args):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    tls = ROOT / "tls"
    tls.mkdir()
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CaseOps isolated mobile fixture CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=30))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False,
                         content_commitment=False, data_encipherment=False, key_agreement=False,
                         key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (x509.CertificateBuilder().subject_name(leaf_name).issuer_name(ca_name)
            .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=14))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.IPAddress(ipaddress.ip_address("10.0.2.2")),
            ]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    for name, key in (("ca", ca_key), ("server", server_key)):
        (tls / f"{name}.key").write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (tls / f"{name}.key").chmod(0o600)
    (tls / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (tls / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    credentials = (json.loads((ROOT / "supplied-credentials.json").read_text())
                   if (ROOT / "supplied-credentials.json").exists() else {
                       "email": "mobile-operator@example.com", "password": "Aa1!" + secrets.token_urlsafe(24),
                   })
    assert len(credentials["password"]) >= 12
    credentials.update({"company_slug": "test-legal", "full_name": "Mobile Local Operator"})
    save("credentials.json", credentials)
    database_password = secrets.token_hex(24)
    save("compose-secrets.json", {
        "CASEOPS_MOBILE_DB_PASSWORD": database_password,
        "CASEOPS_MOBILE_DATABASE_URL": f"postgresql+psycopg://caseops:{database_password}@postgres:5432/caseops_mobile",
        "CASEOPS_MOBILE_AUTH_SECRET": secrets.token_hex(32),
        "CASEOPS_MOBILE_NATIVE_SECRET": secrets.token_hex(32),
    })
    save("tls-receipt.json", {
        "caSha256": ca.fingerprint(hashes.SHA256()).hex(),
        "serverSha256": cert.fingerprint(hashes.SHA256()).hex(),
        "subjectAlternativeNames": ["localhost", "127.0.0.1", "10.0.2.2"],
        "privateKeysOutsideGit": True, "expires": certificate_time_utc(cert, "not_valid_after").isoformat(),
    })
    save("gateway-routes.json", {"routes": ["GET /api/build", "GET /api/health"]})
    print(json.dumps({"prepared": True, "publicCA": "tls/ca.crt", "passwordLogged": False}))


def repair_tls(args):
    """Retain failed public bytes and reissue with unchanged private keys."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization

    tls = ROOT / "tls"
    ca = x509.load_pem_x509_certificate((tls / "ca.crt").read_bytes())
    leaf = x509.load_pem_x509_certificate((tls / "server.crt").read_bytes())
    ca_key = serialization.load_pem_private_key((tls / "ca.key").read_bytes(), password=None)
    server_key = serialization.load_pem_private_key((tls / "server.key").read_bytes(), password=None)
    stamp = secrets.token_hex(4)
    for name, certificate, key in (("ca", ca, ca_key), ("server", leaf, server_key)):
        (tls / f"{name}-failed-{stamp}.crt").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        builder = (x509.CertificateBuilder().subject_name(certificate.subject).issuer_name(certificate.issuer)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(certificate_time_utc(certificate, "not_valid_before"))
                   .not_valid_after(certificate_time_utc(certificate, "not_valid_after")))
        for extension in certificate.extensions:
            if extension.oid not in (x509.oid.ExtensionOID.SUBJECT_KEY_IDENTIFIER, x509.oid.ExtensionOID.AUTHORITY_KEY_IDENTIFIER):
                builder = builder.add_extension(extension.value, extension.critical)
        builder = builder.add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        builder = builder.add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        renewed = builder.sign(ca_key, hashes.SHA256())
        (tls / f"{name}.crt").write_bytes(renewed.public_bytes(serialization.Encoding.PEM))
    current = x509.load_pem_x509_certificate((tls / "ca.crt").read_bytes())
    receipt = {"certificateStandardsRepair": True, "priorPublicBytesRetained": True,
               "privateKeysChanged": False, "caSha256": current.fingerprint(hashes.SHA256()).hex()}
    save("tls-reissued-" + stamp + ".json", receipt)
    print(json.dumps(receipt))


def expect(response, status=200):
    if response.status_code != status:
        # Never serialize auth bodies or request values in failure diagnostics.
        fields = []
        if response.status_code == 422:
            detail = response.json().get("detail", [])
            if isinstance(detail, list):
                fields = [{"loc": row.get("loc"), "type": row.get("type")} for row in detail]
        raise AssertionError(f"{response.request.method} {response.request.url.path}: expected {status}, received {response.status_code}; fields={json.dumps(fields)}")
    return response.json() if response.content else None


def client():
    import httpx
    return httpx.Client(base_url="http://127.0.0.1:8000", headers=HEADERS, timeout=20, follow_redirects=False)


def bootstrap(http, credentials, slug, name):
    from sqlalchemy import select
    from sqlalchemy.engine import make_url
    from caseops_api.db.models import Company
    from caseops_api.db.session import get_session_factory

    url = make_url(os.environ["CASEOPS_DATABASE_URL"])
    assert os.environ["CASEOPS_ENV"] == "local" and url.host == "postgres" and url.database == "caseops_mobile"
    with get_session_factory()() as session:
        existing = session.scalar(select(Company.id).where(Company.slug == slug).limit(1))
    if existing:
        return login(http, {**credentials, "company_slug": slug})
    body = expect(http.post("/api/bootstrap/company", json={
        "company_name": name, "company_slug": slug, "company_type": "law_firm",
        "owner_full_name": credentials["full_name"], "owner_email": credentials["email"],
        "owner_password": credentials["password"],
    }))
    http.cookies.clear()
    http.headers["Authorization"] = f"Bearer {body['access_token']}"
    return body


def one_or_none(rows, key, value):
    selected = [row for row in rows if row[key] == value]
    assert len(selected) <= 1, "Ambiguous synthetic fixture identity"
    return selected[0] if selected else None


def ensure_matter(http, payload):
    rows = expect(http.get("/api/matters/", params={"q": payload["matter_code"], "limit": 25}))["matters"]
    found = one_or_none(rows, "matter_code", payload["matter_code"])
    if found:
        assert found["title"] == payload["title"], "Existing synthetic fixture does not match"
        return expect(http.get(f"/api/matters/{found['id']}"))
    return expect(http.post("/api/matters/", json=payload))


def seed_manual_draft_version(draft_id, matter_id, company_id, membership_id):
    from sqlalchemy import select
    from caseops_api.db.models import Draft, DraftVersion, Matter
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        matter = session.scalar(select(Matter).where(Matter.id == matter_id, Matter.company_id == company_id).with_for_update())
        assert matter and matter.status == "intake"
        draft = session.scalar(select(Draft).where(Draft.id == draft_id, Draft.matter_id == matter_id).with_for_update())
        assert draft
        if draft.current_version_id is None:
            version = DraftVersion(draft_id=draft_id, generated_by_membership_id=membership_id,
                                   model_run_id=None, revision=1,
                                   body="Synthetic manually seeded memo. No legal advice or authority.",
                                   summary="Isolated fixture version, not model-generated or legally verified.",
                                   context_manifest_json='{"fixture":"mobile-local-synthetic"}')
            session.add(version)
            session.flush()
            draft.current_version_id = version.id
            session.commit()


def submit_synthetic_review(http, mid, draft):
    if draft["status"] == "draft":
        draft = expect(http.post(f"/api/matters/{mid}/drafts/{draft['id']}/submit", json={
            "notes": "Synthetic local fixture for read-only review. Not a legal approval.",
        }))
    assert draft["status"] == "in_review" and draft["current_version_id"]
    return draft


def login(http, credentials):
    http.headers.pop("Authorization", None)
    http.cookies.clear()
    auth = expect(http.post("/api/auth/login", json={
        "email": credentials["email"], "password": credentials["password"],
        "company_slug": credentials["company_slug"],
    }))
    http.cookies.clear()
    http.headers["Authorization"] = f"Bearer {auth['access_token']}"
    return auth


def seed(args):
    assert type(args.mfa) is bool, "Explicit MFA Boolean required"
    mfa_enabled = args.mfa is True
    assert not (ROOT / "seed.json").exists(), "Existing fixture must never be reseeded"
    credentials = json.loads((ROOT / "credentials.json").read_text())
    with client() as http:
        owner = bootstrap(http, credentials, "test-legal", "Mobile Local Legal")
        today = datetime.now(UTC).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()
        matter = ensure_matter(http, {
            "title": "Synthetic mobile acceptance matter", "matter_code": "MOBILE-LOCAL-001",
            "practice_area": "Litigation", "forum_level": "advisory", "status": "intake",
            "assignee_membership_id": owner["membership"]["id"],
        })
        mid = matter["id"]
        workspace = expect(http.get(f"/api/matters/{mid}/workspace"))
        task = one_or_none(workspace["tasks"], "title", "Review synthetic mobile file") or expect(http.post(f"/api/matters/{mid}/tasks", json={
            "title": "Review synthetic mobile file", "due_on": today,
            "owner_membership_id": owner["membership"]["id"], "priority": "high",
        }))
        hearing = one_or_none(workspace["hearings"], "purpose", "Local acceptance only") or expect(http.post(f"/api/matters/{mid}/hearings", json={
            "hearing_on": today, "forum_name": "Synthetic local forum", "purpose": "Local acceptance only",
            "time_status": "exact", "hearing_time": "11:30:00", "timezone": "Asia/Kolkata",
            "reminder_channels": ["in_app"],
        }))
        drafts = expect(http.get(f"/api/matters/{mid}/drafts"))["drafts"]
        draft = one_or_none(drafts, "title", "Synthetic manual draft") or expect(http.post(f"/api/matters/{mid}/drafts", json={
            "title": "Synthetic manual draft", "draft_type": "memo",
        }))
        seed_manual_draft_version(draft["id"], mid, owner["company"]["id"], owner["membership"]["id"])
        draft = expect(http.get(f"/api/matters/{mid}/drafts/{draft['id']}"))
        draft = submit_synthetic_review(http, mid, draft)
        clean = one_or_none(workspace["attachments"], "original_filename", "mobile-source.txt") or expect(http.post(f"/api/matters/{mid}/attachments", files={
            "file": ("mobile-source.txt", CLEAN, "text/plain"),
        }))
        download = http.get(f"/api/matters/{mid}/attachments/{clean['id']}/download")
        assert download.status_code == 200 and download.content == CLEAN
        expect(http.post(f"/api/matters/{mid}/attachments", files={
            "file": ("eicar.txt", EICAR, "text/plain"),
        }), 400)
        closed = ensure_matter(http, {
            "title": "Synthetic terminal matter", "matter_code": "MOBILE-CLOSED-001",
            "practice_area": "Litigation", "forum_level": "advisory", "status": "intake",
        })
        if closed["status"] != "disposed":
            closed = expect(http.patch(f"/api/matters/{closed['id']}/lifecycle/status", json={
            "to_status": "disposed", "expected_from_status": closed["status"],
            "expected_updated_at": closed["updated_at"], "reason": "Synthetic terminal isolation fixture",
            }))
        denied = http.post(f"/api/matters/{closed['id']}/notes", json={
            "body": "This must not persist", "expected_lifecycle_version": closed["lifecycle_version"],
        })
        assert denied.status_code in (403, 409), "Terminal note must fail closed"
        other_credentials = {"email": "mobile-other@example.com", "password": credentials["password"],
                             "full_name": "Other Local Operator"}
        other = bootstrap(http, other_credentials, "test-mobile-other", "Other Mobile Local")
        other_matter = ensure_matter(http, {
            "title": "Other tenant synthetic matter", "matter_code": "OTHER-PRIVATE-001",
            "practice_area": "Litigation", "forum_level": "advisory", "status": "intake",
        })
        expect(http.get(f"/api/matters/{mid}/workspace"), 404)
        login(http, credentials)
        expect(http.get(f"/api/matters/{other_matter['id']}/workspace"), 404)
        workspace = expect(http.get(f"/api/matters/{mid}/workspace"))
        assert not workspace["notes"], "Native note fixture must start empty"
        # Enroll through actual endpoints. The operator browser still has to perform its own MFA step-up.
        if mfa_enabled and not credentials.get("totp_secret"):
            from caseops_api.services.security import TOTP_PERIOD_SECONDS, _hotp
            enrollment = expect(http.post("/api/auth/mfa/enroll"))
            secret = enrollment["secret"]
            expect(http.post("/api/auth/mfa/enroll/verify", json={"code": _hotp(secret, int(time.time()) // TOTP_PERIOD_SECONDS)}))
            credentials["totp_secret"] = secret
            update_private("credentials.json", credentials)
        routes = initial_gateway_routes(mid, draft["id"])
        (ROOT / "gateway-routes.json").write_text(json.dumps({"routes": sorted(routes)}), encoding="utf-8")
        save("seed.json", {
            "environment": "docker-integration", "syntheticDataOnly": True,
            "principalLabel": owner["user"]["full_name"], "workspaceLabel": owner["company"]["name"],
            "companyId": owner["company"]["id"], "membershipId": owner["membership"]["id"],
            "matter": {"id": mid, "search": matter["matter_code"], "identityLabel": matter["matter_code"]},
            "calendarDate": today, "taskId": task["id"], "hearingId": hearing["id"],
            "draftId": draft["id"], "sourceId": clean["id"],
            "sourceSha256": hashlib.sha256(CLEAN).hexdigest(),
            "closedMatterId": closed["id"], "otherCompanyId": other["company"]["id"],
            "otherMatterId": other_matter["id"], "mfaEnrolled": mfa_enabled,
            "nativeNotesBeforeRun": 0, "crossTenantWorkspaceDenied": True,
            "terminalNoteDenied": True, "cleanUploadAndDownload": True, "eicarRejected": True,
        })
    print(json.dumps({"seeded": True, "syntheticTenants": 2, "nativeNoteCount": 0,
                      "realScannerCleanAndEicar": True}))


def probe(args):
    credentials = json.loads((ROOT / "credentials.json").read_text())
    state = json.loads((ROOT / "seed.json").read_text())
    with client() as http:
        login(http, credentials)
        mid = state["matter"]["id"]
        search = expect(http.get("/api/matters/", params={"q": state["matter"]["search"], "limit": 25}))
        assert [row["id"] for row in search["matters"]] == [mid]
        workspace = expect(http.get(f"/api/matters/{mid}/workspace"))
        assert workspace["matter"]["id"] == mid
        agenda = expect(http.get("/api/calendar/events", params={"from": state["calendarDate"], "to": state["calendarDate"]}))
        hearing = one_or_none(agenda["events"], "id", "hearing:" + state["hearingId"])
        assert hearing and hearing["matter_id"] == mid and hearing["occurs_on"] == state["calendarDate"]
        assert hearing["time_status"] == "exact" and hearing["hearing_time"] == "11:30:00" and hearing["timezone"] == "Asia/Kolkata"
        today = expect(http.get("/api/me/today", params={"horizon_days": 7}))
        assert any(row["id"] == state["taskId"] and row["matter"]["id"] == mid and
                   row["due_on"] == state["calendarDate"] for row in today["tasks_due_or_overdue"])
        assert any(row["id"] == state["draftId"] and row["matter"]["id"] == mid
                   for row in today["drafts_in_review"])
        drafts = expect(http.get(f"/api/matters/{mid}/drafts"))
        assert any(row["id"] == state["draftId"] and row["current_version_id"] and
                   any(version["id"] == row["current_version_id"] for version in row["versions"])
                   for row in drafts["drafts"])
        expect(http.get(f"/api/matters/{state['otherMatterId']}/workspace"), 404)
        if args.outage:
            expect(http.post(f"/api/matters/{mid}/attachments", files={
                "file": ("scanner-outage.txt", CLEAN, "text/plain"),
            }), 503)
        receipt = {"realHTTP": True, "exactMatterSearch": True, "exactWorkspaceReload": True,
                   "calendarEvents": len(agenda["events"]), "exactHearingDateAndTime": True,
                   "todayExactTask": True, "workExactDraftInReview": True,
                   "currentDraftRead": True, "nativeNoteCount": len(workspace["notes"]),
                   "crossTenantDenied": True, "scannerOutageRejected": args.outage}
        save(f"probe-{secrets.token_hex(4)}.json", receipt)
        print(json.dumps(receipt))


def prepare_reviews(args):
    state = json.loads((ROOT / "seed.json").read_text())
    credentials = json.loads((ROOT / "credentials.json").read_text())
    with client() as http:
        login(http, credentials)
        mid = state["matter"]["id"]
        draft = expect(http.get(f"/api/matters/{mid}/drafts/{state['draftId']}"))
        draft = submit_synthetic_review(http, mid, draft)
        save("seed-review-" + secrets.token_hex(4) + ".json", {
            "draftId": draft["id"], "currentVersionId": draft["current_version_id"],
            "status": draft["status"], "approved": False, "generatedByProvider": False,
        })
    print(json.dumps({"syntheticDraftInReview": True, "approved": False}))


def auth_probe(args):
    """Real cookie/CSRF -> MFA -> PKCE -> native bearer HTTP proof, not UI injection."""
    import base64
    from caseops_api.services.security import TOTP_PERIOD_SECONDS, _hotp

    credentials = json.loads((ROOT / "credentials.json").read_text())
    state = json.loads((ROOT / "seed.json").read_text())
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    transport = _LOCAL_TRANSPORT["policy"](json.loads((ROOT / "config.json").read_text()))
    authorization = {"code_challenge": challenge, "state": secrets.token_urlsafe(32),
                     "platform": transport["platform"], "redirect_uri": "caseops://oauth/callback"}
    with client() as browser, client() as token_http, client() as native:
        expect(browser.post("/api/auth/login", json={
            "email": credentials["email"], "password": credentials["password"],
            "company_slug": credentials["company_slug"],
        }))
        browser.headers["X-CSRF-Token"] = browser.cookies.get("caseops_csrf")
        browser.headers["Origin"] = transport["webOrigin"]
        expect(browser.post("/api/auth/native/authorize", json=authorization), 403)
        expect(browser.post("/api/auth/mfa/step-up", json={
            "code": _hotp(credentials["totp_secret"], int(time.time()) // TOTP_PERIOD_SECONDS),
            "purpose": "step_up", "method": "totp",
        }))
        grant = expect(browser.post("/api/auth/native/authorize", json=authorization))
        assert grant["state"] == authorization["state"] and grant["redirect_uri"] == authorization["redirect_uri"]
        payload = {"code": grant["code"], "code_verifier": verifier,
                   "platform": transport["platform"], "redirect_uri": authorization["redirect_uri"]}
        tokens = expect(token_http.post("/api/auth/native/token", json=payload))
        expect(token_http.post("/api/auth/native/token", json=payload), 401)
        native.headers["Authorization"] = f"Bearer {tokens['access_token']}"
        identity = expect(native.get("/api/auth/me"))
        assert identity["company"]["id"] == state["companyId"]
        mid = state["matter"]["id"]
        expect(native.get(f"/api/matters/{mid}/workspace"))
        expect(native.get(f"/api/matters/{state['otherMatterId']}/workspace"), 404)
        proof = ensure_matter(native, {
            "title": "Synthetic HTTP note proof", "matter_code": "MOBILE-PROBE-" + secrets.token_hex(5).upper(),
            "practice_area": "Litigation", "forum_level": "advisory", "status": "intake",
        })
        note = expect(native.post(f"/api/matters/{proof['id']}/notes", json={
            "body": "Synthetic save-once HTTP proof", "expected_lifecycle_version": proof["lifecycle_version"],
        }))
        reloaded = expect(native.get(f"/api/matters/{proof['id']}/workspace"))
        assert len(reloaded["notes"]) == 1 and reloaded["notes"][0]["id"] == note["id"]
        expect(native.patch(f"/api/matters/{proof['id']}/lifecycle/status", json={
            "to_status": "disposed", "expected_from_status": proof["status"],
            "expected_updated_at": proof["updated_at"], "reason": "Completed synthetic HTTP proof",
        }))
        rotated = expect(token_http.post("/api/auth/native/refresh", json={"refresh_token": tokens["refresh_token"]}))
        expect(token_http.post("/api/auth/native/logout", json={"refresh_token": rotated["refresh_token"]}), 204)
        native.headers["Authorization"] = f"Bearer {rotated['access_token']}"
        expect(native.get("/api/auth/me"), 401)
        # Read target again with legitimate browser authority; native target remains untouched.
        target = expect(browser.get(f"/api/matters/{mid}/workspace"))
        assert not target["notes"]
        receipt = {"realHTTP": True, "browserCookiesFromActualLogin": True,
                   "cookieOrNativeTokenInjection": False, "mfaRequiredBeforeNativeConsent": True,
                   "pkceExchange": True, "singleUseCodeReplayDenied": True,
                   "nativeTenantIsolation": True, "separateProofMatterId": proof["id"],
                   "oneNotePersistedAndReloaded": True, "proofMatterDisposed": True,
                   "refreshRotation": True, "logoutRevokesAccess": True, "nativeTargetNotes": 0,
                   "nativeUIAcceptance": False}
        save("auth-probe-" + secrets.token_hex(4) + ".json", receipt)
        print(json.dumps(receipt))


def scanner_probe(args):
    import clamd
    import tempfile
    from caseops_api.services.virus_scan import scan_file_for_viruses, _config_from_env

    host, port, timeout, required = _config_from_env()
    assert host == "scanner" and port == 3310 and required, "Real required scanner policy must be active"
    daemon = clamd.ClamdNetworkSocket(host=host, port=port, timeout=timeout)
    assert daemon.ping() == "PONG"
    observations = []
    for label, data, expected in (("clean", CLEAN, "clean"), ("eicar", EICAR, "infected")):
        with tempfile.TemporaryDirectory(prefix="caseops-mobile-scan-") as directory:
            file = Path(directory) / "probe.txt"
            file.write_bytes(data)
            verdict = scan_file_for_viruses(file)
            assert verdict.status == expected, f"Real scanner {label} control failed"
            if label == "eicar":
                assert verdict.signature
            observations.append({"sample": label, "sha256": hashlib.sha256(data).hexdigest(),
                                 "status": verdict.status, "signature": verdict.signature})
    receipt = {"realClamAV": True, "requiredPolicy": required, "host": host, "port": port,
               "daemonVersion": daemon.version(), "samples": observations,
               "notAnUploadDTO": True, "scannerOutageProven": False}
    save("scanner-probe-" + secrets.token_hex(4) + ".json", receipt)
    print(json.dumps(receipt))


def admit_upload(args):
    state = json.loads((ROOT / "seed.json").read_text())
    with client() as http:
        schema = expect(http.get("/openapi.json"))
    operation = schema["paths"]["/api/matters/{matter_id}/attachments"]["post"]
    body = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    if "$ref" in body:
        body = schema["components"]["schemas"][body["$ref"].rsplit("/", 1)[1]]
    assert "expected_lifecycle_version" in body["properties"], "Serving API lacks the native upload version contract"
    path = ROOT / "gateway-routes.json"
    previous = json.loads(path.read_text())
    route = f"POST /api/matters/{state['matter']['id']}/attachments"
    current = {"routes": sorted(set(previous["routes"]) | {route})}
    save("gateway-upload-admission-" + secrets.token_hex(4) + ".json", {
        "previousRoutes": previous["routes"], "admittedRoute": route,
        "servingMultipartVersionContractPresent": True,
        "uploadFixtureBodyLimitBytes": 1048576,
        "doesNotCertifyLifecycleRaceTests": True,
    })
    path.write_text(json.dumps(current), encoding="utf-8")
    print(json.dumps({"nativeUploadRouteAdmitted": True, "servingVersionContractPresent": True}))


def admit_source(args):
    from http.client import HTTPConnection
    import socket
    import ssl

    seed = json.loads((ROOT / "seed.json").read_text(encoding="utf-8"))
    with client() as http:
        login(http, json.loads((ROOT / "credentials.json").read_text(encoding="utf-8")))
        mid, source_id = seed["matter"]["id"], seed["sourceId"]
        workspace = expect(http.get(f"/api/matters/{mid}/workspace"))
        source = one_or_none(workspace["attachments"], "id", source_id)
        assert source and source["sha256_hex"] == seed["sourceSha256"] and 0 < source["size_bytes"] <= 1048576
        route = f"/api/matters/{mid}/attachments/{source_id}/download"
        route_file = ROOT / "gateway-routes.json"
        previous = json.loads(route_file.read_text(encoding="utf-8"))
        route_file.write_text(json.dumps({"routes": sorted(set(previous["routes"]) | {f"GET {route}"})}), encoding="utf-8")
        observations = []
        for byte_range, expected_status in ((None, 200), ("bytes=0-15", 206)):
            context = ssl.create_default_context(cafile=str(ROOT / "tls/ca.crt"))
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            # Docker DNS maps the logical localhost origin to the dedicated TLS gateway.
            # Hostname and CA verification remain enabled for that exact logical origin.
            raw = socket.create_connection(("gateway", 8443), timeout=3)
            secured = context.wrap_socket(raw, server_hostname="localhost")
            connection = HTTPConnection("localhost", 8443, timeout=3)
            connection.sock = secured
            headers = {**HEADERS, "Authorization": http.headers["Authorization"], "Host": "localhost:8443"}
            if byte_range:
                headers["Range"] = byte_range
            try:
                connection.request("GET", route, headers=headers)
                response = connection.getresponse()
                content = response.read(1048577)
                assert response.status == expected_status, f"Canonical source {byte_range or 'full'} response mismatch"
                if byte_range:
                    assert content == CLEAN[:16]
                    assert response.getheader("Content-Range") == f"bytes 0-15/{source['size_bytes']}"
                else:
                    assert hashlib.sha256(content).hexdigest() == seed["sourceSha256"]
                observations.append({"range": byte_range, "status": response.status, "bytes": len(content),
                                     "responseSha256": hashlib.sha256(content).hexdigest(), "actualNoPaidHeader": True})
            finally:
                connection.close()
        evidence = {"admittedRoute": f"GET {route}", "previousRoutes": previous["routes"],
                    "sourceId": source_id, "sourceSha256": seed["sourceSha256"],
                    "servingBuild": expect(http.get("/api/build")), "strictTLS": True,
                    "observations": observations, "mustReplayAfterFinalImageRebuild": True}
        name = "gateway-source-admission-" + secrets.token_hex(4) + ".json"
        save(name, evidence)
        print(json.dumps({"sourceRouteAdmitted": True, "rangeGET": 206, "receipt": name}))


def failure_diagnostic(error, mode):
    import traceback
    return {"failed": mode, "errorType": type(error).__name__,
            "frames": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                       for frame in traceback.extract_tb(error.__traceback__)],
            "detail": "See owned container diagnostics; values redacted"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "repair-tls", "seed", "prepare-reviews", "probe", "auth-probe", "scanner-probe", "admit-upload", "admit-source"))
    parser.add_argument("--mfa", action="store_true")
    parser.add_argument("--outage", action="store_true")
    options = parser.parse_args()
    try:
        {"prepare": prepare, "repair-tls": repair_tls, "seed": seed, "probe": probe,
         "auth-probe": auth_probe, "scanner-probe": scanner_probe,
         "prepare-reviews": prepare_reviews, "admit-upload": admit_upload, "admit-source": admit_source}[options.mode](options)
    except Exception as error:
        # Assertion messages can include response/request secrets too.
        print(json.dumps(failure_diagnostic(error, options.mode)), file=sys.stderr)
        sys.exit(1)
