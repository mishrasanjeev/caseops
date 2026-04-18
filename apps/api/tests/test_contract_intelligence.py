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
