"""QG-SEC-003 / PYA561-01..05: offline pyasn1 0.6.5 compatibility contracts.

Small fixtures cover the four patched decoder paths, not DoS resistance or
CaseOps endpoint reachability. Resolver, audit and release gates remain separate.
Upstream guidance: https://github.com/pyasn1/pyasn1/pull/132
"""

from __future__ import annotations

import io
import socket
import sys
import tomllib
from importlib.metadata import distribution, version
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

API_ROOT = Path(__file__).resolve().parents[1]
TAIL = b"\x02\x01\x17"
CONSTRUCTED_MODES = [
    ("ber", False), ("ber", True), ("cer", False), ("cer", True), ("der", False),
]
MODE_IDS = ["ber-def", "ber-indef", "cer-def", "cer-indef", "der-schema-def"]
# Publisher metadata reviewed in PYASN1-SECURITY-20261031-01.md, not runtime downloads.
# https://pypi.org/project/pyasn1/0.6.5/#files
REVIEWED_ARTIFACTS = {
    "pyasn1-0.6.5-py3-none-any.whl": (
        "sha256:4017b0fce125096b8573b39c989fdb1a4b19cf761e683398184550fea0e66587"
    ),
    "pyasn1-0.6.5.tar.gz": (
        "sha256:6b11616a6bcf3a40e635f082bb232fa57b5e0dd7f517bd7ddd69ec3794508a47"
    ),
}


@pytest.fixture(autouse=True)
def deny_external_network(monkeypatch, request):
    attempts = []

    def reject_transport(*args, **kwargs):
        attempts.append("socket_or_DNS_call")
        raise AssertionError("Offline pyasn1 contract attempted network transport")

    for name in (
        "create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex",
        "gethostbyaddr", "getnameinfo",
    ):
        monkeypatch.setattr(socket, name, reject_transport)
    for name in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, reject_transport)
    try:
        yield
    finally:
        request.node.user_properties.append(("network_transport_attempts", len(attempts)))
        assert attempts == []


@pytest.fixture
def codecs(deny_external_network):
    from pyasn1.codec.ber import decoder as ber_decoder
    from pyasn1.codec.ber import encoder as ber_encoder
    from pyasn1.codec.cer import decoder as cer_decoder
    from pyasn1.codec.cer import encoder as cer_encoder
    from pyasn1.codec.der import decoder as der_decoder
    from pyasn1.codec.der import encoder as der_encoder

    return {
        "ber": (ber_encoder, ber_decoder),
        "cer": (cer_encoder, cer_decoder),
        "der": (der_encoder, der_decoder),
    }


def _locked_package(lock, name):
    rows = [row for row in lock["package"] if row["name"] == name]
    assert len(rows) == 1, f"Expected one locked {name} distribution"
    return rows[0]


def _tlv(identifier, body, indefinite=False):
    if len(body) > 127:
        raise ValueError("Offline fixtures must stay within short-form lengths")
    if indefinite:
        return bytes((identifier, 0x80)) + body + b"\x00\x00"
    return bytes((identifier, len(body))) + body


