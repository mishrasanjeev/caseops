import hashlib
import ssl
import subprocess
from pathlib import Path

denied = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"
entry = "mozilla/emSign_ECC_Root_CA_-_G3.crt"
before = {
    hashlib.sha256(cert).hexdigest()
    for cert in ssl.create_default_context().get_ca_certs(binary_form=True)
}
certificate = Path("/usr/share/ca-certificates") / entry
if certificate.exists():
    pem = certificate.read_text()
    if hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() != denied:
        raise RuntimeError("Expected Debian CA identity differs.")
elif denied in before:
    raise RuntimeError("Expected Debian CA identity differs.")
config = Path("/etc/ca-certificates.conf")
lines = config.read_text().splitlines(keepends=True)
enabled = sum(line.strip() == entry for line in lines)
if enabled > 1 or (denied in before and enabled != 1):
    raise RuntimeError("Expected Debian CA configuration differs.")
if enabled:
    config.write_text("".join("!" + line if line.strip() == entry else line for line in lines))
subprocess.run(["update-ca-certificates", "--fresh"], check=True)
context = ssl.create_default_context()
after = {hashlib.sha256(cert).hexdigest() for cert in context.get_ca_certs(binary_form=True)}
if not (after and denied not in after and after == before - {denied}
        and context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname):
    raise RuntimeError("Debian CA removal changed unrelated trust or verification.")
