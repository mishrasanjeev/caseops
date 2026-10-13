"""Financial admission denial is not evidence that a legal source is corrupt."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from caseops_api.db.models import (
    AuthorityDocument,
    Company,
    Matter,
    MatterCourtOrder,
    ModelRun,
    PredictiveOutcomeClassification,
    Statute,
    StatuteSection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import enrich_statute_sections as statute_cli
from caseops_api.services import predictive_outcomes as predictive
from caseops_api.services import statute_enrichment as statute
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.llm import LLMCompletion, LLMProviderError
from tests.test_predictive_outcomes import _seed_doc
from tests.test_statute_enrichment import _seed_statute_and_section

_NO_SIGNAL = "The Court records the operative result in the attached detailed reasons."
_NOTICE = "Notice is issued to the respondent. The source identifies the parties."
_DENIAL = "The shared AI money allowance is exhausted. No external request was sent."
_PROVIDER = SimpleNamespace(name="openai", model="offline-classification")


def _columns(row) -> dict:
    return {attr.key: getattr(row, attr.key) for attr in inspect(row).mapper.column_attrs}


def _source(session, kind: str, *, text: str):
    if kind == "authority":
        source = session.get(AuthorityDocument, _seed_doc(text=text))
        assert source is not None
        return source, lambda **kw: predictive.classify_authority_document(
            session, source, **kw
        )
    company = Company(
        name="Offline classification", slug=f"money-stop-{uuid4().hex}",
        company_type="law_firm", tenant_key=str(uuid4()),
    )
    session.add(company)
    session.flush()
    matter = Matter(
        company_id=company.id, title="Offline order", matter_code="MONEY-STOP",
        practice_area="Commercial", forum_level="high_court", status="intake",
    )
    session.add(matter)
    session.flush()
    order = MatterCourtOrder(
        matter_id=matter.id, order_date=date(2026, 10, 11), title="Offline order",
        summary="Source retained", order_text=text, source="test_fixture",
    )
    session.add(order)
    session.commit()
    return order, lambda **kw: predictive.classify_matter_court_order(
        session, order, matter=matter, **kw
    )


@pytest.mark.parametrize("kind", ["authority", "order"])
@pytest.mark.parametrize("force", [False, True])
def test_predictive_money_denial_preserves_source_evidence_and_caller_work(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, kind: str, force: bool,
) -> None:
    calls = []

    def denied(*args, **kwargs):
        calls.append(kwargs["context"].metadata["source_id"])
        raise AiMoneyBudgetError(_DENIAL)

    monkeypatch.setattr(predictive, "generate_structured", denied)
    with get_session_factory()() as session:
        source, classify = _source(
            session, kind, text=_NOTICE if force else _NO_SIGNAL,
        )
        if force:
            assert classify()
            if kind == "authority":
                source.document_text = _NO_SIGNAL
            else:
                source.order_text = _NO_SIGNAL
            session.commit()
        before_source = _columns(source)
        before_rows = [
            _columns(row) for row in session.scalars(
                select(PredictiveOutcomeClassification).where(
                    PredictiveOutcomeClassification.source_id == source.id
                ).order_by(PredictiveOutcomeClassification.id)
            )
        ]
        sibling = Statute(
            id="pending-sibling", short_name="Pending", long_name="Pending sibling",
            enacted_year=2026, jurisdiction="india", is_active=True,
        )
        session.add(sibling)
        errors = []
        try:
            classify(use_llm=True, force=force, provider=_PROVIDER)
        except AiMoneyBudgetError as exc:
            errors.append(exc)
        # Even a caller that catches the operational stop must retain old evidence.
        session.commit()
        after_rows = [
            _columns(row) for row in session.scalars(
                select(PredictiveOutcomeClassification).where(
                    PredictiveOutcomeClassification.source_id == source.id
                ).order_by(PredictiveOutcomeClassification.id)
            )
        ]
        print(json.dumps({
            "kind": kind, "force": force, "admission_denials": len(calls),
            "escaped_denials": len(errors), "evidence_unchanged": after_rows == before_rows,
            "classification_statuses": [row["status"] for row in after_rows],
        }))
        assert len(errors) == 1
        assert calls == [source.id]
        assert _columns(source) == before_source
        assert after_rows == before_rows
        assert session.get(Statute, sibling.id) is not None
        assert list(session.scalars(
            select(ModelRun).where(ModelRun.purpose == predictive.PURPOSE)
        )) == []


@pytest.mark.parametrize("kind", ["authority", "order"])
def test_deterministic_predictive_classification_does_not_submit_ai(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("Deterministic classification must not submit an AI call")

    monkeypatch.setattr(predictive, "generate_structured", unexpected)
    with get_session_factory()() as session:
        source, classify = _source(session, kind, text=_NOTICE)
        rows = classify(use_llm=True, force=True, provider=_PROVIDER)
        session.commit()
        assert rows
        assert all(row.method == "deterministic" and row.status == "classified" for row in rows)
        assert all(row.source_id == source.id and row.model_run_id is None for row in rows)


def test_retry_money_denial_retains_prior_actual_model_run_without_quarantine(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def generate(provider, *, context, messages, on_model_run, **kwargs):
        calls.append(context.metadata["source_id"])
        if len(calls) == 2:
            raise AiMoneyBudgetError(_DENIAL)
        completion = LLMCompletion(
            text="invalid JSON", provider=provider.name, model=provider.model,
            prompt_tokens=17, completion_tokens=4, latency_ms=1,
        )
        on_model_run(completion, context, messages)
        raise ValueError("invalid JSON")

    monkeypatch.setattr(predictive, "generate_structured", generate)
    with get_session_factory()() as session:
        source, classify = _source(session, "authority", text=_NO_SIGNAL)
        errors = []
        try:
            classify(use_llm=True, provider=_PROVIDER)
        except AiMoneyBudgetError as exc:
            errors.append(exc)
        session.commit()
        runs = list(session.scalars(select(ModelRun).where(ModelRun.purpose == predictive.PURPOSE)))
        assert len(errors) == 1
        assert calls == [source.id, source.id]
        assert len(runs) == 1
        assert (runs[0].prompt_tokens, runs[0].completion_tokens, runs[0].status) == (
            17, 4, "malformed_output",
        )
        assert list(session.scalars(select(PredictiveOutcomeClassification))) == []


def test_predictive_backfill_stops_and_retains_committed_batch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [
        _seed_doc(text="Notice is issued to the respondent."),
        _seed_doc(text=_NO_SIGNAL),
        _seed_doc(text=_NO_SIGNAL),
    ]
    calls = []

    def denied(*args, **kwargs):
        calls.append(kwargs["context"].metadata["source_id"])
        raise AiMoneyBudgetError(_DENIAL)

    monkeypatch.setattr(predictive, "build_provider", lambda **kwargs: _PROVIDER)
    monkeypatch.setattr(predictive, "generate_structured", denied)
    with get_session_factory()() as session:
        docs = [session.get(AuthorityDocument, item) for item in ids]
        monkeypatch.setattr(predictive, "_select_authority_documents", lambda *args, **kwargs: docs)
        errors = []
        try:
            predictive.backfill_predictive_outcomes(session, use_llm=True, batch_size=1)
        except AiMoneyBudgetError as exc:
            errors.append(exc)
        session.commit()
        rows = list(session.scalars(select(PredictiveOutcomeClassification)))
        assert len(errors) == 1
        assert calls == [ids[1]]
        assert rows and {row.source_id for row in rows} == {ids[0]}
        assert all(row.status == "classified" for row in rows)


class _DeniedProvider:
    name = "openai"
    model = "offline-statute"

    def generate(self, **kwargs):
        raise AiMoneyBudgetError(_DENIAL)


def test_statute_money_denial_does_not_commit_sibling_or_fabricate_model_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(statute, "build_provider", lambda **kwargs: _DeniedProvider())
    with get_session_factory()() as session:
        st, section = _seed_statute_and_section(session)
        before = _columns(section)
        sibling = Statute(
            id="pending-statute", short_name="Pending", long_name="Pending sibling",
            enacted_year=2026, jurisdiction="india", is_active=True,
        )
        session.add(sibling)
        with pytest.raises(AiMoneyBudgetError, match="shared AI money"):
            statute.model_generate_section_text(session, st, section)
        assert sibling in session.new
        assert session.in_transaction()
        assert _columns(section) == before
        with session.no_autoflush:
            assert list(session.scalars(select(ModelRun))) == []
        session.commit()
    with get_session_factory()() as session:
        assert session.get(Statute, "pending-statute") is not None


@pytest.mark.parametrize(
    "status", ["verified_official", "verified_licensed", "quarantined", "retired"],
)
def test_statute_reviewed_source_is_preserved_without_model_admission(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, status: str,
) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("Reviewed or terminal source cannot enter model admission")

    monkeypatch.setattr(statute, "build_provider", unexpected)
    monkeypatch.setattr(statute, "scrape_indiacode_section", unexpected)
    with get_session_factory()() as session:
        st, section = _seed_statute_and_section(session)
        section.verification_status = status
        section.section_text = "Retained reviewed source text."
        session.commit()
        before = _columns(section)
        result = statute.enrich_section(session, section, statute=st)
        session.commit()
        assert result.notes == "reviewed_or_terminal_source_preserved"
        assert _columns(section) == before


@pytest.mark.parametrize("outcome", ["provider_error", "refusal"])
def test_ordinary_statute_provider_error_and_refusal_keep_original_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    class Provider:
        def generate(self, **kwargs):
            if outcome == "provider_error":
                raise LLMProviderError("Offline provider unavailable")
            return LLMCompletion(
                text="UNAVAILABLE", provider="mock", model="offline-statute",
                prompt_tokens=7, completion_tokens=1, latency_ms=1,
            )

    monkeypatch.setattr(statute, "build_provider", lambda **kwargs: Provider())
    with get_session_factory()() as session:
        st, section = _seed_statute_and_section(session)
        text, status = statute.model_generate_section_text(session, st, section)
        runs = list(session.scalars(select(ModelRun)))
        assert text is None
        if outcome == "provider_error":
            assert status.startswith("provider_error:")
        else:
            assert status == "model_refused"
        assert len(runs) == 1
        assert runs[0].status == ("provider_error" if outcome == "provider_error" else "ok")
        assert section.section_text is None and section.ai_explanation is None


def test_statute_driver_stops_without_counting_denial_as_corrupt_content(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    with get_session_factory()() as session:
        st, first = _seed_statute_and_section(session, sid="a-money-stop", sec_no="1")
        sections = [first]
        for ordinal in [2, 3]:
            sec = StatuteSection(
                statute_id=st.id, section_number=str(ordinal), ordinal=ordinal, is_active=True,
            )
            session.add(sec)
            sections.append(sec)
        later, later_section = _seed_statute_and_section(session, sid="z-money-stop", sec_no="1")
        session.commit()
        ids = [sec.id for sec in sections] + [later_section.id]
    scraped = []
    admissions = []

    def scrape(st, sec, **kwargs):
        scraped.append(sec.id)
        return "An official candidate still needs source review. " * 3 if sec.id == ids[0] else None

    class Provider:
        def generate(self, **kwargs):
            admissions.append(True)
            raise AiMoneyBudgetError(_DENIAL)

    monkeypatch.setattr(statute, "scrape_indiacode_section", scrape)
    monkeypatch.setattr(statute, "build_provider", lambda **kwargs: Provider())
    rc = statute_cli.run(
        statute_filter=["a-money-stop", "z-money-stop"], budget_usd=5,
        allow_model_fallback=True, dry_run=False, limit_per_statute=None,
    )
    output = capsys.readouterr()
    total = next(line.split() for line in output.out.splitlines() if line.startswith("TOTAL"))
    print(json.dumps({
        "driver": "statute", "exit_code": rc, "admission_denials": len(admissions),
        "scrape_attempts": len(scraped), "summary": output.out, "stop": output.err,
    }))
    assert rc != 0
    assert admissions == [True]
    assert scraped == ids[:2]
    assert "shared_ai_budget" in output.out + output.err
    assert "budget_blocked" in output.out
    assert total == ["TOTAL", "1", "0", "0", "0", "1"]
    with get_session_factory()() as session:
        first = session.get(StatuteSection, ids[0])
        assert first.section_text is not None and first.verification_status == "unverified"
        assert first.source_status == "official_candidate" and first.is_provisional
        for sec_id in ids[1:]:
            sec = session.get(StatuteSection, sec_id)
            assert sec.section_text is None and sec.ai_explanation is None
            assert sec.verification_status == "unverified"
        assert list(session.scalars(select(ModelRun))) == []


@pytest.mark.parametrize("driver", ["predictive", "statute"])
def test_native_cli_money_denial_has_nonzero_exit(
    client: TestClient, driver: str,
) -> None:
    if driver == "predictive":
        _seed_doc(text=_NO_SIGNAL, court_name="CLI money stop")
        module = "caseops_api.scripts.backfill_predictive_outcomes"
        argv = ["--use-llm", "--court-name", "CLI money stop"]
    else:
        with get_session_factory()() as session:
            _seed_statute_and_section(session, sid="cli-money-stop")
        module = "caseops_api.scripts.enrich_statute_sections"
        argv = ["--statute", "cli-money-stop"]
    api = Path(__file__).resolve().parents[1]
    code = f"""
