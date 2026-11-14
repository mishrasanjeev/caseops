"""CVE-2026-128089: offline protocol bounds, without oversized allocations."""

import socket

import dns.exception
import dns.rdata
import dns.rdataclass
import dns.rdatatype
import pytest
from dns.rdtypes.IN.WKS import WKS


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("WKS regression must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket.socket, "connect_ex", refused)
    monkeypatch.setattr(socket, "create_connection", refused)


@pytest.mark.parametrize("service", ["-1", "65536"])
def test_wks_text_refuses_out_of_range_service_before_bitmap_growth(service):
    # The upper negative is only one bit beyond the bound: safe on old versions.
    with pytest.raises(dns.exception.SyntaxError):
        dns.rdata.from_text("IN", "WKS", f"10.0.0.1 udp {service}")


def test_wks_constructor_refuses_an_oversize_service_bitmap():
    with pytest.raises(ValueError, match="8192"):
        WKS(dns.rdataclass.IN, dns.rdatatype.WKS, "10.0.0.1", 17, bytes(8193))


def test_wks_wire_parser_refuses_an_oversize_service_bitmap():
    wire = bytes([10, 0, 0, 1, 17]) + bytes(8193)
    with pytest.raises(dns.exception.FormError):
        dns.rdata.from_wire("IN", "WKS", wire, 0, len(wire))


@pytest.mark.parametrize("service", [0, 53, 65535])
def test_valid_wks_services_retain_their_bit_and_exact_wire_roundtrip(service):
    record = dns.rdata.from_text("IN", "WKS", f"10.0.0.1 udp {service}")
    assert record.address == "10.0.0.1"
    assert record.protocol == 17
    assert len(record.bitmap) == service // 8 + 1 <= 8192
    assert record.bitmap[service // 8] == 0x80 >> (service % 8)
    wire = record.to_wire()
    restored = dns.rdata.from_wire("IN", "WKS", wire, 0, len(wire))
    assert restored == record
    assert restored.to_wire() == wire


@pytest.mark.parametrize("size", [0, 8192])
def test_wks_constructor_preserves_legal_empty_and_maximum_bitmap(size):
    record = WKS(dns.rdataclass.IN, dns.rdatatype.WKS, "10.0.0.1", 17, bytes(size))
    assert record.bitmap == bytes(size)
