from urllib.parse import urlsplit

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from starlette.responses import RedirectResponse, StreamingResponse


class TlsTerminatedProxy:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "scheme": "http"}
        await self.app(scope, receive, send)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("canonical", ["/api/redirect-probe/", "/api/redirect-probe"])
def test_router_redirect_preserves_public_tls_method_body_and_auth(client, method, canonical):
    observed = []

    async def endpoint(request: Request):
        observed.append(
            (request.method, await request.body(), request.headers.get("authorization"))
        )
        return {"query": request.url.query}

    client.app.add_api_route(canonical, endpoint, methods=[method])
    upstream = TestClient(TlsTerminatedProxy(client.app), base_url="https://testserver")
    path = canonical.rstrip("/") if canonical.endswith("/") else canonical + "/"
    query = "name=a%2Fb&next=https%3A%2F%2Foutside.example%2F&literal=%23"
    response = upstream.request(
        method,
        f"{path}?{query}",
        content=b"synthetic-body",
        headers={"Authorization": "Bearer synthetic-token"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == f"{canonical}?{query}"
    assert observed == []
    completed = upstream.request(
        method,
        response.headers["location"],
        content=b"synthetic-body",
        headers={"Authorization": "Bearer synthetic-token"},
    )
    assert completed.status_code == 200
    assert urlsplit(str(completed.url)).scheme == "https"
    assert observed == [(method, b"synthetic-body", "Bearer synthetic-token")]
    assert completed.json() == {"query": query}
    assert completed.headers["x-request-id"]
    upstream.close()


@pytest.mark.parametrize("status", [302, 303, 307, 308])
@pytest.mark.parametrize(
    "location",
    [
        "https://publisher.example/official.pdf#page=3",
        "https://outside.example/api/source-probe/",
        "/api/other-record?version=2",
    ],
)
def test_source_and_explicit_redirects_are_not_rewritten(client, status, location):
    async def endpoint():
        return RedirectResponse(location, status_code=status)

    client.app.add_api_route("/api/source-probe", endpoint, methods=["GET"])
    response = client.get("/api/source-probe", follow_redirects=False)
    assert response.status_code == status
    assert response.headers["location"] == location


def test_canonical_redirect_does_not_trust_forwarded_origin_headers(client):
    response = client.get(
        "/api/clients",
        follow_redirects=False,
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "outside.example"},
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/api/clients/"
    assert client.get("/api/no-such-canonical-route", follow_redirects=False).status_code == 404


def test_redirect_boundary_preserves_streaming_body(client):
    async def endpoint():
        return StreamingResponse(iter([b"first", b"second"]), media_type="text/plain")

    client.app.add_api_route("/api/stream-probe", endpoint)
    response = client.get("/api/stream-probe")
    assert response.status_code == 200
    assert response.content == b"firstsecond"
