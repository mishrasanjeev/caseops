from __future__ import annotations

import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse


def _case_payload(*, case_number: str, cnr: str) -> dict[str, object]:
    next_hearing = (date.today() + timedelta(days=21)).isoformat()
    number = re.fullmatch(r"\s*(.*?)\s*[/ -]?\s*(\d+/\d{4})\s*", case_number)
    case_type = number.group(1).strip(" /-") if number else ""
    return {
        "cnr": cnr,
        "caseNumber": case_number,
        "registrationNumber": number.group(2) if number else case_number,
        "caseType": "WP_C" if case_type in {"", "WP(C)"} else case_type,
        "courtCode": "DLHC",
        "courtName": "Delhi High Court",
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
        from caseops_api.scripts.docker_acceptance_summary import SOURCE_PATH, SOURCE_TEXT

        if parsed.path == SOURCE_PATH:
            body = SOURCE_TEXT.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="summary-20260910.md"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/partner/search":
            params = parse_qs(parsed.query)
            case_number = params.get("caseNumbers", [""])[0].strip()
            general_query = params.get("query", [""])[0].strip()
            search_text = case_number or general_query
            if not search_text:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"detail": "A case-number or general query is required."},
                )
                return
            self._write_json(
                HTTPStatus.OK,
                {
                    "data": {
                        "results": [
                            _case_payload(
                                case_number=search_text,
                                cnr="DLHC010091232026",
                            )
                        ],
                        "totalHits": 1,
                        "page": 1,
                        "pageSize": 20,
                        "totalPages": 1,
                        "hasNextPage": False,
                        "hasPreviousPage": False,
                        "enumDescriptions": {
                            "enumLookup": {
                                "caseStatus": {"PENDING": "Pending"},
                                "courtCode": {"DLHC": "Delhi High Court"},
                            }
                        },
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
        if parsed.path not in {
            "/api/partner/case/bulk-refresh",
            "/api/partner/case/bulk-refresh-status",
        }:
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
        if parsed.path.endswith("/bulk-refresh-status"):
            self._write_json(
                HTTPStatus.OK,
                {
                    "data": {
                        "results": [
                            {
                                "cnr": cnr,
                                "status": "COMPLETED",
                                "requestedAt": datetime.now(UTC).isoformat(),
                                "completedAt": datetime.now(UTC).isoformat(),
                                "failureReason": None,
                                "creditsCharged": 0,
                                "refunded": False,
                            }
                            for cnr in cnrs
                        ]
                    }
                },
            )
            return
        self._write_json(HTTPStatus.OK, {"data": {"refreshed": cnrs, "queued": [], "invalid": []}})

    def log_message(self, format: str, *args: object) -> None:
        # Keep Docker acceptance logs deterministic and free of request data.
        return


def main() -> None:
    port = int(os.environ.get("CASEOPS_ACCEPTANCE_PROVIDER_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AcceptanceProviderHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
