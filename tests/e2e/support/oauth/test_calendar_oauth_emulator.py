from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from calendar_oauth_emulator import (
    CALLBACK,
    CLIENT_ID,
    CLIENT_SECRET,
    MODE,
    REQUIRED_SCOPES,
    CalendarOAuthEmulator,
    loopback_origin,
    redirected_google_url,
    require_test_environment,
)


class EmulatorIsolationTests(unittest.TestCase):
    def environment(self, **changes: str) -> dict[str, str]:
        return {
            "CASEOPS_ENV": "e2e",
            "CASEOPS_E2E_OAUTH_EMULATOR": MODE,
            "CASEOPS_PUBLIC_APP_URL": "http://127.0.0.1:3100",
            "CASEOPS_DATABASE_URL": "postgresql+psycopg://caseops:caseops@postgres:5432/caseops",
            **changes,
        }

    def test_explicit_local_and_docker_acceptance_only(self) -> None:
        require_test_environment(self.environment())
        require_test_environment(
            self.environment(CASEOPS_DATABASE_URL="sqlite+pysqlite:///C:/tests/e2e.db")
        )
        for changes in (
            {"CASEOPS_ENV": "production"},
            {"CASEOPS_ENV": "local"},
            {"CASEOPS_E2E_OAUTH_EMULATOR": ""},
            {"K_SERVICE": "caseops-api"},
            {"K_REVISION": "production-revision"},
            {"CLOUD_RUN_JOB": "release-job"},
            {"GOOGLE_CLOUD_PROJECT": "production-project"},
            {
                "CASEOPS_DATABASE_URL": "postgresql+psycopg://user:pass@production-db:5432/caseops"
            },
            {"CASEOPS_PUBLIC_APP_URL": "https://caseops.ai"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises((RuntimeError, ValueError)),
            ):
                require_test_environment(self.environment(**changes))

    def test_redirects_cannot_leave_loopback(self) -> None:
        for value in (
            "https://caseops.ai:443",
            "http://127.0.0.1.evil.test:8000",
            "http://user:pass@127.0.0.1:8000",
            "http://localhost",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                loopback_origin(value)

    def test_google_transport_cannot_fall_through(self) -> None:
        local = "http://127.0.0.1:19001"
        self.assertEqual(
            redirected_google_url("https://oauth2.googleapis.com/token", local),
            local + "/token",
        )
        self.assertEqual(
            redirected_google_url(
                "https://www.googleapis.com/oauth2/v3/userinfo", local
            ),
            local + "/userinfo",
        )
        self.assertIsNone(
            redirected_google_url("http://acceptance-case-provider:8080", local)
        )
        for url in (
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            "https://accounts.google.com/o/oauth2/v2/auth",
            "https://oauth2.googleapis.com/token?unexpected=1",
        ):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                redirected_google_url(url, local)


class EmulatorProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.emulator = CalendarOAuthEmulator()

    def authorize(self, scopes: str | None = None):
        return self.emulator.authorize(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": "http://127.0.0.1:8000" + CALLBACK,
                "response_type": "code",
                "state": "server-signed-state-fixture",
                "scope": scopes
                if scopes is not None
                else " ".join(sorted(REQUIRED_SCOPES)),
            }
        )

    def token(self, attempt):
        return self.emulator.token(
            {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": attempt.code,
                "grant_type": "authorization_code",
                "redirect_uri": attempt.redirect_uri,
            }
        )

    def test_missing_identity_scopes_reproduces_original_401_after_token_success(
        self,
    ) -> None:
        attempt = self.authorize("https://www.googleapis.com/auth/calendar.events")
        self.emulator.consent(attempt.identity, "success")
        status, token = self.token(attempt)
        self.assertEqual(status, 200)
        self.assertEqual(
            self.emulator.userinfo("Bearer " + str(token["access_token"]))[0], 401
        )
        self.assertEqual(self.emulator.evidence(attempt.identity)["token_calls"], 1)

    def test_successful_code_is_single_use(self) -> None:
        attempt = self.authorize()
        self.emulator.consent(attempt.identity, "success")
        status, token = self.token(attempt)
        self.assertEqual(status, 200)
        self.assertEqual(
            self.emulator.userinfo("Bearer " + str(token["access_token"]))[0], 200
        )
        self.assertEqual(self.token(attempt), (400, {"error": "invalid_grant"}))

    def test_declined_consent_cannot_exchange_a_code(self) -> None:
        attempt = self.authorize()
        callback = self.emulator.consent(attempt.identity, "decline")
        self.assertEqual(
            parse_qs(urlsplit(callback).query),
            {"error": ["access_denied"], "state": [attempt.state]},
        )
        self.assertEqual(self.emulator.evidence(attempt.identity)["token_calls"], 0)
        self.assertEqual(self.token(attempt), (400, {"error": "invalid_grant"}))
        with self.assertRaises(ValueError):
            self.emulator.consent(attempt.identity, "success")

    def test_explicit_identity_rejection_with_correct_scopes(self) -> None:
        attempt = self.authorize()
        self.emulator.consent(attempt.identity, "identity_failure")
        _, token = self.token(attempt)
        self.assertEqual(
            self.emulator.userinfo("Bearer " + str(token["access_token"]))[0], 401
        )

    def test_real_loopback_http_exchange(self) -> None:
        origin = self.emulator.start()
        self.addCleanup(self.emulator.stop)
        attempt = self.authorize()
        self.emulator.consent(attempt.identity, "success")
        body = urlencode(
            {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": attempt.code,
                "grant_type": "authorization_code",
                "redirect_uri": attempt.redirect_uri,
            }
        ).encode()
        with urlopen(Request(origin + "/token", data=body), timeout=2) as response:
            token = json.load(response)
        with urlopen(
            Request(
                origin + "/userinfo",
                headers={"Authorization": "Bearer " + token["access_token"]},
            ),
            timeout=2,
        ) as response:
            self.assertEqual(
                json.load(response)["email"], "calendar-emulator@example.test"
            )


if __name__ == "__main__":
    unittest.main()
