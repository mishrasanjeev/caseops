"""Opt-in pinned-Mac proof. Generates private synthetic keys only outside Git.

No outbound network, owner keys, installed package changes or global trust edits.
Portable unittest source controls are the separate host-platform-trust.test.py.
"""

import argparse
import json
import os
import ssl
import subprocess
import sys
import threading
import time
import types
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def load_helper():
    path = Path(__file__).resolve().parents[2] / "host-platform-trust.py"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        initial = os.fstat(fd)
        if not 0 < initial.st_size <= 1048576:
            raise ValueError("HELPER_SOURCE_BOUND")
        body = bytearray()
        while len(body) <= initial.st_size:
            part = os.read(fd, min(65536, initial.st_size + 1 - len(body)))
            if not part:
                break
            body.extend(part)
        fields = (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
            "st_uid",
            "st_gid",
            "st_mode",
            "st_nlink",
        )

        def same(value):
            return tuple(getattr(value, key) for key in fields)

        if (
            len(body) != initial.st_size
            or same(os.fstat(fd)) != same(initial)
            or same(path.stat()) != same(initial)
        ):
            raise ValueError("HELPER_SOURCE_CHANGED")
    finally:
        os.close(fd)
    module = types.ModuleType("held_host_trust")
    module.__file__ = str(path)
    exec(compile(body, str(path), "exec"), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", nargs=3, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-python", type=Path, required=True)
    parser.add_argument("--audit-python", type=Path, required=True)
    args = parser.parse_args()
    trust = load_helper()
    trust.need(sys.version_info[:3] == (3, 13, 17), "PINNED_PYTHON_PROOF_REQUIRED")
    # This dependency belongs to the closed accepted API environment, not a new
    # helper install. Its identity is recorded by the enclosing host proof.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    out = args.output
    trust.need(
        out.is_absolute() and out.parent.resolve() == out.parent and not out.exists(),
        "NEW_PROOF_OUTPUT_REQUIRED",
    )
    out.mkdir(mode=0o700)
    policy_ref = {
        "path": args.policy[0],
        "sha256": args.policy[1],
        "sizeBytes": int(args.policy[2]),
    }
    trust.read_ref(policy_ref)
    start = time.monotonic()
    end = start + 120
    keys, servers, threads, calls, requests_seen = [], [], [], [], []
    base = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(out),
        "TMPDIR": str(out),
        "LANG": "en_US.UTF-8",
    }

    def save(name, value):
        return trust.write_new(out / name, trust.json_bytes(value), deadline=end)

    def certificates(name):
        now = datetime.now(UTC)
        ca_key, leaf_key = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048),
            rsa.generate_private_key(public_exponent=65537, key_size=2048),
        )
        subject = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "CaseOps owned offline " + name)]
        )
        ca = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.KeyUsage(
                    False, False, False, False, False, True, True, None, None
                ),
                critical=True,
            )
            .sign(ca_key, hashes.SHA256())
        )
        leaf = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
            )
            .issuer_name(subject)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.KeyUsage(
                    True, False, True, False, False, False, False, None, None
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        ca_ref = trust.write_new(
            out / (name + "-ca.pem"), ca.public_bytes(serialization.Encoding.PEM)
        )
        leaf_ref = trust.write_new(
            out / (name + "-leaf.pem"), leaf.public_bytes(serialization.Encoding.PEM)
        )
        key = out / (name + "-synthetic.key")
        trust.write_new(
            key,
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        keys.append(key)
        return ca_ref, leaf_ref, key

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received = self.headers.get("X-CaseOps-Automated-Test")
            marked = received == "no-paid-providers"
            requests_seen.append(
                {
                    "path": self.path,
                    "marker": received
                    if received in {"no-paid-providers", "1", None}
                    else "unexpected",
                }
            )
            body = (
                b"public-trust-ok"
                if self.path == "/trust-probe" and marked
                else b"refused"
            )
            self.send_response(200 if body == b"public-trust-ok" else 403)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *unused):
            return

    def serve(leaf, key):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(leaf["path"], key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        server.socket.settimeout(3)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        thread.start()
        servers.append(server)
        threads.append(thread)
        return server.server_address[1]

    def call(name, argv, environment, expected):
        trust.need(time.monotonic() < end - 10, "PROOF_CLEANUP_RESERVE")
        process = subprocess.run(
            list(map(str, argv)),
            env=environment,
            capture_output=True,
            timeout=min(10, end - time.monotonic() - 10),
        )
        trust.need(
            len(process.stdout) + len(process.stderr) <= 1048576, "PROOF_LOG_BOUND"
        )
        trust.write_new(out / (name + ".stdout.log"), process.stdout or b"\n")
        trust.write_new(out / (name + ".stderr.log"), process.stderr or b"\n")
        calls.append(
            {
                "name": name,
                "exitCode": process.returncode,
                "expected": expected,
                "stdoutSha256": trust.sha(process.stdout),
                "stderrSha256": trust.sha(process.stderr),
            }
        )
        trust.need(process.returncode == expected, "ACTUAL_LOCAL_TLS_CONTROL_FAILED")
        return process.stdout

    error = None
    try:
        # Actual default contexts, not a mocked certificate list.
        py_env = trust.scoped_environment(policy_ref, "python", base)
        context = "import ssl,hashlib,json;c=ssl.create_default_context();v=sorted(hashlib.sha256(x).hexdigest()for x in c.get_ca_certs(binary_form=True));print(json.dumps({'count':len(v),'setSha256':hashlib.sha256(('\\n'.join(v)+'\\n').encode()).hexdigest(),'checkHostname':c.check_hostname,'verifyMode':int(c.verify_mode),'minimumVersion':int(c.minimum_version)}))"
        value = json.loads(
            call("python-default", [trust.PYTHON, "-I", "-B", "-c", context], py_env, 0)
        )
        trust.need(
            value["count"] == 127
            and value["setSha256"] == trust.CONTRACTS["python"][3]
            and value["checkHostname"] is True
            and value["verifyMode"] == 2
            and value["minimumVersion"] >= 771,
            "ACTUAL_PYTHON_DEFAULTS_REFUSED",
        )
        for runtime in ("java21", "java17"):
            value = trust.run_java(
                runtime,
                ["inspect"],
                trust.scoped_environment(policy_ref, runtime, base),
                end,
                calls.append,
            )
            trust.need(
                value
                == {
                    "count": 117,
                    "setSha256": trust.CONTRACTS["java"][3],
                    "deniedCount": 0,
                },
                "ACTUAL_JAVA_DEFAULTS_REFUSED",
            )
        good_ca, good_leaf, good_key = certificates("good")
        _, bad_leaf, bad_key = certificates("untrusted")
        fixture = save(
            "fixture-receipt.json",
            {
                "schemaVersion": 1,
                "kind": "caseops-owned-loopback-tls-fixture-v1",
                "noPaid": True,
                "network": "loopback-only",
                "hosts": ["localhost", "127.0.0.1"],
                "ca": good_ca,
            },
        )
        qa_ref = trust.prepare_qa_policy(
            policy_ref, fixture, out / "qa-policy", environment=base
        )
        good_port, unknown_port = serve(good_leaf, good_key), serve(bad_leaf, bad_key)
        probe = Path(__file__).with_name("python_tls_probe.py")
        routes = [
            ("trusted", f"https://localhost:{good_port}/trust-probe", 0),
            ("untrusted", f"https://localhost:{unknown_port}/trust-probe", 37),
            ("wronghost", f"https://127.0.0.1:{good_port}/trust-probe", 37),
        ]
        for mode, executable, request_scope in (
            ("urllib", trust.PYTHON, None),
            ("requests-api", args.api_python, "apiCertifi"),
            ("requests-audit", args.audit_python, "auditCertifi"),
        ):
            env = trust.scoped_environment(
                qa_ref,
                "python",
                base,
                requests_scope=request_scope,
                qa_fixture_reference=fixture,
            )
            for label, url, expected in routes:
                raw = call(
                    mode + "-" + label,
                    [
                        executable,
                        "-I",
                        "-B",
                        probe,
                        "urllib" if mode == "urllib" else "requests",
                        url,
                    ],
                    env,
                    expected,
                )
                trust.need(
                    json.loads(raw)["connected"] is (expected == 0),
                    "ACTUAL_PYTHON_TLS_OUTCOME",
                )
        for runtime in ("java21", "java17"):
            env = trust.scoped_environment(
                qa_ref, runtime, base, qa_fixture_reference=fixture
            )
            # run_java raises on negative37; retain those separately without retry.
            for label, url, expected in routes:
                logs = []
                try:
                    value = trust.run_java(
                        runtime, ["probe", url], env, end, logs.append
                    )
                    trust.need(
                        expected == 0 and value == {"connected": True},
                        "ACTUAL_JAVA_TLS_OUTCOME",
                    )
                except ValueError:
                    trust.need(
                        expected == 37 and len(logs) == 1 and logs[0]["exitCode"] == 37,
                        "ACTUAL_JAVA_TLS_NEGATIVE_REQUIRED",
                    )
                calls.append(
                    {"name": runtime + "-" + label, "expected": expected, "java": logs}
                )
        trust.need(
            len(requests_seen) == 5
            and all(
                row == {"path": "/trust-probe", "marker": "no-paid-providers"}
                for row in requests_seen
            ),
            "EVERY_REAL_HTTP_CONSTRUCTOR_MARKED",
        )
        save("qa-policy-reference.json", qa_ref)
    except BaseException as exc:
        error = {
            "class": type(exc).__name__,
            "code": str(exc)
            if str(exc).isupper() and len(str(exc)) < 128
            else "PROOF_REFUSED",
        }
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
        for key in keys:
            key.unlink()
        complete = not any(thread.is_alive() for thread in threads) and all(
            not key.exists() for key in keys
        )
        save(
            "summary.json",
            {
                "passed": error is None and complete,
                "error": error,
                "calls": calls,
                "actualHttpRequests": requests_seen,
                "syntheticPrivateKeysRemoved": all(not key.exists() for key in keys),
                "ownedServersClosed": complete,
                "seconds": time.monotonic() - start,
                "limits": {"seconds": 120, "childSeconds": 10, "reserveSeconds": 10},
                "policy": policy_ref,
                "scope": "One pinned-Mac public-store/default-context/localTLS proof; no outbound, global trust, owner key or native/build acceptance.",
            },
        )
    raise SystemExit(0 if error is None and complete else 1)


if __name__ == "__main__":
    main()