import sys
sys.path[:0] = {json.dumps([str(api / 'src'), sysconfig.get_path('purelib')])}
import runpy, socket
from types import SimpleNamespace
from caseops_api.services import predictive_outcomes as p, statute_enrichment as s
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
def blocked(*args, **kwargs):
    raise AssertionError('External network is forbidden in the CLI fixture')
socket.socket.connect = blocked
def denied(*args, **kwargs):
    print('OFFLINE_ADMISSION_DENIED', flush=True)
    raise AiMoneyBudgetError({_DENIAL!r})
p.build_provider = lambda **kwargs: SimpleNamespace(name='mock', model='offline')
p.generate_structured = denied
s.build_provider = lambda **kwargs: SimpleNamespace(generate=denied)
s.scrape_indiacode_section = lambda *args, **kwargs: None
sys.argv = {[module, *argv]!r}
runpy.run_module({module!r}, run_name='__main__')
"""
    result = subprocess.run(
        [sys._base_executable, "-c", code], cwd=api, env=os.environ.copy(),
        capture_output=True, text=True, timeout=30, check=False,
    )
    print(json.dumps({
        "driver": driver, "exit_code": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr,
    }))
    assert result.returncode == 1, result.stdout
    assert result.stdout.count("OFFLINE_ADMISSION_DENIED") == 1
    streams = result.stdout + result.stderr
    assert "shared AI money" in streams or "shared_ai_budget" in streams
    assert "ModuleNotFoundError" not in result.stderr
