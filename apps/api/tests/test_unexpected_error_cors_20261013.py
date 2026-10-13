"""An unexpected server error must not masquerade as browser connectivity loss."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("origin", ["http://localhost:3000", "https://untrusted.example", None])
def test_unexpected_error_preserves_native_cors_policy_and_safe_problem(client, origin):
    @client.app.get("/api/_isolated-unexpected-error")
    def injected_failure():
        raise RuntimeError("private synthetic source diagnostic must not escape")

    headers = {"X-Request-ID": "isolated-unexpected-cors-20261013"}
    if origin:
        headers["Origin"] = origin
    with TestClient(client.app, raise_server_exceptions=False) as transport:
        response = transport.get("/api/_isolated-unexpected-error", headers=headers)
        assert response.status_code == 500
        assert response.json()["detail"] == "An unexpected error occurred."
        assert "private synthetic source diagnostic" not in response.text
        assert response.headers["X-Request-ID"] == response.json()["request_id"]
        if origin == "http://localhost:3000":
            assert response.headers["access-control-allow-origin"] == origin
            assert "X-Request-ID" in response.headers["access-control-expose-headers"]
            assert "Origin" in response.headers["Vary"]
        else:
            assert "access-control-allow-origin" not in response.headers
        assert transport.get("/api/health").status_code == 200
