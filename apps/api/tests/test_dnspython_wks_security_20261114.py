"""CVE-2026-128089: bounded, offline tests of the shipped WKS parser.

Use the maintainer's small 65536-service witness, never a memory-exhaustion
payload. A parser pass does not establish an exposed CaseOps zone-file route.
"""

from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

import dns.exception
import dns.rdata
import dns.rdataclass
import dns.rdatatype
import pytest
from dns.rdtypes.IN.WKS import WKS


class WksServiceBoundsTests(unittest.TestCase):
    def setUp(self):
        for operation in ("connect", "connect_ex", "sendto"):
            self.enterContext(
                patch.object(
                    socket.socket,
                    operation,
                    side_effect=AssertionError("OFFLINE_DNS_PARSER_NETWORK_REFUSED"),
                )
            )
        self.enterContext(
            patch.object(
                socket,
                "getaddrinfo",
                side_effect=AssertionError("OFFLINE_DNS_PARSER_NETWORK_REFUSED"),
            )
        )

    def test_first_out_of_range_service_is_rejected(self):
        with self.assertRaises(dns.exception.SyntaxError):
            dns.rdata.from_text("IN", "WKS", "192.0.2.1 17 65536")

    def test_bounded_larger_services_are_rejected(self):
        for service in (65537, 1048576):
            with self.subTest(service=service):
                with self.assertRaises(dns.exception.SyntaxError):
                    dns.rdata.from_text("IN", "WKS", f"192.0.2.1 17 {service}")

    def test_negative_service_is_rejected(self):
        with patch.object(socket, "getservbyname", side_effect=OSError("NO_SERVICE")):
            with self.assertRaises(dns.exception.SyntaxError):
                dns.rdata.from_text("IN", "WKS", "192.0.2.1 17 -1")

    def test_exact_uint16_boundaries_and_service_bits_survive_wire_roundtrip(self):
        record = dns.rdata.from_text("IN", "WKS", "192.0.2.1 17 0 53 65535")
        self.assertEqual(record.address, "192.0.2.1")
        self.assertEqual(record.protocol, 17)
        self.assertEqual(len(record.bitmap), 8192)
        expected = bytearray(8192)
        for service in (0, 53, 65535):
            expected[service // 8] |= 0x80 >> (service % 8)
        self.assertEqual(record.bitmap, bytes(expected))
        wire = record.to_wire()
        self.assertEqual(wire, b"\xc0\x00\x02\x01\x11" + bytes(expected))
        restored = dns.rdata.from_wire(1, 11, wire, 0, len(wire))
        self.assertEqual(restored, record)
        self.assertEqual(restored.to_wire(), wire)

    def test_empty_service_list_remains_valid(self):
        record = dns.rdata.from_text("IN", "WKS", "192.0.2.1 17")
        self.assertEqual(record.bitmap, b"")
        self.assertEqual(record.to_wire(), b"\xc0\x00\x02\x01\x11")

    def test_named_service_uses_the_same_exact_bitmap(self):
        with patch.object(socket, "getservbyname", return_value=53) as lookup:
            record = dns.rdata.from_text("IN", "WKS", "192.0.2.1 17 domain")
        lookup.assert_called_once_with("domain", "udp")
        self.assertEqual(record.bitmap, b"\x00" * 6 + b"\x04")

    def test_out_of_range_named_service_lookup_is_rejected(self):
        with patch.object(socket, "getservbyname", return_value=65536) as lookup:
            with self.assertRaises(dns.exception.SyntaxError):
                dns.rdata.from_text("IN", "WKS", "192.0.2.1 17 synthetic-service")
        lookup.assert_called_once_with("synthetic-service", "udp")

    def test_constructor_accepts_both_valid_bitmap_extents(self):
        for width in (0, 8192):
            with self.subTest(width=width):
                record = WKS(1, 11, "192.0.2.1", 17, b"\x01" * width)
                self.assertEqual(record.bitmap, b"\x01" * width)

    def test_constructor_rejects_first_oversized_bitmap(self):
        with self.assertRaisesRegex(ValueError, "service bitmap"):
            WKS(1, 11, "192.0.2.1", 17, b"\x00" * 8193)

    def test_wire_reader_rejects_first_oversized_bitmap(self):
        wire = b"\xc0\x00\x02\x01\x11" + b"\x00" * 8193
        with self.assertRaises(dns.exception.FormError):
            dns.rdata.from_wire(1, 11, wire, 0, len(wire))



# Preserve the independent mainline pytest boundary inventory as well.
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


if __name__ == "__main__":
    unittest.main()
