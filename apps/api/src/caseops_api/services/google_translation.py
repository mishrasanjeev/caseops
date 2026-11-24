"""Google Cloud Translation Advanced (v3) client pinned to the Translation LLM.

REST contract (Cloud Translation docs, checked 2026-11-23):
``POST {base}/v3/projects/{project}/locations/{location}:translateText`` with
``contents``, ``mimeType``, ``sourceLanguageCode``, ``targetLanguageCode`` and
``model = projects/{project}/locations/{location}/models/general/translation-llm``.
v3 accepts OAuth bearer tokens only (no API keys); the runtime service account
needs ``roles/cloudtranslate.user``. Translation LLM caps a request at 30,000
characters; callers send far smaller, paragraph-aligned chunks.

The model is never substituted. If Google answers with another model, or the
model is unavailable in the configured region, the call fails and the user can
retry once the configuration is fixed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

PROVIDER_KEY = "google-translation"
PROVIDER_LABEL = "Google Cloud Translation (Translation LLM)"
MODEL_ID = "general/translation-llm"
MAX_REQUEST_CHARACTERS = 30_000
MAX_CONTENT_ITEMS = 1024
_SCOPES = ("https://www.googleapis.com/auth/cloud-translation",)


class GoogleTranslationError(Exception):
    def __init__(
        self, code: str, message: str, *, retryable: bool, charge_possible: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.charge_possible = charge_possible


@dataclass(frozen=True, slots=True)
class TranslationBatch:
    texts: list[str]
    model: str


def model_path(project_id: str, location: str) -> str:
    return f"projects/{project_id}/locations/{location}/models/{MODEL_ID}"


def default_token_provider() -> Callable[[], str]:
    """Application Default Credentials (Cloud Run workload identity in prod)."""

    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=list(_SCOPES))

    def token() -> str:
        if not credentials.valid:
            credentials.refresh(Request())
        if not credentials.token:
            raise GoogleTranslationError(
                "auth", "Google credentials returned no access token.", retryable=False,
            )
        return str(credentials.token)

    return token


def _error_from_response(response: httpx.Response) -> GoogleTranslationError:
    message = ""
    status_name = ""
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or "")
            status_name = str(error.get("status") or "")
    except ValueError:
        pass
    lowered = message.lower()
    code = response.status_code
    if code == 429 or "rate limit" in lowered or "quota" in lowered or (
        status_name == "RESOURCE_EXHAUSTED"
    ):
        return GoogleTranslationError(
            "rate_limited", "Google Translation quota or rate limit reached; retry shortly.",
            retryable=True,
        )
    if code in {401, 403}:
        return GoogleTranslationError(
            "auth",
            "Google Translation rejected the service credentials or the API is not enabled.",
            retryable=False,
        )
    if code == 400 and "model" in lowered:
        return GoogleTranslationError(
            "model_unavailable",
            "The Translation LLM model is not available for this project or region.",
            retryable=False,
        )
    if code == 400 and "language" in lowered:
        return GoogleTranslationError(
            "unsupported_language",
            "Google Translation LLM does not support this language pair.",
            retryable=False,
        )
    if code == 400:
        return GoogleTranslationError(
            "invalid_request", "Google Translation rejected the request.", retryable=False,
        )
    if code >= 500:
        return GoogleTranslationError(
            "unavailable", "Google Translation is temporarily unavailable.",
            retryable=True, charge_possible=True,
        )
    return GoogleTranslationError(
        "provider_error", "Google Translation returned an unexpected error.", retryable=False,
    )


class GoogleTranslationClient:
    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        base_url: str,
        timeout_seconds: float,
        http: httpx.Client | None = None,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._base_url = base_url.rstrip("/")
        self._own_http = http is None
        self._http = http or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
        self._token_provider = token_provider

    @property
    def model(self) -> str:
        return model_path(self._project_id, self._location)

    def close(self) -> None:
        if self._own_http:
            self._http.close()

    def _token(self) -> str:
        if self._token_provider is None:
            try:
                self._token_provider = default_token_provider()
            except GoogleTranslationError:
                raise
            except Exception as exc:  # google.auth raises several unrelated types
                raise GoogleTranslationError(
                    "auth", "Google service credentials are not available.", retryable=False,
                ) from exc
        try:
            return self._token_provider()
        except GoogleTranslationError:
            raise
        except Exception as exc:
            raise GoogleTranslationError(
                "auth", "Google service credentials could not be refreshed.", retryable=True,
            ) from exc

    def translate(self, contents: list[str], *, source: str, target: str) -> TranslationBatch:
        if not contents or len(contents) > MAX_CONTENT_ITEMS:
            raise ValueError("Translation batches need 1-1024 items.")
        if sum(len(item) for item in contents) > MAX_REQUEST_CHARACTERS:
            raise ValueError("Translation batch exceeds the Translation LLM character limit.")
        body: dict[str, Any] = {
            "contents": contents,
            "mimeType": "text/plain",
            "sourceLanguageCode": source,
            "targetLanguageCode": target,
            "model": self.model,
        }
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "x-goog-user-project": self._project_id,
            "Content-Type": "application/json; charset=utf-8",
        }
        url = (
            f"{self._base_url}/v3/projects/{self._project_id}"
            f"/locations/{self._location}:translateText"
        )
        try:
            response = self._http.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise GoogleTranslationError(
                "timeout", "Google Translation did not answer in time.",
                retryable=True, charge_possible=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise GoogleTranslationError(
                "network", "Google Translation could not be reached.",
                retryable=True, charge_possible=True,
            ) from exc
        if response.status_code >= 400:
            raise _error_from_response(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleTranslationError(
                "bad_response", "Google Translation returned an unreadable response.",
                retryable=True, charge_possible=True,
            ) from exc
        translations = payload.get("translations") if isinstance(payload, dict) else None
        if not isinstance(translations, list) or len(translations) != len(contents):
            raise GoogleTranslationError(
                "bad_response", "Google Translation returned an incomplete response.",
                retryable=True, charge_possible=True,
            )
        texts: list[str] = []
        for item in translations:
            if not isinstance(item, dict) or not isinstance(item.get("translatedText"), str):
                raise GoogleTranslationError(
                    "bad_response", "Google Translation returned an incomplete response.",
                    retryable=True, charge_possible=True,
                )
            reported = item.get("model")
            # Never accept a silent fallback to NMT or another model.
            if isinstance(reported, str) and reported and not reported.endswith(MODEL_ID):
                raise GoogleTranslationError(
                    "model_mismatch",
                    "Google Translation answered with a different model; the result was "
                    "discarded.",
                    retryable=False, charge_possible=True,
                )
            texts.append(item["translatedText"])
        return TranslationBatch(texts=texts, model=self.model)


__all__ = [
    "MAX_REQUEST_CHARACTERS",
    "MODEL_ID",
    "PROVIDER_KEY",
    "PROVIDER_LABEL",
    "GoogleTranslationClient",
    "GoogleTranslationError",
    "TranslationBatch",
    "model_path",
]