def test_manifest_lock_runtime_and_reviewed_artifact_identity():
    import pyasn1

    project = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [Requirement(text) for text in project["project"]["dependencies"]]
    declared = [item for item in requirements if canonicalize_name(item.name) == "pyasn1"]
    assert len(declared) == 1
    assert str(declared[0].specifier) == ">=0.6.5"
    assert declared[0].marker is None and declared[0].url is None
    assert Version("0.6.4") not in declared[0].specifier
    assert Version("0.6.5") in declared[0].specifier

    lock = tomllib.loads((API_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = _locked_package(lock, "pyasn1")
    installed = version("pyasn1")
    assert locked["version"] == installed == pyasn1.__version__ == "0.6.5"
    assert locked["source"] == {"registry": "https://pypi.org/simple"}
    artifacts = [locked["sdist"], *locked["wheels"]]
    assert len(artifacts) == 2
    observed = {}
    for artifact in artifacts:
        location = urlsplit(artifact["url"])
        assert location.scheme == "https" and location.netloc == "files.pythonhosted.org"
        observed[location.path.rsplit("/", 1)[-1]] = artifact["hash"]
    assert observed == REVIEWED_ARTIFACTS


def test_pyasn1_modules_constraint_accepts_the_locked_runtime():
    import pyasn1_modules

    lock = tomllib.loads((API_ROOT / "uv.lock").read_text(encoding="utf-8"))
    modules = _locked_package(lock, "pyasn1-modules")
    pyasn1 = _locked_package(lock, "pyasn1")
    installed = distribution("pyasn1-modules")
    requirements = [Requirement(text) for text in installed.requires or []]
    constraints = [item for item in requirements if canonicalize_name(item.name) == "pyasn1"]
    assert installed.version == modules["version"] == pyasn1_modules.__version__ == "0.4.2"
    assert len(constraints) == 1
    constraint = constraints[0]
    # https://github.com/pyasn1/pyasn1-modules/blob/v0.4.2/setup.cfg
    assert str(constraint.specifier) == "<0.7.0,>=0.6.1"
    assert constraint.marker is None and constraint.url is None
    assert Version("0.6.5") in constraint.specifier
    assert Version("0.7.0") not in constraint.specifier
    installed_pyasn1 = version("pyasn1")
    assert installed_pyasn1 == pyasn1["version"]
    assert Version(installed_pyasn1) in constraint.specifier
    assert modules["dependencies"] == [{"name": "pyasn1"}]


@pytest.mark.parametrize("codec_name", ["ber", "cer", "der"])
def test_normal_round_trips_with_and_without_schema_preserve_remainder(codecs, codec_name):
    from pyasn1.type import char, namedtype, univ

    encoder, decoder = codecs[codec_name]
    record_schema = univ.Sequence(componentType=namedtype.NamedTypes(
        namedtype.NamedType("number", univ.Integer()),
        namedtype.NamedType("label", univ.OctetString()),
    ))
    record = record_schema.clone()
    record["number"] = 23
    record["label"] = b"offline"
    values = [
        (univ.Integer(-23), univ.Integer()),
        (univ.Boolean(True), univ.Boolean()),
        (univ.BitString(binValue="001011001"), univ.BitString()),
        (univ.OctetString(b"CaseOps\x00offline"), univ.OctetString()),
        (char.UTF8String("CaseOps"), char.UTF8String()),
        (univ.ObjectIdentifier((1, 2, 840, 113549)), univ.ObjectIdentifier()),
        (univ.Real((13, 2, -2)), univ.Real()),
        (record, record_schema),
    ]
    completed = 0
    for original, schema in values:
        wire = encoder.encode(original)
        for spec in (None, schema):
            decoded, remainder = decoder.decode(wire + TAIL, asn1Spec=spec)
            reencoded = encoder.encode(decoded)
            trailing_value, trailing_remainder = decoder.decode(remainder)
            assert decoded == original
            assert decoded.tagSet == original.tagSet
            assert decoded.isValue
            assert reencoded == wire
            assert remainder == TAIL
            assert trailing_value == 23 and trailing_remainder == b""
            completed += 1
    assert completed == 16


@pytest.mark.parametrize("codec_name,indefinite", CONSTRUCTED_MODES, ids=MODE_IDS)
def test_constructed_bit_strings_preserve_padding_empty_and_aligned_fragments(
    codecs, codec_name, indefinite,
):
    from pyasn1.error import PyAsn1Error
    from pyasn1.type import univ

    _, decoder = codecs[codec_name]
    fixtures = [
        (b"\x03\x02\x00\x81" * 8, "10000001" * 8),
        (b"\x03\x02\x04\x20\x03\x01\x00\x03\x02\x06\xc0\x03\x02\x01\x56",
         "0010110101011"),
        (b"\x03\x01\x00", ""),
    ]
    specs = (univ.BitString(),) if codec_name == "der" else (None, univ.BitString())
    completed = 0
    for fragments, expected in fixtures:
        wire = _tlv(0x23, fragments, indefinite)
        expected_bits = tuple(int(bit) for bit in expected)
        for spec in specs:
            decoded, remainder = decoder.decode(wire + TAIL, asn1Spec=spec)
            bits = tuple(decoded)
            assert bits == expected_bits
            assert len(decoded) == len(expected)
            assert remainder == TAIL
            completed += 1
        if codec_name == "der":
            with pytest.raises(PyAsn1Error):
                decoder.decode(wire)
    assert completed == (3 if codec_name == "der" else 6)
    for invalid in (b"\x03\x02\x08\xff", b"\x03\x01\x01"):
        wire = _tlv(0x23, invalid, indefinite)
        with pytest.raises(PyAsn1Error):
            decoder.decode(wire, asn1Spec=univ.BitString())


@pytest.mark.parametrize("codec_name,indefinite", CONSTRUCTED_MODES, ids=MODE_IDS)
def test_constructed_octet_and_character_strings_keep_decoded_nested_values(
    codecs, codec_name, indefinite,
):
    from pyasn1.error import PyAsn1Error
    from pyasn1.type import char, univ

    _, decoder = codecs[codec_name]
    fragments = [b"\x04\x02CA\x04\x02SE"]
    inner_modes = (False,) if codec_name == "der" else (False, True)
    for inner_indefinite in inner_modes:
        nested = _tlv(0x24, b"\x04\x02CA", inner_indefinite)
        fragments.append(nested + b"\x04\x02SE")
    specs = (univ.OctetString(),) if codec_name == "der" else (None, univ.OctetString())
    completed = 0
    for body in fragments:
        wire = _tlv(0x24, body, indefinite)
        for spec in specs:
            decoded, remainder = decoder.decode(wire + TAIL, asn1Spec=spec)
            octets = decoded.asOctets()
            assert octets == b"CASE"
            assert remainder == TAIL
            completed += 1
        if codec_name == "der":
            with pytest.raises(PyAsn1Error):
                decoder.decode(wire)
    wire = _tlv(0x2C, b"\x0c\x02CA\x0c\x02SE", indefinite)
    for spec in (None, char.UTF8String()):
        decoded, remainder = decoder.decode(wire + TAIL, asn1Spec=spec)
        text = str(decoded)
        assert text == "CASE"
        assert remainder == TAIL
        completed += 1
    assert completed == (4 if codec_name == "der" else 8)
    malformed = _tlv(0x24, b"\x02\x01\x07", indefinite)
    with pytest.raises(PyAsn1Error):
        decoder.decode(malformed, asn1Spec=univ.OctetString())
    if codec_name == "der":
        for identifier, spec in ((0x24, univ.OctetString()), (0x30, univ.Any())):
            non_der = _tlv(identifier, b"\x04\x02CA", True)
            with pytest.raises(PyAsn1Error):
                decoder.decode(non_der, asn1Spec=spec)


@pytest.mark.parametrize("codec_name", ["ber", "cer"])
def test_any_preserves_definite_and_nested_indefinite_content(codecs, codec_name):
    from pyasn1.error import SubstrateUnderrunError
    from pyasn1.type import tag, univ

    _, decoder = codecs[codec_name]
    body = b"\x04\x02CA\x02\x01\x07"
    definite = _tlv(0x30, body)
    indefinite = _tlv(0x30, body, True)
    tagged = univ.Any().subtype(explicitTag=tag.Tag(
        tag.tagClassContext, tag.tagFormatConstructed, 3,
    ))
    # ANY's indefinite path omits consumed EOC markers, including nested ones.
    fixtures = [
        (definite, univ.Any(), definite),
        (indefinite, univ.Any(), b"\x30\x80" + body),
        (_tlv(0x30, definite, True), univ.Any(), b"\x30\x80" + definite),
        (_tlv(0x30, indefinite, True), univ.Any(), b"\x30\x80\x30\x80" + body),
        (_tlv(0xA3, body, True), tagged, body),
    ]
    completed = 0
    for wire, schema, expected in fixtures:
        decoded, remainder = decoder.decode(wire + TAIL, asn1Spec=schema)
        captured = bytes(decoded)
        assert captured == expected
        assert remainder == TAIL
        completed += 1
    assert completed == 5
    with pytest.raises(SubstrateUnderrunError):
        decoder.decode(indefinite[:-2], asn1Spec=univ.Any())


@pytest.mark.parametrize("codec_name", ["ber", "cer", "der"])
def test_binary_real_preserves_mantissa_sign_scale_and_exponent(codecs, codec_name):
    from pyasn1.error import PyAsn1Error
    from pyasn1.type import univ

    _, decoder = codecs[codec_name]
    mantissa = b"\x81" + b"\x23" * 15
    integer = int.from_bytes(mantissa, "big")
    fixtures = [
        (b"\x80\x00" + mantissa, (integer, 2, 0)),
        (b"\xc0\xfd" + mantissa, (-integer, 2, -3)),
        (b"\x94\xff\x0d", (26, 2, -3)),
        (b"\xa0\xfe\x01", (1, 2, -8)),
    ]
    completed = 0
    for body, expected in fixtures:
        wire = _tlv(0x09, body)
        for spec in (None, univ.Real()):
            decoded, remainder = decoder.decode(wire + TAIL, asn1Spec=spec)
            value = tuple(decoded)
            assert value == expected
            assert remainder == TAIL
            completed += 1
    assert completed == 8
    with pytest.raises(PyAsn1Error):
        decoder.decode(b"\x09\x01\x80", asn1Spec=univ.Real())


class _IncrementalStream(io.BytesIO):
    def read(self, size=-1):
        chunk = super().read(size)
        return None if size and not chunk else chunk


def _incremental_decode(decoder, wire):
    from pyasn1.error import SubstrateUnderrunError

    with _IncrementalStream() as stream:
        iterator = iter(decoder.StreamingDecoder(stream))
        supplied = 0
        underruns = 0
        try:
            for _ in range(len(wire) + 1):
                decoded = next(iterator)
                if not isinstance(decoded, SubstrateUnderrunError):
                    break
                assert supplied < len(wire), "Decoder did not resume after complete input"
                position = stream.tell()
                stream.seek(0, io.SEEK_END)
                supplied += stream.write(wire[supplied:supplied + 3])
                stream.seek(position)
                underruns += 1
            else:
                pytest.fail("Decoder exceeded the finite fixture feed inventory")
            consumed = stream.tell()
            assert supplied == consumed == len(wire)
            assert underruns > 1
            return decoded
        finally:
            iterator.close()


def _assert_container(decoded, expected_type, tag_ids):
    from pyasn1.type import tag, univ

    assert type(decoded) is expected_type
    assert len(decoded) == len(tag_ids)
    for index, tag_id in enumerate(tag_ids):
        component = decoded.getComponentByPosition(index)
        octets = component.asOctets()
        expected_tag = univ.OctetString.tagSet.tagExplicitly(tag.Tag(
            tag.tagClassContext, tag.tagFormatConstructed, tag_id,
        ))
        assert type(component) is univ.OctetString
        assert octets == bytes((index + 1,))
        assert component.tagSet == expected_tag


@pytest.mark.parametrize("codec_name", ["ber", "cer", "der"])
def test_schemaless_container_types_collisions_and_incremental_resume(
    codecs, codec_name, monkeypatch,
):
    from pyasn1.type import tag, univ

    ber_encoder, _ = codecs["ber"]
    _, decoder = codecs[codec_name]
    modes = (False,) if codec_name == "der" else (False, True)
    colliding = tuple(37 + index * sys.hash_info.modulus for index in range(8))
    original_eq = tag.TagSet.__eq__
    comparisons = 0

    def counted_eq(left, right):
        nonlocal comparisons
        if (isinstance(right, tag.TagSet) and len(left) == len(right) == 2
                and left[-1].tagClass == right[-1].tagClass == tag.tagClassContext):
            comparisons += 1
        return original_eq(left, right)

    completed = streamed = 0
    for identifier, homogeneous, heterogeneous in (
        (0x30, univ.SequenceOf, univ.Sequence), (0x31, univ.SetOf, univ.Set),
    ):
        for indefinite in modes:
            for tag_ids, expected_type in (
                ((37, 37, 37), homogeneous), ((37, 37, 38, 39, 37), heterogeneous),
                (colliding, heterogeneous),
            ):
                components = [univ.OctetString(bytes((index + 1,))).subtype(
                    explicitTag=tag.Tag(tag.tagClassContext, tag.tagFormatConstructed, tag_id),
                ) for index, tag_id in enumerate(tag_ids)]
                body = b"".join(ber_encoder.encode(component) for component in components)
                wire = _tlv(identifier, body, indefinite)
                comparisons = 0
                with monkeypatch.context() as guard:
                    if tag_ids == colliding:
                        hashes = {hash(component.tagSet) for component in components}
                        assert len(hashes) == 1
                        guard.setattr(tag.TagSet, "__eq__", counted_eq)
                    decoded, remainder = decoder.decode(wire + TAIL)
                _assert_container(decoded, expected_type, tag_ids)
                assert remainder == TAIL
                if tag_ids == colliding:
                    assert 0 < comparisons <= 8
                else:
                    resumed = _incremental_decode(decoder, wire)
                    _assert_container(resumed, expected_type, tag_ids)
                    streamed += 1
                completed += 1
    assert completed == (6 if codec_name == "der" else 12)
    assert streamed == (4 if codec_name == "der" else 8)


@pytest.mark.parametrize("schema_name", ["x509", "pkcs8"])
def test_benign_modules_schema_fixtures_round_trip_without_keys_or_transport(codecs, schema_name):
    from pyasn1.type import univ
    from pyasn1_modules import rfc5208, rfc5280

    encoder, decoder = codecs["der"]
    if schema_name == "x509":
        schema = rfc5280.Extension()
        value = schema.clone()
        value["extnID"] = rfc5280.id_ce_basicConstraints
        value["critical"] = True
        value["extnValue"] = bytes.fromhex("30 06 01 01 ff 02 01 01")
        expected = bytes.fromhex("30 12 06 03 55 1d 13 01 01 ff 04 08 30 06 01 01 ff 02 01 01")
    else:
        schema = rfc5208.PrivateKeyInfo()
        value = schema.clone()
        value["version"] = 0
        value["privateKeyAlgorithm"]["algorithm"] = univ.ObjectIdentifier("1.2.840.113549.1.1.1")
        value["privateKeyAlgorithm"]["parameters"] = b"\x05\x00"
        # Opaque schema-only bytes, not an RSA key or cryptographic acceptance.
        value["privateKey"] = b"offline-not-a-key"
        expected = bytes.fromhex(
            "30 25 02 01 00 30 0d 06 09 2a 86 48 86 f7 0d 01 01 01 05 00 04 11",
        )
        expected += b"offline-not-a-key"
    wire = encoder.encode(value)
    decoded, remainder = decoder.decode(wire + TAIL, asn1Spec=schema)
    reencoded = encoder.encode(decoded)
    assert wire == expected == reencoded
    assert remainder == TAIL
    if schema_name == "x509":
        assert decoded == value
        inner, inner_remainder = decoder.decode(
            decoded["extnValue"].asOctets(), asn1Spec=rfc5280.BasicConstraints(),
        )
        ca = bool(inner["cA"])
        path_length = int(inner["pathLenConstraint"])
        assert ca and path_length == 1
        assert inner_remainder == b""
    else:
        # Omitted optional attributes are schema objects, not comparable values.
        decoded_version = int(decoded["version"])
        supplied_attributes = value["attributes"].hasValue()
        decoded_attributes = decoded["attributes"].hasValue()
        payload = decoded["privateKey"].asOctets()
        algorithm = tuple(decoded["privateKeyAlgorithm"]["algorithm"])
        parameters = bytes(decoded["privateKeyAlgorithm"]["parameters"])
        assert decoded_version == int(value["version"]) == 0
        assert supplied_attributes is False and decoded_attributes is False
        assert payload == b"offline-not-a-key"
        assert algorithm == (1, 2, 840, 113549, 1, 1, 1)
        assert parameters == b"\x05\x00"
