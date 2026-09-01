from __future__ import annotations

import json
import os
from datetime import date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse


def _case_payload(*, case_number: str, cnr: str) -> dict[str, object]:
    next_hearing = (date.today() + timedelta(days=21)).isoformat()
    return {
        "cnr": cnr,
        "caseNumber": case_number,
        "cnrCourtCode": "DLHC",
        "petitioners": ["Local Docker Petitioner"],
        "respondents": ["Local Docker Respondent"],
        "caseStatus": "PENDING",
        "stage": "Arguments",
        "nextHearingDate": f"{next_hearing}T00:00:00Z",
    }


class AcceptanceProviderHandler(BaseHTTPRequestHandler):
    server_version = "CaseOpsDockerAcceptanceProvider/1.0"

    def _write_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = os.environ.get(
            "CASEOPS_ECOURTSINDIA_API_TOKEN",
            "docker-acceptance-provider-token",
        )
        if self.headers.get("Authorization") == f"Bearer {expected}":
            return True
        self._write_json(HTTPStatus.UNAUTHORIZED, {"detail": "Unauthorized"})
        return False

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        if not self._authorized():
            return
        if parsed.path == "/api/partner/search":
            query = parse_qs(parsed.query).get("query", [""])[0].strip()
            if not query:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"detail": "A case-number query is required."},
                )
                return
            self._write_json(
                HTTPStatus.OK,
                {
                    "data": {
                        "results": [
                            _case_payload(
                                case_number=query,
                                cnr="DLHC010091232026",
                            )
                        ],
                        "descriptions": {
                            "enumLookup": {
                                "caseStatus": {"PENDING": "Pending"},
                                "courtCode": {"DLHC": "Delhi High Court"},
                            }
                        },
                    }
                },
            )
            return
        prefix = "/api/partner/case/"
        if parsed.path.startswith(prefix):
            cnr = unquote(parsed.path.removeprefix(prefix)).strip()
            if not cnr or "/" in cnr:
                self._write_json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
                return
            self._write_json(
                HTTPStatus.OK,
                {
                    "data": {
                        "courtCaseData": _case_payload(
                            case_number="WP(C) 9123/2026",
                            cnr=cnr,
                        ),
                        "descriptions": {
                            "enumLookup": {
                                "caseStatus": {"PENDING": "Pending"},
                                "courtCode": {"DLHC": "Delhi High Court"},
                            }
                        },
                    }
                },
            )
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        parsed = urlparse(self.path)
        if not self._authorized():
            return
        if parsed.path != "/api/partner/case/bulk-refresh":
            self._write_json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"detail": "Invalid JSON"})
            return
        cnrs = payload.get("cnrs") if isinstance(payload, dict) else None
        if not isinstance(cnrs, list):
            self._write_json(HTTPStatus.BAD_REQUEST, {"detail": "cnrs is required"})
            return
        self._write_json(HTTPStatus.OK, {"data": {"accepted": len(cnrs)}})

    def log_message(self, format: str, *args: object) -> None:
        # Keep Docker acceptance logs deterministic and free of request data.
        return


def main() -> None:
    port = int(os.environ.get("CASEOPS_ACCEPTANCE_PROVIDER_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AcceptanceProviderHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
