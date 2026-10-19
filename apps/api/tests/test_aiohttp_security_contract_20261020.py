"""Native dependency contracts; no provider or HTTP transport is permitted."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import socket
import tomllib
from http.cookies import SimpleCookie
from importlib.machinery import EXTENSION_SUFFIXES, ExtensionFileLoader
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

API_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.filterwarnings("error::ResourceWarning")


@pytest.fixture(autouse=True)
def offline_loop(monkeypatch, request):
    # Windows may need its internal socketpair while creating the event loop.
    loop = asyncio.new_event_loop()
    attempts = []

    def reject_transport(*args, **kwargs):
        attempts.append("socket_or_DNS_call")
        raise AssertionError("Dependency contract attempted network transport")

    try:
        with monkeypatch.context() as guard:
            guard.setattr(socket, "create_connection", reject_transport)
            guard.setattr(socket, "getaddrinfo", reject_transport)
            guard.setattr(socket.socket, "connect", reject_transport)
            guard.setattr(socket.socket, "connect_ex", reject_transport)
            yield loop
            request.node.user_properties.append(("network_transport_attempts", len(attempts)))
            assert attempts == []
    finally:
        loop.close()


def test_declared_and_locked_security_versions_match_installed_packages():
    project = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((API_ROOT / "uv.lock").read_text(encoding="utf-8"))
    requirement = next(
        Requirement(value) for value in project["project"]["dependencies"]
        if Requirement(value).name == "aiohttp"
    )
    assert Version("3.14.3") not in requirement.specifier
    assert Version("3.14.4") in requirement.specifier
    locked = {item["name"]: item["version"] for item in lock["package"]}
    assert Version(locked["aiohttp"]) >= Version("3.14.4")
    assert Version(locked["yarl"]) >= Version("1.25.1")
    for name in ("aiohttp", "yarl", "voyageai"):
        assert version(name) == locked[name]


@pytest.mark.parametrize("name", [
    "aiohttp._http_parser", "aiohttp._http_writer",
    "aiohttp._websocket.reader_c", "yarl._quoting_c",
])
def test_native_dependency_c_extensions_import(name, request):
    module = importlib.import_module(name)
    assert isinstance(module.__loader__, ExtensionFileLoader)
    binary = Path(module.__file__)
    assert binary.is_file()
    assert any(str(binary).endswith(suffix) for suffix in EXTENSION_SUFFIXES)
    if name == "aiohttp._http_parser":
        parser = importlib.import_module("aiohttp.http_parser")
        assert parser.HttpResponseParser is module.HttpResponseParser
    request.node.user_properties.extend([
        ("native_module", name), ("native_file", str(binary)),
        ("native_sha256", hashlib.sha256(binary.read_bytes()).hexdigest()),
    ])


@pytest.mark.parametrize("schemes", [
    ("http", "https", "http", "https", "http"),
    ("https", "https", "http", "https", "http"),
], ids=["http-first", "https-cache-first"])
def test_shared_secure_cookie_never_leaks_over_http(offline_loop, schemes):
    async def exercise():
        from aiohttp import CookieJar
        from yarl import URL

        jar = CookieJar()
        cookies = SimpleCookie()
        cookies["shared-secure"] = "secure-control"
        cookies["shared-secure"]["secure"] = True
        cookies["shared-plain"] = "plain-control"
        jar.update_cookies(cookies, response_url=URL())
        stored = {cookie.key: cookie for cookie in jar}
        assert set(stored) == {"shared-secure", "shared-plain"}
        assert stored["shared-secure"]["domain"] == ""
        assert stored["shared-secure"]["secure"]
        visited = []
        # Upstream test_filter_cookies_with_secure_shared_cookie, plus cache-first RED.
        for scheme in schemes:
            visited.append(scheme)
            filtered = jar.filter_cookies(URL(f"{scheme}://cookie-contract.invalid/path"))
            assert filtered["shared-plain"].value == "plain-control"
            if scheme == "https":
                assert filtered["shared-secure"].value == "secure-control"
                assert "shared-secure" in jar._morsel_cache[("", "")]
            else:
                assert set(filtered) == {"shared-plain"}, f"Secure shared leak after {visited}"
            assert len(jar) == 2

    offline_loop.run_until_complete(asyncio.wait_for(exercise(), timeout=2.0))


def test_host_bound_secure_cookie_keeps_host_and_scheme_fences(offline_loop):
    async def exercise():
        from aiohttp import CookieJar
        from yarl import URL

        jar = CookieJar()
        cookies = SimpleCookie("host-secure=control; Secure")
        jar.update_cookies(cookies, URL("https://cookie-contract.invalid/path"))
        for scheme in ("https", "http", "https", "http", "https"):
            filtered = jar.filter_cookies(URL(f"{scheme}://cookie-contract.invalid/path"))
            assert set(filtered) == ({"host-secure"} if scheme == "https" else set())
            assert not jar.filter_cookies(URL("https://foreign-contract.invalid/path"))
        assert len(jar) == 1

    offline_loop.run_until_complete(asyncio.wait_for(exercise(), timeout=2.0))


def test_native_client_construction_and_disposal_are_bounded_and_offline(offline_loop):
    async def exercise():
        from aiohttp import ClientSession, ClientTimeout, TCPConnector

        connector = TCPConnector(limit=1, limit_per_host=1)
        timeout = ClientTimeout(total=1.0, connect=0.25, sock_connect=0.25, sock_read=0.5)
        session = ClientSession(connector=connector, timeout=timeout, trust_env=False)
        try:
            async with session:
                assert not session.closed and not connector.closed
                assert session.timeout.total == 1.0 and session.timeout.connect == 0.25
                assert connector.limit == connector.limit_per_host == 1
                assert not session.trust_env
            assert session.closed and connector.closed
        finally:
            await session.close()
            await connector.close()

    offline_loop.run_until_complete(asyncio.wait_for(exercise(), timeout=2.0))


@pytest.mark.parametrize("client_name", ["Client", "AsyncClient"])
def test_real_voyage_sdk_import_and_construction_need_no_network(client_name):
    voyage = importlib.import_module("voyageai")
    before_async = voyage.aiosession.get()
    before_sync = voyage.requestssession
    client = getattr(voyage, client_name)(
        api_key="offline-contract-not-a-key", max_retries=0,
        timeout=1.0, base_url="https://voyage-contract.invalid",
    )
    assert client.max_retries == 0
    assert client._params["request_timeout"] == 1.0
    assert client._params["base_url"] == "https://voyage-contract.invalid"
    assert voyage.aiosession.get() is before_async
    assert voyage.requestssession is before_sync
