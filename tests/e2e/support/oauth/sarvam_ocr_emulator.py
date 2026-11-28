"""Offline Sarvam Document AI for local OCR & Translate journeys; never shipped.

Replaces the rendition pipeline's Sarvam client with one whose transport is an
in-process mock, so no request can leave the machine. The mock follows the
documented Parse contract (docs.sarvam.ai, checked 2026-11-27): it accepts
only PDF, PNG and JPEG uploads whose name and type agree, and answers with the
documented ``output_format=json`` archive -- ``manifest.json`` plus
``<uploaded name>/<uploaded stem>.json`` -- named after the uploaded file.
"""

import io
import json
import os
import re
import zipfile
from threading import Lock
from typing import Any

from calendar_oauth_emulator import require_test_environment

PREFIX = "/_e2e/sarvam-ocr"
DOWNLOAD_ORIGIN = "https://files.sarvam-ocr.e2e.test/"
OCR_TEXT = "OFFLINE SARVAM OCR. ORDER dated 12.03.2023. Page {page} of {name}."
_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg",
          "jpeg": "image/jpeg"}
_FILE_PART = re.compile(
    rb'name="file"; filename="([^"]+)"\r\nContent-Type: ([^\r]+)\r\n\r\n'
)


def install_sarvam_ocr_emulator(app: Any) -> None:
    require_test_environment()

    import httpx
    from fastapi import HTTPException, Request
    from sqlalchemy import select

    from caseops_api.core.automated_test_context import (
        NO_PAID_PROVIDERS_HEADER,
        NO_PAID_PROVIDERS_VALUE,
    )
    from caseops_api.core.settings import get_settings
    from caseops_api.db.models import ProviderCostProfile
    from caseops_api.db.session import get_session_factory
    from caseops_api.services import document_rendition_pipeline as pipeline
    from caseops_api.services.sarvam_document_ai import SarvamDocumentClient

    os.environ["CASEOPS_SARVAM_DOCUMENT_AI_ENABLED"] = "true"
    os.environ["CASEOPS_SARVAM_API_KEY"] = "offline-sarvam-emulator-key"
    get_settings.cache_clear()

    jobs: dict[str, dict[str, Any]] = {}
    lock = Lock()

    def _problem(status: int, code: str) -> httpx.Response:
        return httpx.Response(status, json={"title": code, "status": status, "detail": code})

    def _submit(body: bytes) -> httpx.Response:
        part = _FILE_PART.search(body)
        if part is None:
            return _problem(400, "INPUT_INVALID")
        name = part.group(1).decode()
        declared = part.group(2).decode()
        content = body[part.end():body.rfind(b"\r\n--")]
        suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if _TYPES.get(suffix) != declared:
            return _problem(400, "INPUT_TYPE_UNSUPPORTED")
        if suffix == "pdf":
            import pypdfium2 as pdfium

            pages = len(pdfium.PdfDocument(content))
        else:
            from PIL import Image

            Image.open(io.BytesIO(content)).verify()
            pages = 1
        with lock:
            job = f"offline-sarvam-{len(jobs) + 1}"
            jobs[job] = {"name": name, "pages": pages, "bytes": len(content)}
        return httpx.Response(201, json={"job_id": job, "status": "pending", "run_id": job})

    def _archive(job: str) -> bytes:
        entry = jobs[job]
        name = entry["name"]
        document = {
            "filename": name, "page_count": entry["pages"], "status": "completed",
            "partial": False, "warnings": [],
            "pages": [
                {"page_num": page, "status": "completed", "image_width": 1240,
                 "image_height": 1754, "blocks": [{
                     "block_id": f"p{page}-b1", "layout_tag": "paragraph", "reading_order": 1,
                     "text": OCR_TEXT.format(page=page, name=name), "confidence": 0.98,
                     "coordinates": {"x1": 80, "y1": 80, "x2": 1160, "y2": 240},
                     "bbox_norm": [0.0645, 0.0456, 0.9355, 0.1368],
                 }]}
                for page in range(1, entry["pages"] + 1)
            ],
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"job_id": job, "files": [name]}))
            archive.writestr(f"{name}/{name.rsplit('.', 1)[0]}.json", json.dumps(document))
        return buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(DOWNLOAD_ORIGIN):
            return httpx.Response(200, content=_archive(url.removeprefix(DOWNLOAD_ORIGIN)))
        if request.method == "POST" and url.endswith("/doc-ai/v1/job/parse"):
            return _submit(request.content)
        match = re.search(r"/doc-ai/v1/job/([^/]+)/(status|download-url)$", url)
        if match is None or match.group(1) not in jobs:
            return _problem(404, "NOT_FOUND")
        job, action = match.groups()
        if action == "status":
            pages = jobs[job]["pages"]
            return httpx.Response(200, json={
                "job_id": job, "status": "completed",
                "usage": {"pages_total": pages, "pages_processed": pages,
                          "pages_succeeded": pages, "pages_failed": 0},
            })
        return httpx.Response(200, json={"method": "GET", "url": DOWNLOAD_ORIGIN + job})

    def offline_sarvam_client() -> tuple[SarvamDocumentClient, bool]:
        return SarvamDocumentClient(
            api_key="offline-sarvam-emulator-key",
            base_url=get_settings().sarvam_api_base_url,
            timeout_seconds=10,
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        ), True

    pipeline.sarvam_client = offline_sarvam_client

    @app.post(PREFIX + "/cost-profile", include_in_schema=False)
    def offline_cost_profile(request: Request) -> dict[str, str]:
        # Readiness refuses OCR until a verified page price exists.
        require_test_environment()
        if request.headers.get(NO_PAID_PROVIDERS_HEADER) != NO_PAID_PROVIDERS_VALUE:
            raise HTTPException(403, "The offline OCR fixture requires the no-paid marker.")
        from datetime import UTC, datetime, timedelta

        with get_session_factory()() as session:
            existing = session.scalars(select(ProviderCostProfile).where(
                ProviderCostProfile.category == "ocr_page",
                ProviderCostProfile.provider == "sarvam",
                ProviderCostProfile.status == "active",
            )).first()
            if existing is None:
                session.add(ProviderCostProfile(
                    category="ocr_page", provider="sarvam", currency="INR",
                    unit_amount_minor=150, unit_label="page",
                    effective_from=datetime.now(UTC) - timedelta(days=1), status="active",
                    source="https://example.invalid/offline-sarvam-pricing",
                    cost_basis="actual", confidence_level="high",
                    evidence_ref="offline e2e OCR fixture",
                    founder_approval_status="pending", approved_at=None,
                ))
                session.commit()
        return {"provider": "sarvam", "transport": "in-process-mock"}

    @app.get(PREFIX + "/jobs", include_in_schema=False)
    def offline_jobs() -> dict[str, list[dict[str, Any]]]:
        with lock:
            return {"jobs": [{"job_id": job, **entry} for job, entry in jobs.items()]}
