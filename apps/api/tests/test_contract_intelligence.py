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
        lowered = exc.detail.lower()
        assert "retry" in lowered or "support" in lowered
    else:
        raise AssertionError("expected HTTPException 422 after both retries")


def test_structured_with_retry_quota_returns_actionable_503_without_retry_or_raw_leak() -> None:
    from fastapi import HTTPException
    from pydantic import BaseModel

    from caseops_api.services.llm import (
        LLMCallContext,
        LLMQuotaExhaustedError,
    )

    class _QuotaFails:
        name = "openai"
        model = "gpt-5-mini"
        calls = 0

        def generate(self, messages, **_kw):
            self.calls += 1
            raise LLMQuotaExhaustedError(
                "OpenAI quota exhausted: Error code: 429 - {'error': "
                "{'code': 'insufficient_quota', 'message': 'billing raw'}}"
            )

    class _Schema(BaseModel):
        ok: bool

    provider = _QuotaFails()
    try:
        _structured_with_retry(
            provider,
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
        assert exc.status_code == 503
        assert "provider quota is exhausted" in exc.detail
        assert "contract intelligence result" in exc.detail
        assert "insufficient_quota" not in exc.detail
        assert "billing raw" not in exc.detail
        assert "No output was saved" in exc.detail
        assert provider.calls == 1
    else:
        raise AssertionError("expected HTTPException 503 for provider quota")


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


# ---------------------------------------------------------------------------
# ADP-13: party-perspective contract clause extraction
# ---------------------------------------------------------------------------


def _seed_party_contract(client: TestClient, token: str) -> tuple[str, str, str, str]:
    import uuid as _uuid
    from datetime import UTC, datetime

    from sqlalchemy import text as _sql_text

    from caseops_api.db.models import (
        Contract,
        ContractAttachment,
        DocumentProcessingStatus,
    )
    from caseops_api.db.session import get_session_factory

    contract_id = _create_contract(client, token)
    attachment_id = str(_uuid.uuid4())
    factory = get_session_factory()
    with factory() as s:
        contract = s.get(Contract, contract_id)
        att = ContractAttachment(
            id=attachment_id,
            contract_id=contract_id,
            original_filename="msa.pdf",
            storage_key=f"contracts/{contract_id}/{_uuid.uuid4()}.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            sha256_hex="0" * 64,
            processing_status=DocumentProcessingStatus.INDEXED,
            extracted_char_count=900,
            extracted_text=(
                "Master Services Agreement between Acme India Private Limited "
                "(Supplier) and Beta Software Solutions Inc. (Customer). "
                "Clause 4 Payment: Customer shall pay Supplier within "
                "thirty days of receipt of invoice. "
                "Clause 7 Notice: each party shall send notices to the "
                "address listed in Schedule A. "
                "Clause 9 Termination: Customer may terminate for convenience "
                "on sixty days written notice. "
                "Clause 11 Limitation of Liability: aggregate liability of "
                "Supplier shall not exceed fees paid by Customer in the "
                "prior twelve months. "
                "Clause 12 Indemnity: Supplier indemnifies Customer for IP "
                "infringement and breach of confidentiality. "
                "Clause 14 Confidentiality: both parties shall keep "
                "confidential information of the other party in strict "
                "confidence. "
                "Clause 18 Dispute Resolution: any dispute shall be referred "
                "to arbitration seated in Mumbai. "
                "Clause 19 Either party may invoke step-in rights upon "
                "material breach."
            ),
            processed_at=datetime.now(UTC),
        )
        s.add(att)
        s.commit()
        company_id = contract.company_id
        membership_id = next(iter(s.execute(
            _sql_text(
                "select id from company_memberships where company_id = :cid limit 1",
            ),
            {"cid": company_id},
        ).scalars().all()))
    return contract_id, attachment_id, company_id, membership_id


def _make_party_provider(items: list[dict]):
    import json as _json

    from caseops_api.services.llm import LLMCompletion

    class _PartyProvider:
        name = "mock"
        model = "mock-party-extract"

        def generate(self, messages=None, **_kw):
            assert messages is not None
            return LLMCompletion(
                text=_json.dumps({"items": items}),
                provider=self.name,
                model=self.model,
                prompt_tokens=15,
                completion_tokens=80,
                latency_ms=7,
            )

    return _PartyProvider()


def _party_payload(represented: str) -> dict:
    return {
        "first_party_name": "Acme India Private Limited",
        "second_party_name": "Beta Software Solutions Inc.",
        "first_party_aliases": ["Acme", "Supplier"],
        "second_party_aliases": ["Beta", "Customer"],
        "represented_party": represented,
    }


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_party_extract_vendor_and_customer_views_on_same_contract(
    client: TestClient, monkeypatch,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id, attachment_id, _company_id, _membership_id = _seed_party_contract(
        client, token,
    )

    items = [
        {
            "category": "payment",
            "summary": "Customer must pay Supplier within 30 days of invoice.",
            "assigned_party": "second",
            "ambiguity_reason": "",
            "snippet": "Customer shall pay Supplier within thirty days of receipt of invoice.",
            "locator": "Clause 4",
        },
        {
            "category": "liability_cap",
            "summary": "Supplier liability capped at 12 months of fees.",
            "assigned_party": "first",
            "ambiguity_reason": "",
            "snippet": "aggregate liability of Supplier shall not exceed fees paid by Customer in the prior twelve months.",
            "locator": "Clause 11",
        },
        {
            "category": "indemnity",
            "summary": "Supplier indemnifies Customer for IP and confidentiality.",
            "assigned_party": "first",
            "ambiguity_reason": "",
            "snippet": "Supplier indemnifies Customer for IP infringement and breach of confidentiality.",
            "locator": "Clause 12",
        },
    ]
    monkeypatch.setattr(
        "caseops_api.services.contract_intelligence.build_provider",
        lambda *a, **kw: _make_party_provider(items),
    )

    supplier_view = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract-by-party",
        headers=_bearer(token),
        json=_party_payload("first"),
    )
    assert supplier_view.status_code == 200, supplier_view.text
    supplier_body = supplier_view.json()
    assert supplier_body["represented_party"] == "first"
    supplier_categories = {item["category"] for item in supplier_body["represented_items"]}
    counterparty_categories = {item["category"] for item in supplier_body["counterparty_items"]}
    assert "indemnity" in supplier_categories
    assert "liability_cap" in supplier_categories
    assert "payment" in counterparty_categories

    customer_view = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract-by-party",
        headers=_bearer(token),
        json=_party_payload("second"),
    )
    assert customer_view.status_code == 200, customer_view.text
    customer_body = customer_view.json()
    assert customer_body["represented_party"] == "second"
    customer_repr_categories = {item["category"] for item in customer_body["represented_items"]}
    customer_counter_categories = {item["category"] for item in customer_body["counterparty_items"]}
    assert "payment" in customer_repr_categories
    assert "indemnity" in customer_counter_categories
    assert "liability_cap" in customer_counter_categories

    for item in supplier_body["represented_items"] + supplier_body["counterparty_items"]:
        assert item["source"]["attachment_id"] == attachment_id
        assert len(item["source"]["snippet"]) <= 280


