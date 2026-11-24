"""Sarvam Document AI (Parse API) client for page-wise OCR.

Flow, per the Sarvam Document Intelligence docs (checked 2026-11-23):

* ``POST /doc-ai/v1/job/parse`` (multipart ``file``, ``language``,
  ``output_format``) creates and starts an asynchronous job -> ``job_id``.
* ``GET /doc-ai/v1/job/{job_id}/status`` -> ``status`` in
  pending|running|completed|partially_completed|failed|rejected plus
  ``usage.pages_*`` counters.
* ``GET /doc-ai/v1/job/{job_id}/download-url`` -> a short-lived URL to a ZIP
  holding the parsed output and one ``metadata/page_NNN.json`` per page.

A job accepts at most 20 PDF pages, so callers split documents and restore the
original page numbers themselves. The per-page JSON schema is not published;
``parse_output_archive`` reads it defensively and never invents text: a page
it cannot map is reported as missing, not filled.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

import httpx

PROVIDER_KEY = "sarvam"
PROVIDER_LABEL = "Sarvam Document AI"
MODEL_LABEL = "sarvam-document-ai/parse"
MAX_PAGES_PER_JOB = 20
TERMINAL_STATUSES = frozenset({"completed", "partially_completed", "failed", "rejected"})
# CaseOps language code -> Sarvam BCP-47 code.
LANGUAGE_CODES = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}
MAX_OUTPUT_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_OUTPUT_MEMBER_BYTES = 50 * 1024 * 1024
MAX_OUTPUT_TOTAL_BYTES = 400 * 1024 * 1024
LOW_CONFIDENCE = 0.6
_PAGE_FILE = re.compile(r"(?:^|/)page[_-]?0*(\d{1,4})\.json$", re.IGNORECASE)


class SarvamError(Exception):
    """A classified provider failure with safe, user-presentable copy."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        charge_possible: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        # True when the provider may have accepted (and billed) the request.
        self.charge_possible = charge_possible


@dataclass(frozen=True, slots=True)
class SarvamJobStatus:
    job_id: str
    status: str
    pages_total: int | None
    pages_succeeded: int | None
    pages_failed: int | None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass(slots=True)
class ParsedPage:
    text: str
    blocks: list[dict[str, Any]] = field(default_factory=list)
    min_confidence: float | None = None
    low_confidence_blocks: int = 0


_HTTP_ERRORS: dict[int, tuple[str, str, bool]] = {
    400: ("invalid_request", "Sarvam rejected the request as invalid.", False),
    401: ("auth", "Sarvam rejected the API credentials.", False),
    402: ("billing", "Sarvam billing or entitlement blocked the request.", False),
    403: ("auth", "Sarvam rejected the API credentials or entitlement.", False),
    404: ("not_found", "Sarvam could not find the OCR job.", False),
    409: ("not_ready", "The Sarvam OCR job has not finished yet.", True),
    413: ("file_too_large", "The file is larger than Sarvam accepts.", False),
    422: ("invalid_file", "Sarvam could not read the file; it may be corrupt.", False),
    429: ("rate_limited", "Sarvam rate limit reached; retry shortly.", True),
    503: ("unavailable", "Sarvam is temporarily unavailable.", True),
}


