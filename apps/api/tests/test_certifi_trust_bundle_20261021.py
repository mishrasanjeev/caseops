import ssl
from pathlib import Path

import certifi
from cryptography import x509
from cryptography.x509.oid import NameOID


def test_certifi_bundle_excludes_compromised_emsign_g3_root():
    certificates = x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes())
    assert certificates
    common_names = {
        attribute.value
        for certificate in certificates
        for attribute in certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    }
    assert "emSign ECC Root CA - G3" not in common_names


def test_certifi_tls_context_requires_verified_hostname_and_nonempty_ca_store():
    context = ssl.create_default_context(cafile=certifi.where())
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] > 0
