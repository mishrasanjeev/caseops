"""Authenticated, local-only fixtures for the real Drive review/import routes."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from calendar_oauth_emulator import require_test_environment

PREFIX = "/_e2e/drive-import"
CLIENT_ID = "caseops-drive-browser-emulator"
CLIENT_SECRET = "offline-drive-browser-fixture-secret"
TENANT_PREFIX = "drive-browser-"


@dataclass
class FixtureFile:
    file_id: str
    access_token: str
    filename: str
    content: bytes
    scenario: str = "success"
    fetch_calls: int = 0

    @property
    def modified_time(self) -> datetime:
        return datetime(2026, 10, 8, tzinfo=UTC)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


class DriveImportEmulator:
    configured = True
    unavailable_reason = None

    def __init__(self) -> None:
        self.files: dict[str, FixtureFile] = {}
        self.lock = Lock()

    def register(self, scenario: str = "success") -> FixtureFile:
        if scenario not in {"success", "reauthorization_required"}:
            raise ValueError("Unknown offline Drive scenario.")
        identity = uuid4().hex
        fixture = FixtureFile(
            file_id="offline-drive-file-" + identity,
            access_token="offline-drive-access-" + identity,
            filename="drive-evidence-" + identity[:12] + ".txt",
            content=("CaseOps reviewed Drive evidence\nFixture: " + identity + "\n").encode(),
            scenario=scenario,
        )
        with self.lock:
            if len(self.files) >= 128:
                raise RuntimeError("Offline Drive fixture inventory limit reached.")
            self.files[fixture.file_id] = fixture
        return fixture

    def fetch_file(
        self, *, token_payload: dict[str, Any], file_id: str, expected: Any,
        expected_version: str, max_size_bytes: int, deadline: float,
    ) -> bytes:
        with self.lock:
            fixture = self.files.get(file_id)
            if fixture is None or token_payload.get("access_token") != fixture.access_token:
                raise RuntimeError("Only the matching offline Drive fixture can be fetched.")
            modified = expected.modified_time
            if modified is not None and modified.tzinfo is None:
                modified = modified.replace(tzinfo=UTC)
            if (
                expected.provider_file_id != fixture.file_id or expected.name != fixture.filename
                or expected.mime_type != "text/plain" or expected.size_bytes != len(fixture.content)
                or modified != fixture.modified_time
                or expected_version != fixture.modified_time.isoformat()
                or max_size_bytes < len(fixture.content) or deadline <= monotonic()
            ):
                raise RuntimeError("Offline Drive source identity or download bounds changed.")
            fixture.fetch_calls += 1
            if fixture.scenario == "reauthorization_required":
                from caseops_api.services.drive_sync import GoogleDriveProviderError

                raise GoogleDriveProviderError("Offline Drive consent was revoked.", status_code=401)
            return fixture.content

    def evidence(self, file_id: str) -> dict[str, object]:
        with self.lock:
            fixture = self.files[file_id]
            return {"fetch_calls": fixture.fetch_calls, "sha256": fixture.sha256}

    def authorization_url(self, *, state: str) -> str:
        raise RuntimeError("The Drive import fixture cannot authorize Google accounts.")

    def exchange_code(self, *, code: str) -> dict[str, Any]:
        raise RuntimeError("The Drive import fixture cannot exchange Google credentials.")

    def list_files(self, *, token_payload: dict[str, Any], limit: int) -> list[Any]:
        raise RuntimeError("The Drive import fixture cannot browse Google accounts.")


def install_drive_import_emulator(app: Any) -> None:
    # Validate before importing application code, mounting routes or overriding providers.
    require_test_environment()

    from fastapi import APIRouter, Depends, HTTPException, Request
    from pydantic import BaseModel, ConfigDict, Field
    from sqlalchemy import func, select

    from caseops_api.api.dependencies import DbSession, require_capability
    from caseops_api.core.automated_test_context import (
        NO_PAID_PROVIDERS_HEADER,
        NO_PAID_PROVIDERS_VALUE,
    )
    from caseops_api.db.models import (
        AuditEvent,
        DocumentProcessingJob,
        DriveFileCandidate,
        DriveSyncControl,
        Matter,
        MatterAttachment,
        UserDriveConnection,
    )
    from caseops_api.services.calendar_sync import _encrypt_token_payload
    from caseops_api.services.drive_sync import (
        GOOGLE_DRIVE_SCOPES,
        set_google_drive_provider_for_tests,
    )
    from caseops_api.services.google_workspace import google_workspace_oauth_config
    from caseops_api.services.session_context import SessionContext

    class FixtureRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        matter_id: str = Field(min_length=36, max_length=36)
        scenario: Literal["success", "reauthorization_required"] = "success"

    def require_no_paid_marker(request: Request) -> None:
        if request.headers.get(NO_PAID_PROVIDERS_HEADER) != NO_PAID_PROVIDERS_VALUE:
            raise HTTPException(403, "The offline Drive fixture requires the no-paid-provider marker.")

    emulator = DriveImportEmulator()
    router = APIRouter(
        prefix=PREFIX, include_in_schema=False, dependencies=[Depends(require_no_paid_marker)],
    )
    owner_dependency = Depends(require_capability("documents:upload"))

    def require_fixture_owner(context: SessionContext) -> None:
        if context.membership.role != "owner" or not context.company.slug.startswith(TENANT_PREFIX):
            raise HTTPException(403, "Only a fresh offline Drive fixture owner is allowed.")

    @router.post("/fixtures")
    def seed_fixture(
        payload: FixtureRequest, session: DbSession,
        context: SessionContext = owner_dependency,
    ) -> dict[str, object]:
        require_fixture_owner(context)
        config = google_workspace_oauth_config(session, context=context, connector="drive")
        if not config.configured or config.client_id != CLIENT_ID or config.client_secret != CLIENT_SECRET:
            raise HTTPException(409, "Explicit offline Drive tenant configuration is required.")
        matter = session.get(Matter, payload.matter_id)
        if matter is None or matter.company_id != context.company.id:
            raise HTTPException(404, "Fixture Matter not found.")
        if not matter.is_active or matter.status == "disposed":
            raise HTTPException(409, "Fixture Matter must be operational.")
        for model in (UserDriveConnection, DriveFileCandidate):
            if session.scalar(select(model.id).where(model.company_id == context.company.id).limit(1)):
                raise HTTPException(409, "Offline Drive fixtures cannot replace retained rows.")
        control = session.scalar(select(DriveSyncControl).where(
            DriveSyncControl.company_id == context.company.id,
            DriveSyncControl.provider == "google_drive",
        ))
        if control is None or control.mode != "review_import" or control.auto_import_enabled:
            raise HTTPException(409, "Explicit review-only Drive controls are required.")
        fixture = emulator.register(payload.scenario)
        connection = UserDriveConnection(
            company_id=context.company.id, membership_id=context.membership.id,
            provider="google_drive", status="connected", provider_account_id=fixture.file_id,
            display_email="drive-emulator@example.com", scopes_json=GOOGLE_DRIVE_SCOPES,
            encrypted_token_ref=_encrypt_token_payload({"access_token": fixture.access_token}),
        )
        session.add(connection)
        session.flush()
        candidate = DriveFileCandidate(
            company_id=context.company.id, drive_connection_id=connection.id,
            provider="google_drive", provider_file_id=fixture.file_id,
            provider_version=fixture.modified_time.isoformat(), modified_time=fixture.modified_time,
            name=fixture.filename, mime_type="text/plain",
            size_bytes=len(fixture.content), folder_path="offline-reviewed-evidence",
            suggested_matter_id=matter.id, status="new", confidence=1.0,
            provenance_json={"source": "offline-drive-browser-fixture"},
        )
        session.add(candidate)
        session.commit()
        return {
            "candidate_id": candidate.id, "connection_id": connection.id, "matter_id": matter.id,
            "filename": fixture.filename, "content": fixture.content.decode(),
            "size_bytes": len(fixture.content), "sha256": fixture.sha256,
        }

    @router.get("/fixtures/{candidate_id}")
    def fixture_evidence(
        candidate_id: str, session: DbSession,
        context: SessionContext = owner_dependency,
    ) -> dict[str, object]:
        require_fixture_owner(context)
        candidate = session.scalar(select(DriveFileCandidate).join(
            UserDriveConnection, UserDriveConnection.id == DriveFileCandidate.drive_connection_id,
        ).where(
            DriveFileCandidate.id == candidate_id,
            DriveFileCandidate.company_id == context.company.id,
            UserDriveConnection.membership_id == context.membership.id,
        ))
        if candidate is None or candidate.provider_file_id not in emulator.files:
            raise HTTPException(404, "Offline Drive fixture not found.")
        attachment = session.get(MatterAttachment, candidate.imported_attachment_id) if candidate.imported_attachment_id else None
        return {
            **emulator.evidence(candidate.provider_file_id),
            "status": candidate.status, "attachment_id": candidate.imported_attachment_id,
            "attachment_sha256": attachment.sha256_hex if attachment else None,
            "job_count": session.scalar(select(func.count()).select_from(DocumentProcessingJob).where(
                DocumentProcessingJob.attachment_id == candidate.imported_attachment_id,
            )) if attachment else 0,
            "import_audit_count": session.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.company_id == context.company.id,
                AuditEvent.target_id == candidate.id, AuditEvent.action == "drive.candidate.imported",
            )),
        }

    set_google_drive_provider_for_tests(emulator)
    app.include_router(router)
