import ast
import hashlib
import ssl
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
DENIED = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"


def _exercise_policy(tmp_path, before, after, certificate, entry, *, verify=True, hostname=True):
    source = DOCKERFILE.read_text()
    policy = source.split("RUN python - <<'CA_POLICY'\n", 1)[1].split("\nCA_POLICY", 1)[0]
    tree = ast.parse(policy)
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    # Bind a synthetic known identity; the separate source contract pins the real G3 hash.
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == "denied":
                assert node.value.value == DENIED
                node.value = ast.Constant(hashlib.sha256(b"g3").hexdigest())
    certificates = tmp_path / "certificates"
    certificates.mkdir()
    if certificate is not None:
        (certificates / "mozilla").mkdir()
        (certificates / "mozilla/emSign_ECC_Root_CA_-_G3.crt").write_text(certificate)
    config = tmp_path / "ca-certificates.conf"
    known_entry = "mozilla/emSign_ECC_Root_CA_-_G3.crt\n"
    config.write_text(
        "mozilla/Other.crt\n"
        + {"enabled": known_entry, "disabled": "!" + known_entry, "absent": ""}[entry]
    )
    contexts = iter(
        SimpleNamespace(
            get_ca_certs=lambda binary_form, roots=roots: roots,
            verify_mode=ssl.CERT_REQUIRED if safe else ssl.CERT_NONE,
            check_hostname=check_hostname,
        )
        for roots, safe, check_hostname in ((before, True, True), (after, verify, hostname))
    )
    update = Mock()
    paths = {"/usr/share/ca-certificates": certificates, "/etc/ca-certificates.conf": config}
    namespace = {
        "hashlib": hashlib,
        "Path": paths.__getitem__,
        "ssl": SimpleNamespace(
            create_default_context=lambda: next(contexts),
            PEM_cert_to_DER_cert=lambda pem: pem.encode(),
            CERT_REQUIRED=ssl.CERT_REQUIRED,
        ),
        "subprocess": SimpleNamespace(run=update),
    }
    exec(compile(ast.fix_missing_locations(tree), str(DOCKERFILE), "exec"), namespace)
    update.assert_called_once_with(["update-ca-certificates", "--fresh"], check=True)
    assert "mozilla/Other.crt\n" in config.read_text()
    assert known_entry not in config.read_text().splitlines(keepends=True)


@pytest.mark.parametrize(
    ("before", "certificate", "entry"),
    [
        ([b"other", b"g3"], "g3", "enabled"),
        ([b"other"], "g3", "disabled"),
        ([b"other"], "g3", "absent"),
        ([b"other"], None, "absent"),
        ([b"other"], None, "enabled"),
    ],
    ids=["present", "already-disabled", "entry-removed", "certificate-removed", "stale-entry"],
)
def test_ca_removal_accepts_only_known_or_already_secure_states(
    tmp_path, before, certificate, entry
):
    _exercise_policy(tmp_path, before, [b"other"], certificate, entry)


@pytest.mark.parametrize("before", [[b"other", b"g3"], [b"other"]], ids=["effective", "absent"])
def test_ca_removal_rejects_wrong_known_file_identity(tmp_path, before):
    with pytest.raises(RuntimeError, match="identity differs"):
        _exercise_policy(tmp_path, before, [b"other"], "wrong", "enabled")


@pytest.mark.parametrize(
    ("certificate", "entry"), [(None, "enabled"), ("g3", "disabled"), ("g3", "absent")]
)
def test_ca_removal_rejects_unexplained_effective_root(tmp_path, certificate, entry):
    with pytest.raises(RuntimeError):
        _exercise_policy(tmp_path, [b"other", b"g3"], [b"other"], certificate, entry)


@pytest.mark.parametrize(
    ("after", "verify", "hostname"),
    [
        ([b"other", b"g3"], True, True),
        ([b"other", b"extra"], True, True),
        ([], True, True),
        ([b"other"], False, True),
        ([b"other"], True, False),
    ],
    ids=["g3-retained", "extra-root", "roots-lost", "verification-disabled", "hostname-disabled"],
)
def test_ca_removal_rejects_unsafe_effective_after_state(tmp_path, after, verify, hostname):
    with pytest.raises(RuntimeError, match="changed unrelated trust or verification"):
        _exercise_policy(
            tmp_path, [b"other", b"g3"], after, "g3", "enabled", verify=verify, hostname=hostname
        )


def test_api_image_pins_fixed_uv_without_changing_python_base():
    source = DOCKERFILE.read_text()
    assert "FROM python:3.13-slim AS runtime-base" in source
    assert "RUN pip install --no-cache-dir uv==0.13.4" in source
    assert "uv==0.11.6" not in source


def test_api_bootstrap_selects_verified_patched_ca_before_pip():
    source = DOCKERFILE.read_text()
    policy = source.index("RUN python - <<'CA_POLICY'")
    pip_ca = source.index("PIP_CERT=/etc/ssl/certs/ca-certificates.crt")
    install = source.index("RUN pip install --no-cache-dir uv==0.13.4")
    assert policy < pip_ca < install
    assert "PIP_USE_DEPRECATED=legacy-certs" in source
    assert "trusted-host" not in source
    assert "CERT_NONE" not in source


def test_actual_ca_policy_checks_exact_root_and_preserves_all_other_roots():
    source = DOCKERFILE.read_text()
    policy = source.split("RUN python - <<'CA_POLICY'\n", 1)[1].split("\nCA_POLICY", 1)[0]
    ast.parse(policy)
    assert DENIED in policy
    assert 'entry = "mozilla/emSign_ECC_Root_CA_-_G3.crt"' in policy
    assert '["update-ca-certificates", "--fresh"]' in policy
    assert "after == before - {denied}" in policy
    assert "context.verify_mode == ssl.CERT_REQUIRED" in policy
    assert "context.check_hostname" in policy


def test_api_copies_only_reviewed_wheel_and_provenance_before_frozen_export():
    source = DOCKERFILE.read_text()
    export = source.index("RUN uv export")
    for name in (
        "fastembed-0.8.0-1caseops1-py3-none-any.whl",
        "fastembed-0.8.0-1caseops1.json",
    ):
        assert (DOCKERFILE.parent / "vendor" / name).is_file()
        assert source.index(f"COPY vendor/{name} ./vendor/") < export
    assert "COPY vendor/ ./vendor/" not in source
    assert "COPY vendor/*" not in source
    assert "rebuild_fastembed.py" not in source
    assert "--frozen" in source
