"""September 10 offline fixture, served only on the isolated acceptance network."""

import os
from datetime import date, timedelta
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from caseops_api.scripts.docker_acceptance_case_provider import AcceptanceProviderHandler

HEARING_CNR = "DLHC010081232026"
HEARING_CASE_NUMBER = "8123/2026"
SECOND_HEARING_CASE_NUMBER = "8124/2026"
HEARING_FILING_NUMBER = "421/2026"
AMBIGUOUS_NUMBER = "889/2026"
AMBIGUOUS_CNRS = ("DLHC010008892026", "DLHC020008892026")


def hearing_case(number: str, *, cnr: str = HEARING_CNR) -> dict[str, object]:
    return {
        "cnr": cnr,
        "caseNumber": f"WP(C) {number}",
        "registrationNumber": number,
        "filingNumber": HEARING_FILING_NUMBER,
        "caseType": "WP_C",
        "courtCode": "DLHC01",
        "courtName": "Delhi High Court",
        "state": "Delhi",
        "district": "New Delhi",
        "petitioners": ["Local Docker Petitioner"],
        "respondents": ["Local Docker Respondent"],
        "respondentAdvocates": ["Local Docker Counsel"],
        "caseStatus": "PENDING",
        "nextHearingDate": (date.today() + timedelta(days=21)).isoformat(),
        "historyOfCaseHearings": [
            {
                "businessOnDate": (date.today() - timedelta(days=8)).isoformat(),
                "hearingDate": (date.today() - timedelta(days=2)).isoformat(),
                "purposeOfListing": "Arguments",
            },
            {
                "businessOnDate": (date.today() - timedelta(days=1)).isoformat(),
                "hearingDate": (date.today() + timedelta(days=7)).isoformat(),
                "purposeOfListing": "Arguments",
            },
        ],
    }


class HearingAcceptanceHandler(AcceptanceProviderHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/partner/search":
            number = parse_qs(parsed.query).get("caseNumbers", [""])[0]
            if number not in {
                HEARING_CASE_NUMBER,
                SECOND_HEARING_CASE_NUMBER,
                HEARING_FILING_NUMBER,
                AMBIGUOUS_NUMBER,
            }:
                super().do_GET()
                return
            if not self._authorized():
                return
            rows = [hearing_case(number)]
            if number == AMBIGUOUS_NUMBER:
                rows = [
                    dict(hearing_case(number, cnr=cnr), registrationNumber=number)
                    for cnr in AMBIGUOUS_CNRS
                ]
            self._write_json(
                HTTPStatus.OK,
                {"data": {"results": rows, "totalHits": len(rows), "hasNextPage": False}},
            )
            return
        cnr = parsed.path.removeprefix("/api/partner/case/")
        if parsed.path.startswith("/api/partner/case/") and cnr in {HEARING_CNR, *AMBIGUOUS_CNRS}:
            if not self._authorized():
                return
            self._write_json(
                HTTPStatus.OK,
                {"data": {"courtCaseData": hearing_case(HEARING_CASE_NUMBER, cnr=cnr)}},
            )
            return
        # Includes Hume's SOURCE_PATH and every older fixture. Never treat an
        # order/source path as a broad case-detail request in this subclass.
        super().do_GET()


def main() -> None:
    ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("CASEOPS_ACCEPTANCE_PROVIDER_PORT", "8080"))),
        HearingAcceptanceHandler,
    ).serve_forever()


if __name__ == "__main__":
    main()