def _raise_for_status(response: httpx.Response, *, submit: bool = False) -> None:
    if response.status_code < 400:
        return
    code, message, retryable = _HTTP_ERRORS.get(
        response.status_code,
        (
            ("unavailable", "Sarvam returned a server error.", True)
            if response.status_code >= 500
            else ("provider_error", "Sarvam returned an unexpected error.", False)
        ),
    )
    # A 5xx on submit leaves acceptance (and billing) unknown.
    raise SarvamError(
        code,
        message,
        retryable=retryable,
        charge_possible=submit and response.status_code >= 500,
    )


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SarvamError(
            "bad_response", "Sarvam returned an unreadable response.", retryable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise SarvamError("bad_response", "Sarvam returned an unexpected response.", retryable=True)
    return payload


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class SarvamDocumentClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        http: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"api-subscription-key": api_key, "Accept": "application/json"}
        self._own_http = http is None
        self._http = http or httpx.Client(timeout=timeout_seconds, follow_redirects=False)

    def close(self) -> None:
        if self._own_http:
            self._http.close()

    def submit_parse(
        self, *, filename: str, content: bytes, content_type: str, language: str,
    ) -> str:
        if language not in LANGUAGE_CODES:
            raise SarvamError(
                "unsupported_language", "Sarvam OCR does not support this language.",
                retryable=False,
            )
        try:
            response = self._http.post(
                f"{self._base_url}/doc-ai/v1/job/parse",
                headers=self._headers,
                files={"file": (filename, content, content_type)},
                data={"language": LANGUAGE_CODES[language], "output_format": "json"},
            )
        except httpx.TimeoutException as exc:
            raise SarvamError(
                "timeout", "Sarvam did not answer in time.", retryable=True, charge_possible=True,
            ) from exc
        except httpx.HTTPError as exc:
            # Connection errors before a response may still have reached Sarvam.
            raise SarvamError(
                "network", "Sarvam could not be reached.", retryable=True, charge_possible=True,
            ) from exc
        _raise_for_status(response, submit=True)
        job_id = _json(response).get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise SarvamError(
                "bad_response", "Sarvam accepted the file but returned no job id.",
                retryable=False, charge_possible=True,
            )
        return job_id.strip()

    def get_status(self, job_id: str) -> SarvamJobStatus:
        try:
            response = self._http.get(
                f"{self._base_url}/doc-ai/v1/job/{job_id}/status", headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise SarvamError("network", "Sarvam status check failed.", retryable=True) from exc
        _raise_for_status(response)
        payload = _json(response)
        state = payload.get("status")
        if not isinstance(state, str):
            raise SarvamError("bad_response", "Sarvam returned no job status.", retryable=True)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return SarvamJobStatus(
            job_id=job_id,
            status=state.strip().lower(),
            pages_total=_optional_int(usage.get("pages_total")),
            pages_succeeded=_optional_int(usage.get("pages_succeeded")),
            pages_failed=_optional_int(usage.get("pages_failed")),
        )

    def download_output(self, job_id: str) -> bytes:
        try:
            response = self._http.get(
                f"{self._base_url}/doc-ai/v1/job/{job_id}/download-url", headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise SarvamError("network", "Sarvam output lookup failed.", retryable=True) from exc
        _raise_for_status(response)
        url = _json(response).get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise SarvamError("bad_response", "Sarvam returned no output link.", retryable=True)
        # The signed link carries its own authorization; never send our key.
        chunks: list[bytes] = []
        size = 0
        try:
            with self._http.stream("GET", url) as download:
                if download.status_code >= 400:
                    raise SarvamError(
                        "download_failed", "The Sarvam output could not be downloaded.",
                        retryable=True,
                    )
                for chunk in download.iter_bytes():
                    size += len(chunk)
                    if size > MAX_OUTPUT_ARCHIVE_BYTES:
                        raise SarvamError(
                            "output_too_large", "The Sarvam output exceeded the size limit.",
                            retryable=False,
                        )
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise SarvamError(
                "download_failed", "The Sarvam output could not be downloaded.", retryable=True,
            ) from exc
        return b"".join(chunks)


def _block_text(block: dict[str, Any]) -> str:
    for key in ("text", "content", "markdown", "html"):
        value = block.get(key)
        if isinstance(value, str):
            return value
    return ""


def _block_confidence(block: dict[str, Any]) -> float | None:
    for key in ("confidence", "score", "ocr_confidence"):
        value = block.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            number = float(value)
            # Some providers report 0-100; normalise to 0-1.
            return number / 100.0 if number > 1.0 else number
    return None


def _blocks(payload: object) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("blocks", "elements", "layout", "items", "content"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return None


def _page_from_payload(payload: object) -> ParsedPage | None:
    blocks = _blocks(payload)
    if blocks:
        kept: list[dict[str, Any]] = []
        texts: list[str] = []
        confidences: list[float] = []
        low = 0
        for block in blocks:
            text = _block_text(block).strip()
            if not text:
                continue
            tag = block.get("tag") or block.get("type") or block.get("label") or "paragraph"
            confidence = _block_confidence(block)
            if confidence is not None:
                confidences.append(confidence)
                if confidence < LOW_CONFIDENCE:
                    low += 1
            bbox = block.get("bbox") or block.get("bounding_box") or block.get("coordinates")
            kept.append({
                "tag": str(tag)[:40],
                "text": text,
                "confidence": confidence,
                "bbox": bbox if isinstance(bbox, list | dict) else None,
            })
            texts.append(text)
        return ParsedPage(
            text="\n\n".join(texts),
            blocks=kept,
            min_confidence=min(confidences) if confidences else None,
            low_confidence_blocks=low,
        )
    if isinstance(payload, dict):
        for key in ("markdown", "text", "content"):
            value = payload.get(key)
            if isinstance(value, str):
                return ParsedPage(text=value.strip())
    return None


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, budget: list[int]) -> bytes:
    if info.file_size > MAX_OUTPUT_MEMBER_BYTES:
        raise SarvamError("output_too_large", "A Sarvam output file is too large.", retryable=False)
    budget[0] += info.file_size
    if budget[0] > MAX_OUTPUT_TOTAL_BYTES:
        raise SarvamError("output_too_large", "The Sarvam output is too large.", retryable=False)
    with archive.open(info) as handle:
        data = handle.read(MAX_OUTPUT_MEMBER_BYTES + 1)
    if len(data) > MAX_OUTPUT_MEMBER_BYTES:
        raise SarvamError("output_too_large", "A Sarvam output file is too large.", retryable=False)
    return data


def parse_output_archive(archive_bytes: bytes, *, page_count: int) -> dict[int, ParsedPage]:
    """Return parsed pages keyed by 1-based position within the submitted batch.

    Pages missing from the result were not returned by the provider; callers
    must treat them as failed pages rather than empty ones.
    """

    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise SarvamError("bad_output", "The Sarvam output archive is unreadable.",
                          retryable=True) from exc
    budget = [0]
    pages: dict[int, ParsedPage] = {}
    main_json: list[zipfile.ZipInfo] = []
    with archive:
        for info in archive.infolist():
            if info.is_dir() or ".." in info.filename.replace("\\", "/").split("/"):
                continue
            match = _PAGE_FILE.search(info.filename.replace("\\", "/"))
            if match:
                number = int(match.group(1))
                if not 1 <= number <= page_count:
                    continue
                try:
                    payload = json.loads(_read_member(archive, info, budget))
                except (ValueError, UnicodeDecodeError):
                    continue
                parsed = _page_from_payload(payload)
                if parsed is not None:
                    pages[number] = parsed
            elif info.filename.lower().endswith(".json") and not info.filename.lower().endswith(
                "manifest.json"
            ):
                main_json.append(info)
        if len(pages) < page_count:
            for info in main_json:
                try:
                    payload = json.loads(_read_member(archive, info, budget))
                except (ValueError, UnicodeDecodeError):
                    continue
                page_list = payload.get("pages") if isinstance(payload, dict) else None
                if isinstance(page_list, list):
                    for index, item in enumerate(page_list, start=1):
                        number = index
                        if isinstance(item, dict):
                            for key in ("page_number", "page", "page_num"):
                                if isinstance(item.get(key), int):
                                    number = int(item[key])
                                    break
                        if 1 <= number <= page_count and number not in pages:
                            parsed = _page_from_payload(item)
                            if parsed is not None:
                                pages[number] = parsed
                elif page_count == 1 and 1 not in pages:
                    # A single submitted page can only map to page 1.
                    parsed = _page_from_payload(payload)
                    if parsed is not None:
                        pages[1] = parsed
    return pages


__all__ = [
    "LANGUAGE_CODES",
    "MAX_PAGES_PER_JOB",
    "MODEL_LABEL",
    "PROVIDER_KEY",
    "PROVIDER_LABEL",
    "ParsedPage",
    "SarvamDocumentClient",
    "SarvamError",
    "SarvamJobStatus",
    "parse_output_archive",
]