def test_party_extract_respects_alias_for_party_resolution(
    client: TestClient, monkeypatch,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id, _attachment_id, _company_id, _membership_id = _seed_party_contract(
        client, token,
    )

    items = [
        {
            "category": "indemnity",
            "summary": "Supplier indemnifies Customer for IP and confidentiality.",
            "assigned_party": "first",
            "ambiguity_reason": "",
            "snippet": "Supplier indemnifies Customer for IP infringement and breach of confidentiality.",
            "locator": "Clause 12",
        },
    ]
    monkeypatch.setattr(
        "caseops_api.services.contract_intelligence.build_provider",
        lambda *a, **kw: _make_party_provider(items),
    )

    response = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract-by-party",
        headers=_bearer(token),
        json=_party_payload("first"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["represented_items"]) == 1
    assert body["represented_items"][0]["assigned_party"] == "first"

    noisy_payload = {
        **_party_payload("first"),
        "first_party_aliases": ["Acme", "  ", "Supplier", ""],
    }
    response2 = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract-by-party",
        headers=_bearer(token),
        json=noisy_payload,
    )
    assert response2.status_code == 200, response2.text


def test_party_extract_flags_ambiguous_items_separately(
    client: TestClient, monkeypatch,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id, _attachment_id, _company_id, _membership_id = _seed_party_contract(
        client, token,
    )

    items = [
        {
            "category": "termination",
            "summary": "Either party may invoke step-in rights on material breach.",
            "assigned_party": "ambiguous",
            "ambiguity_reason": "Either party reference cannot be resolved without external context.",
            "snippet": "Either party may invoke step-in rights upon material breach.",
            "locator": "Clause 19",
        },
    ]
    monkeypatch.setattr(
        "caseops_api.services.contract_intelligence.build_provider",
        lambda *a, **kw: _make_party_provider(items),
    )

    response = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract-by-party",
        headers=_bearer(token),
        json=_party_payload("first"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["represented_items"] == []
    assert body["counterparty_items"] == []
    assert len(body["ambiguous_items"]) == 1
    assert body["ambiguous_items"][0]["category"] == "termination"
    assert "Either party" in body["ambiguous_items"][0]["ambiguity_reason"]


def test_party_extract_drops_items_with_unverified_source(
    client: TestClient, monkeypatch,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id, _attachment_id, _company_id, _membership_id = _seed_party_contract(
        client, token,
    )

    items = [
        {
            "category": "payment",
            "summary": "Customer pays Supplier within 30 days.",
            "assigned_party": "second",
            "ambiguity_reason": "",
            "snippet": "Customer shall pay Supplier within thirty days of receipt of invoice.",
            "locator": "Clause 4",
        },
        {
            "category": "indemnity",
            "summary": "Supplier promises moon-shot indemnity for stellar damages.",
            "assigned_party": "first",
            "ambiguity_reason": "",
            "snippet": "Supplier shall indemnify Customer for any damage caused by celestial impact events including meteor strikes.",
            "locator": "Clause 99",
        },
    ]
    monkeypatch.setattr(
        "caseops_api.services.contract_intelligence.build_provider",
        lambda *a, **kw: _make_party_provider(items),
    )

    response = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract-by-party",
        headers=_bearer(token),
        json=_party_payload("first"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dropped_source_unverified_count"] == 1
    assert len(body["counterparty_items"]) == 1
    assert body["counterparty_items"][0]["category"] == "payment"
    surviving_summaries = " ".join(
        item["summary"]
        for item in body["represented_items"] + body["counterparty_items"]
    )
    assert "celestial" not in surviving_summaries
    assert "moon-shot" not in surviving_summaries


def test_party_extract_409_when_no_contract_text_available(
    client: TestClient,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)

    response = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract-by-party",
        headers=_bearer(token),
        json=_party_payload("first"),
    )
    assert response.status_code == 409, response.text
    assert "extracted attachment text" in response.json()["detail"]


def test_party_extract_writes_model_run_for_token_governance(
    client: TestClient, monkeypatch,
) -> None:
    from sqlalchemy import select

    from caseops_api.db.models import ModelRun
    from caseops_api.db.session import get_session_factory

    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id, _attachment_id, company_id, _membership_id = _seed_party_contract(
        client, token,
    )

    items = [
        {
            "category": "payment",
            "summary": "Customer pays Supplier in 30 days.",
            "assigned_party": "second",
            "ambiguity_reason": "",
            "snippet": "Customer shall pay Supplier within thirty days of receipt of invoice.",
            "locator": "Clause 4",
        },
    ]
    monkeypatch.setattr(
        "caseops_api.services.contract_intelligence.build_provider",
        lambda *a, **kw: _make_party_provider(items),
    )

    response = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract-by-party",
        headers=_bearer(token),
        json=_party_payload("first"),
    )
    assert response.status_code == 200, response.text

    factory = get_session_factory()
    with factory() as s:
        runs = list(s.scalars(
            select(ModelRun).where(ModelRun.company_id == company_id)
        ))
    assert len(runs) >= 1
    assert any(r.model == "mock-party-extract" for r in runs)
    assert all(r.prompt_hash and len(r.prompt_hash) == 64 for r in runs)


def test_party_extract_audit_metadata_is_redacted(
    client: TestClient, monkeypatch,
) -> None:
    import json as _json

    from sqlalchemy import select

    from caseops_api.db.models import AuditEvent
    from caseops_api.db.session import get_session_factory

    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id, _attachment_id, company_id, _membership_id = _seed_party_contract(
        client, token,
    )

    items = [
        {
            "category": "confidentiality",
            "summary": "Both parties keep confidential info confidential.",
            "assigned_party": "both",
            "ambiguity_reason": "",
            "snippet": "both parties shall keep confidential information of the other party in strict confidence.",
            "locator": "Clause 14",
        },
    ]
    monkeypatch.setattr(
        "caseops_api.services.contract_intelligence.build_provider",
        lambda *a, **kw: _make_party_provider(items),
    )

    response = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract-by-party",
        headers=_bearer(token),
        json=_party_payload("first"),
    )
    assert response.status_code == 200, response.text

    factory = get_session_factory()
    with factory() as s:
        event = s.scalar(
            select(AuditEvent)
            .where(AuditEvent.company_id == company_id)
            .where(AuditEvent.action == "contract.party_clauses.extract")
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        )
        assert event is not None
        metadata = _json.loads(event.metadata_json or "{}")

    assert metadata["represented_party"] == "first"
    assert metadata["first_party_alias_count"] == 2
    assert metadata["second_party_alias_count"] == 2
    assert metadata["represented_item_count"] == 1
    assert metadata["ambiguous_item_count"] == 0
    assert metadata["dropped_source_unverified_count"] == 0
    assert isinstance(metadata["party_metadata_hash"], str)
    assert len(metadata["party_metadata_hash"]) == 64

    redacted = _json.dumps(metadata)
    for needle in [
        "Acme India",
        "Beta Software",
        "Clause 14",
        "both parties shall keep",
        "confidential information",
    ]:
        assert needle not in redacted, (needle, redacted)


def test_existing_clauses_extract_endpoint_unchanged_by_adp13(
    client: TestClient, monkeypatch,
) -> None:
    import json as _json

    from sqlalchemy import select

    from caseops_api.db.models import ContractClause
    from caseops_api.db.session import get_session_factory
    from caseops_api.services.llm import LLMCompletion

    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id, _attachment_id, _company_id, _membership_id = _seed_party_contract(
        client, token,
    )

    class _ValidClauseProvider:
        name = "mock"
        model = "mock-valid-clauses"

        def generate(self, messages=None, **_kw):
            assert messages is not None
            return LLMCompletion(
                text=_json.dumps({
                    "clauses": [
                        {
                            "clause_type": "limitation_of_liability",
                            "title": "Liability cap",
                            "clause_text": "Aggregate liability shall not exceed fees paid in the prior 12 months.",
                            "risk_level": "medium",
                            "rationale": "Standard 12-month cap.",
                        }
                    ]
                }),
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

    response = client.post(
        f"/api/ai/contracts/{contract_id}/clauses/extract",
        headers=_bearer(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contract_id"] == contract_id
    assert body["inserted"] == 1

    factory = get_session_factory()
    with factory() as s:
        rows = list(s.scalars(
            select(ContractClause).where(ContractClause.contract_id == contract_id)
        ))
    assert len(rows) == 1
    assert rows[0].clause_type == "limitation_of_liability"


# ---------------------------------------------------------------------------
# ADP-14: tenant-managed contract playbook admin + deterministic compare
# ---------------------------------------------------------------------------


def _make_playbook(
    client: TestClient, token: str, *, name: str = "Vendor MSA playbook",
) -> dict:
    response = client.post(
        "/api/contracts/tenant-playbooks",
        headers=_bearer(token),
        json={
            "name": name,
            "description": "Standard vendor MSA expectations",
            "contract_type_key": "master_services_agreement",
            "jurisdiction": "India",
            "party_perspective": "first",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _make_rule(
    client: TestClient,
    token: str,
    playbook_id: str,
    *,
    rule_name: str = "Liability cap",
    clause_type: str = "limitation_of_liability",
    keyword_pattern: str | None = "twelve months",
    severity: str = "high",
) -> dict:
    payload = {
        "rule_name": rule_name,
        "clause_type": clause_type,
        "expected_position": "Aggregate liability capped at 12 months of fees.",
        "fallback_text": "Insert a 12-month aggregate cap on liability.",
        "rationale": "Standard market position for SaaS MSAs.",
        "severity": severity,
    }
    if keyword_pattern is not None:
        payload["keyword_pattern"] = keyword_pattern
    response = client.post(
        f"/api/contracts/tenant-playbooks/{playbook_id}/rules",
        headers=_bearer(token),
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _attach_clauses(
    contract_id: str,
    clauses: list[tuple[str, str, str]],
) -> None:
    """Seed ContractClause rows on the contract (clause_type, title, body)."""
    import uuid as _uuid

    from caseops_api.db.models import ContractClause
    from caseops_api.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as s:
        for clause_type, title, body in clauses:
            s.add(
                ContractClause(
                    id=str(_uuid.uuid4()),
                    contract_id=contract_id,
                    title=title,
                    clause_type=clause_type,
                    clause_text=body,
                    risk_level="medium",
                    notes="[auto]",
                )
            )
        s.commit()


def test_tenant_playbook_crud_round_trip(client: TestClient) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]

    pb = _make_playbook(client, token)
    assert pb["is_archived"] is False
    assert pb["rule_count"] == 0
    assert pb["active_rule_count"] == 0

    rule = _make_rule(client, token, pb["id"])
    assert rule["severity"] == "high"
    assert rule["keyword_pattern"] == "twelve months"

    listed = client.get(
        "/api/contracts/tenant-playbooks", headers=_bearer(token),
    )
    assert listed.status_code == 200
    assert any(p["id"] == pb["id"] for p in listed.json()["playbooks"])

    detail = client.get(
        f"/api/contracts/tenant-playbooks/{pb['id']}", headers=_bearer(token),
    )
    assert detail.status_code == 200
    assert detail.json()["rule_count"] == 1
    assert detail.json()["active_rule_count"] == 1

    # Archive the rule
    rule_archive = client.patch(
        f"/api/contracts/tenant-playbooks/{pb['id']}/rules/{rule['id']}",
        headers=_bearer(token),
        json={"is_archived": True},
    )
    assert rule_archive.status_code == 200
    assert rule_archive.json()["is_archived"] is True

    detail2 = client.get(
        f"/api/contracts/tenant-playbooks/{pb['id']}", headers=_bearer(token),
    )
    assert detail2.json()["active_rule_count"] == 0
    assert detail2.json()["rule_count"] == 1

    # Archive the playbook
    pb_archive = client.patch(
        f"/api/contracts/tenant-playbooks/{pb['id']}",
        headers=_bearer(token),
        json={"is_archived": True, "description": "Archived for legacy."},
    )
    assert pb_archive.status_code == 200
    assert pb_archive.json()["is_archived"] is True


def test_tenant_playbook_isolation_across_companies(client: TestClient) -> None:
    tenant_a = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "ADP14 Tenant A",
            "company_slug": "adp14-tenant-a",
            "company_type": "law_firm",
            "owner_full_name": "Owner A",
            "owner_email": "owner-a@adp14.example",
            "owner_password": "FoundersPass123!",
        },
    ).json()
    tenant_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "ADP14 Tenant B",
            "company_slug": "adp14-tenant-b",
            "company_type": "law_firm",
            "owner_full_name": "Owner B",
            "owner_email": "owner-b@adp14.example",
            "owner_password": "FoundersPass123!",
        },
    ).json()
    token_a = str(tenant_a["access_token"])
    token_b = str(tenant_b["access_token"])

    pb_a = _make_playbook(client, token_a, name="A playbook")
    pb_b = _make_playbook(client, token_b, name="B playbook")

    list_a = client.get(
        "/api/contracts/tenant-playbooks", headers=_bearer(token_a),
    ).json()["playbooks"]
    assert {p["name"] for p in list_a} == {"A playbook"}

    list_b = client.get(
        "/api/contracts/tenant-playbooks", headers=_bearer(token_b),
    ).json()["playbooks"]
    assert {p["name"] for p in list_b} == {"B playbook"}

    # B cannot fetch A's playbook
    cross = client.get(
        f"/api/contracts/tenant-playbooks/{pb_a['id']}",
        headers=_bearer(token_b),
    )
    assert cross.status_code == 404

    # B cannot update / add rule to A's playbook
    cross_rule = client.post(
        f"/api/contracts/tenant-playbooks/{pb_a['id']}/rules",
        headers=_bearer(token_b),
        json={
            "rule_name": "Sneaky",
            "clause_type": "indemnity",
            "expected_position": "Steal.",
        },
    )
    assert cross_rule.status_code == 404
    _ = pb_b  # tenant B's playbook is unused here; just bound for clarity.


def test_tenant_playbook_create_requires_contract_rule_manager(
    client: TestClient,
) -> None:
    session_data = _bootstrap(client)
    owner_token = str(session_data["access_token"])
    # Invite a regular user without contracts:manage_rules.
    invite = client.post(
        "/api/companies/current/users",
        headers=_bearer(owner_token),
        json={
            "full_name": "Plain user",
            "email": "plain@adp14.example",
            "role": "member",
            "password": "PlainPass123!",
        },
    )
    assert invite.status_code == 200, invite.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "contracts-intel",
            "email": "plain@adp14.example",
            "password": "PlainPass123!",
        },
    )
    assert login.status_code == 200, login.text
    plain_token = str(login.json()["access_token"])

    forbidden = client.post(
        "/api/contracts/tenant-playbooks",
        headers=_bearer(plain_token),
        json={"name": "Should fail"},
    )
    assert forbidden.status_code == 403


