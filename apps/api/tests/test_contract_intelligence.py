"""Tests for Sprint 5 BG-011 contract intelligence — non-LLM paths.

The LLM-backed extract/compare paths exercise external API calls so we
keep them out of the unit suite; the pure paths (playbook install,
redline DOCX parsing) are exercised here.
"""
# ruff: noqa: E501
# The redline test inlines verbatim Word XML (OOXML is a single-line
# format). Wrapping the lines breaks the DOCX parser, so we waive E501
# for this one test file.
from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient

from caseops_api.services.contract_intelligence import (
    DEFAULT_INDIAN_COMMERCIAL_PLAYBOOK,
    _structured_with_retry,
)
from caseops_api.services.contract_redline import parse_redline_docx


def _bootstrap(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Contracts Test LLP",
            "company_slug": "contracts-intel",
            "company_type": "law_firm",
            "owner_full_name": "Contracts Owner",
            "owner_email": "owner-contracts@example.com",
            "owner_password": "ContractsPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_contract(client: TestClient, token: str) -> str:
    resp = client.post(
        "/api/contracts/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "MSA with Acme India",
            "contract_code": "C-ACME-001",
            "contract_type": "msa",
            "counterparty_name": "Acme India Pvt Ltd",
            "status": "draft",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_install_default_playbook_seeds_15_indian_commercial_rules(
    client: TestClient,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)

    resp = client.post(
        f"/api/ai/contracts/{contract_id}/playbook/install-default",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["installed"] == len(DEFAULT_INDIAN_COMMERCIAL_PLAYBOOK)
    assert body["installed"] >= 15  # future-safe if we expand the default list

    workspace = client.get(
        f"/api/contracts/{contract_id}/workspace",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    rule_names = {r["rule_name"] for r in workspace["playbook_rules"]}
    # Every default rule is tagged so reruns are idempotent.
    assert all(name.endswith(" (default)") for name in rule_names)
    assert any("Liability cap" in name for name in rule_names)
    assert any("Arbitration" in name for name in rule_names)


def test_install_default_playbook_is_idempotent_with_replace_flag(
    client: TestClient,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        f"/api/ai/contracts/{contract_id}/playbook/install-default", headers=headers
    )
    client.post(
        f"/api/ai/contracts/{contract_id}/playbook/install-default", headers=headers
    )
    workspace = client.get(
        f"/api/contracts/{contract_id}/workspace", headers=headers
    ).json()
    # Still exactly the default count — the re-install replaced, not duplicated.
    assert len(workspace["playbook_rules"]) == len(
        DEFAULT_INDIAN_COMMERCIAL_PLAYBOOK
    )


def test_install_default_playbook_preserves_user_authored_rules(
    client: TestClient,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)
    headers = {"Authorization": f"Bearer {token}"}

    # User-authored rule (no "(default)" suffix).
    client.post(
        f"/api/contracts/{contract_id}/playbook-rules",
        headers=headers,
        json={
            "rule_name": "Firm override — warranty period 180 days",
            "clause_type": "warranties",
            "expected_position": "Warranty period extended to 180 days for this matter.",
            "severity": "medium",
        },
    )
    client.post(
        f"/api/ai/contracts/{contract_id}/playbook/install-default", headers=headers
    )
    client.post(
        f"/api/ai/contracts/{contract_id}/playbook/install-default", headers=headers
    )
    workspace = client.get(
        f"/api/contracts/{contract_id}/workspace", headers=headers
    ).json()
    names = {r["rule_name"] for r in workspace["playbook_rules"]}
    assert "Firm override — warranty period 180 days" in names
    assert len(workspace["playbook_rules"]) == (
        len(DEFAULT_INDIAN_COMMERCIAL_PLAYBOOK) + 1
    )


def test_extract_clauses_success_path_persists_rows(
    client: TestClient, monkeypatch,
) -> None:
    """Codex sign-off blocker (Ram-BUG-009, 2026-04-22): the failure
    regression I shipped covers safe degradation, but Codex
    correctly demanded a SUCCESS-path test for clause extraction
    too — without it, the happy path (LLM returns valid JSON →
    rows actually land in the DB) was never asserted, and Codex's
    direct local smoke returned 422 because the default mock LLM
    can't satisfy the strict pydantic clause schema. This test
    pins the contract: a provider that emits a valid extraction
    payload MUST result in ContractClause rows persisted with the
    [auto] notes prefix and the right risk_level + clause_type.
    """
    import json as _json
    import uuid as _uuid
    from datetime import UTC, datetime

    from sqlalchemy import select

    from caseops_api.db.models import (
        Contract,
        ContractAttachment,
        ContractClause,
        DocumentProcessingStatus,
    )
    from caseops_api.db.session import get_session_factory
    from caseops_api.services.contract_intelligence import extract_clauses
    from caseops_api.services.identity import SessionContext
    from caseops_api.services.llm import LLMCompletion, LLMMessage

    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)

    factory = get_session_factory()

    # Seed an attachment with extracted text so extract_clauses has
    # something to feed the LLM. We bypass the upload pipeline
    # because that's not what this test is about.
    with factory() as s:
        contract = s.get(Contract, contract_id)
        att = ContractAttachment(
            id=str(_uuid.uuid4()),
            contract_id=contract_id,
            original_filename="msa.pdf",
            storage_key=f"contracts/{contract_id}/{_uuid.uuid4()}.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            sha256_hex="0" * 64,
            processing_status=DocumentProcessingStatus.INDEXED,
            extracted_char_count=200,
            extracted_text=(
                "This Master Services Agreement is between the parties. "
                "Clause 11 Limitation of Liability: aggregate liability "
                "shall not exceed fees paid in the prior 12 months. "
                "Clause 12 Indemnity: the supplier indemnifies the customer "
                "for IP infringement and breach of confidentiality."
            ),
            processed_at=datetime.now(UTC),
        )
        s.add(att)
        s.commit()
        company_id = contract.company_id
        membership_id = next(iter(s.execute(
            __import__("sqlalchemy").text(
                "select id from company_memberships where company_id = :cid limit 1",
            ),
            {"cid": company_id},
        ).scalars().all()))

    class _ValidClauseProvider:
        name = "mock"
        model = "mock-valid-clauses"

        def generate(self, messages: list[LLMMessage], **_kw):
            payload = {
                "clauses": [
                    {
                        "clause_type": "limitation_of_liability",
                        "title": "Limitation of liability",
                        "clause_text": (
                            "Aggregate liability shall not exceed the fees "
                            "paid by the customer in the prior 12 months."
                        ),
                        "risk_level": "medium",
                        "rationale": "Standard 12-month cap.",
                    },
                    {
                        "clause_type": "indemnity",
                        "title": "Indemnity",
                        "clause_text": (
                            "Supplier indemnifies the customer for "
                            "IP infringement and breach of confidentiality."
                        ),
                        "risk_level": "high",
                        "rationale": "IP + confidentiality scope.",
                    },
                ]
            }
            return LLMCompletion(
                text=_json.dumps(payload),
                provider=self.name,
                model=self.model,
                prompt_tokens=10,
                completion_tokens=20,
                latency_ms=5,
            )

    monkeypatch.setattr(
        "caseops_api.services.contract_intelligence.build_provider",
        lambda *a, **kw: _ValidClauseProvider(),
    )

    with factory() as s:
        # Re-load company + membership to construct a SessionContext
        # the same way the route layer does.
        from caseops_api.db.models import Company, CompanyMembership

        company = s.get(Company, company_id)
        membership = s.get(CompanyMembership, membership_id)
        context = SessionContext(
            user=membership.user,
            company=company,
            membership=membership,
        )
        result = extract_clauses(s, context=context, contract_id=contract_id)
        s.commit()

    assert result.contract_id == contract_id
    assert result.inserted == 2
    assert result.provider == "mock"
    assert result.model == "mock-valid-clauses"

    # Rows landed in the DB with the [auto] notes prefix and the
    # right clause_type / risk_level pulled from the LLM payload.
    with factory() as s:
        rows = list(
            s.scalars(
                select(ContractClause).where(
                    ContractClause.contract_id == contract_id,
                )
            )
        )
    assert len(rows) == 2
    types = {r.clause_type for r in rows}
    assert types == {"limitation_of_liability", "indemnity"}
    risks = {r.clause_type: r.risk_level for r in rows}
    assert risks["limitation_of_liability"] == "medium"
    assert risks["indemnity"] == "high"
    for r in rows:
        assert (r.notes or "").startswith("[auto]")


def test_extract_obligations_success_path_persists_rows(
    client: TestClient, monkeypatch,
) -> None:
    """Codex sign-off blocker (Ram-BUG-010, 2026-04-22): same
    success-path proof for obligations. A provider that emits a
    valid obligation payload MUST result in ContractObligation
    rows persisted with the right priority + due_on.
    """
    import json as _json
    import uuid as _uuid
    from datetime import UTC, datetime
    from datetime import date as _date

    from sqlalchemy import select

    from caseops_api.db.models import (
        Contract,
        ContractAttachment,
        ContractObligation,
        DocumentProcessingStatus,
    )
    from caseops_api.db.session import get_session_factory
    from caseops_api.services.contract_intelligence import extract_obligations
    from caseops_api.services.identity import SessionContext
    from caseops_api.services.llm import LLMCompletion, LLMMessage

    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)

    factory = get_session_factory()
    with factory() as s:
        contract = s.get(Contract, contract_id)
        s.add(
            ContractAttachment(
                id=str(_uuid.uuid4()),
                contract_id=contract_id,
                original_filename="msa.pdf",
                storage_key=f"contracts/{contract_id}/{_uuid.uuid4()}.pdf",
                content_type="application/pdf",
                size_bytes=1024,
                sha256_hex="0" * 64,
                processing_status=DocumentProcessingStatus.INDEXED,
                extracted_char_count=120,
                extracted_text=(
                    "Customer shall pay supplier ₹5,00,000 within 30 days "
                    "of each milestone. Renewal notice: 60 days before "
                    "the term ends, on 2026-12-31."
                ),
                processed_at=datetime.now(UTC),
            ),
        )
        s.commit()
        company_id = contract.company_id

    class _ValidObligationProvider:
        name = "mock"
        model = "mock-valid-obligations"

        def generate(self, messages: list[LLMMessage], **_kw):
            payload = {
                "obligations": [
                    {
                        "title": "Milestone payment",
                        "description": "₹5,00,000 within 30 days of milestone",
                        "due_on_iso": "2026-12-31",
                        "priority": "high",
                    },
                    {
                        "title": "Renewal notice",
                        "description": "60 days before term ends",
                        "due_on_iso": None,
                        "priority": "medium",
                    },
                ]
            }
            return LLMCompletion(
                text=_json.dumps(payload),
                provider=self.name,
                model=self.model,
                prompt_tokens=10,
                completion_tokens=20,
                latency_ms=5,
            )

    monkeypatch.setattr(
        "caseops_api.services.contract_intelligence.build_provider",
        lambda *a, **kw: _ValidObligationProvider(),
    )

    with factory() as s:
        from caseops_api.db.models import Company, CompanyMembership

        company = s.get(Company, company_id)
        membership = s.scalars(
            select(CompanyMembership).where(
                CompanyMembership.company_id == company_id,
            ).limit(1)
        ).first()
        context = SessionContext(
            user=membership.user,
            company=company,
            membership=membership,
        )
        result = extract_obligations(s, context=context, contract_id=contract_id)
        s.commit()

    assert result.contract_id == contract_id
    assert result.inserted == 2

    with factory() as s:
        rows = list(
            s.scalars(
                select(ContractObligation).where(
                    ContractObligation.contract_id == contract_id,
                )
            )
        )
    assert len(rows) == 2
    titles = {r.title for r in rows}
    assert titles == {"Milestone payment", "Renewal notice"}
    by_title = {r.title: r for r in rows}
    assert by_title["Milestone payment"].priority == "high"
    assert by_title["Milestone payment"].due_on == _date(2026, 12, 31)
    assert by_title["Renewal notice"].priority == "medium"
    assert by_title["Renewal notice"].due_on is None
    for r in rows:
        assert (r.description or "").startswith("[auto]")


def test_structured_with_retry_returns_actionable_422_when_provider_keeps_failing() -> None:
    """Strict Ledger #9 (2026-04-22) — Ram-BUG-009 (clauses) and
    Ram-BUG-010 (obligations) were generic 500s because contract
    intelligence only caught LLMResponseFormatError. The
    AnthropicProvider 503 wraps as LLMProviderError (parent), which
    slipped past the catch and surfaced as opaque 500s with no
    actionable detail.

    Commit 4104265 introduced ``_structured_with_retry`` (same-model
    retry on LLMProviderError, then 422 with actionable detail).
    This is a unit test of that helper — covers all three call
    sites uniformly (extract_clauses, extract_obligations,
    compare_playbook) without bootstrapping the full upload flow.
    """
    from fastapi import HTTPException
    from pydantic import BaseModel

    from caseops_api.services.llm import LLMCallContext, LLMProviderError

    class _AlwaysFails:
        name = "mock"
        model = "mock-503"

        def generate(self, messages, **_kw):
            raise LLMProviderError(
                "Anthropic call failed: 503 overloaded — please retry",
            )

    class _Schema(BaseModel):
        ok: bool

    try:
        _structured_with_retry(
            _AlwaysFails(),
            schema=_Schema,
            messages=[],
            context=LLMCallContext(
                purpose="metadata_extract",
                tenant_id="t-test",
                matter_id=None,
            ),
            temperature=0.0,
            max_tokens=512,
            session=None,
            feature="extract clauses",
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "Could not extract clauses" in exc.detail
        assert "LLMProviderError" in exc.detail
        assert "retry in a minute" in exc.detail.lower()
    else:
        raise AssertionError("expected HTTPException 422 after both retries")


def test_parse_redline_docx_recovers_insertions_and_deletions() -> None:
    # Build a tiny DOCX in-memory with tracked changes; python-docx has no
    # high-level API to author ins/del, so we write the XML by hand and
    # ship the minimal DOCX skeleton via zipfile.
    from zipfile import ZIP_DEFLATED, ZipFile

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t xml:space="preserve">Liability shall be capped at </w:t></w:r><w:ins w:id="1" w:author="Counsel" w:date="2026-04-18T12:00:00Z"><w:r><w:t xml:space="preserve">24 </w:t></w:r></w:ins><w:del w:id="2" w:author="Counsel" w:date="2026-04-18T12:00:00Z"><w:r><w:delText xml:space="preserve">12 </w:delText></w:r></w:del><w:r><w:t>months of fees.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Governing law is India.</w:t></w:r></w:p>
  </w:body>
</w:document>"""

    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    buf.seek(0)

    result = parse_redline_docx(source=buf.read(), attachment_name="liability.docx")
    kinds = [c.kind for c in result.changes]
    assert "insertion" in kinds
    assert "deletion" in kinds
    assert result.insertion_count == 1
    assert result.deletion_count == 1
    assert result.author_counts.get("Counsel") == 2
    # Changes are paragraph-scoped.
    assert all(c.paragraph_index == 0 for c in result.changes)


def test_parse_redline_docx_empty_on_clean_document() -> None:
    from docx import Document

    doc = Document()
    doc.add_paragraph("Standard NDA body, no tracked changes.")
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    result = parse_redline_docx(source=buf.read())
    assert result.insertion_count == 0
    assert result.deletion_count == 0
    assert result.paragraph_count >= 1