def test_tenant_playbook_compare_statuses_matched_missing_deviation(
    client: TestClient,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)
    pb = _make_playbook(client, token)
    _make_rule(
        client, token, pb["id"],
        rule_name="Liability cap (12 months)",
        clause_type="limitation_of_liability",
        keyword_pattern="twelve months",
    )
    _make_rule(
        client, token, pb["id"],
        rule_name="Indemnity (IP)",
        clause_type="indemnity",
        keyword_pattern="IP infringement",
    )
    _make_rule(
        client, token, pb["id"],
        rule_name="Confidentiality (mutual)",
        clause_type="confidentiality",
        keyword_pattern="mutual",
    )

    # Matched: limitation_of_liability with the keyword present.
    # Deviation: indemnity present but missing "IP infringement" keyword.
    # Missing: no confidentiality clause at all.
    _attach_clauses(contract_id, [
        (
            "limitation_of_liability",
            "Cap",
            "Aggregate liability shall not exceed fees paid in the prior twelve months.",
        ),
        (
            "indemnity",
            "Indemnity",
            "Each party shall indemnify the other against third-party claims.",
        ),
    ])

    response = client.post(
        f"/api/contracts/{contract_id}/tenant-playbook-compare",
        headers=_bearer(token),
        json={"playbook_id": pb["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    by_rule = {f["rule_name"]: f for f in body["findings"]}
    assert by_rule["Liability cap (12 months)"]["status"] == "matched"
    assert by_rule["Liability cap (12 months)"]["source"]["clause_id"]
    assert by_rule["Indemnity (IP)"]["status"] == "deviation"
    assert by_rule["Indemnity (IP)"]["source"]["clause_id"]
    assert "IP infringement" in by_rule["Indemnity (IP)"]["note"]
    assert by_rule["Confidentiality (mutual)"]["status"] == "missing"
    assert by_rule["Confidentiality (mutual)"]["source"] is None

    assert body["summary"]["matched"] == 1
    assert body["summary"]["missing"] == 1
    assert body["summary"]["deviation"] == 1
    assert body["summary"]["needs_review"] == 0
    assert body["summary"]["total_rules"] == 3


def test_tenant_playbook_compare_returns_needs_review_with_no_clauses(
    client: TestClient,
) -> None:
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)
    pb = _make_playbook(client, token)
    _make_rule(client, token, pb["id"])

    response = client.post(
        f"/api/contracts/{contract_id}/tenant-playbook-compare",
        headers=_bearer(token),
        json={"playbook_id": pb["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["needs_review"] == 1
    assert body["summary"]["matched"] == 0
    assert body["findings"][0]["source"] is None


def test_tenant_playbook_compare_missing_finding_carries_no_source(
    client: TestClient,
) -> None:
    """PRD acceptance: missing findings must not fabricate a source."""
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)
    pb = _make_playbook(client, token)
    _make_rule(
        client, token, pb["id"],
        rule_name="Dispute resolution (arbitration)",
        clause_type="arbitration",
        keyword_pattern=None,
    )
    _attach_clauses(contract_id, [
        ("limitation_of_liability", "Cap", "Liability cap is twelve months."),
    ])

    response = client.post(
        f"/api/contracts/{contract_id}/tenant-playbook-compare",
        headers=_bearer(token),
        json={"playbook_id": pb["id"]},
    )
    body = response.json()
    finding = body["findings"][0]
    assert finding["status"] == "missing"
    assert finding["source"] is None
    assert finding["fallback_text"] is not None


def test_tenant_playbook_compare_audit_metadata_is_redacted(
    client: TestClient,
) -> None:
    import json as _json

    from sqlalchemy import select

    from caseops_api.db.models import AuditEvent
    from caseops_api.db.session import get_session_factory

    session_data = _bootstrap(client)
    token = session_data["access_token"]
    company_id = str(session_data["company"]["id"])
    contract_id = _create_contract(client, token)
    pb = _make_playbook(client, token, name="Audit-test playbook")
    _make_rule(client, token, pb["id"])
    _attach_clauses(contract_id, [
        ("limitation_of_liability", "Cap", "Liability cap is twelve months of fees."),
    ])

    response = client.post(
        f"/api/contracts/{contract_id}/tenant-playbook-compare",
        headers=_bearer(token),
        json={"playbook_id": pb["id"]},
    )
    assert response.status_code == 200, response.text

    factory = get_session_factory()
    with factory() as s:
        event = s.scalar(
            select(AuditEvent)
            .where(AuditEvent.company_id == company_id)
            .where(AuditEvent.action == "contract_playbook.tenant.compare")
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        )
        assert event is not None
        metadata = _json.loads(event.metadata_json or "{}")

    assert metadata["playbook_id"] == pb["id"]
    assert metadata["contract_id"] == contract_id
    assert metadata["total_rules"] == 1
    assert isinstance(metadata["playbook_name_hash"], str)
    assert len(metadata["playbook_name_hash"]) == 64
    redacted = _json.dumps(metadata)
    for needle in [
        "Audit-test playbook",
        "Liability cap is twelve",
        "limitation_of_liability is matched",  # full LLM summary text
    ]:
        assert needle not in redacted, (needle, redacted)


def test_existing_per_contract_playbook_compare_endpoint_unchanged(
    client: TestClient,
) -> None:
    """Backward-compat: legacy LLM compare_playbook endpoint still
    exists and responds (with 200 + empty findings when no rules are
    seeded — the no-LLM short-circuit path)."""
    session_data = _bootstrap(client)
    token = session_data["access_token"]
    contract_id = _create_contract(client, token)
    # No rules installed → service short-circuits without calling the LLM.
    response = client.post(
        f"/api/ai/contracts/{contract_id}/playbook/compare",
        headers=_bearer(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["findings"] == []
    assert response.json()["provider"] == "caseops-no-rules"
