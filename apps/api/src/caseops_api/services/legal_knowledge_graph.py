from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, replace

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AffidavitQuestion,
    AffidavitStatement,
    LegalKnowledgeGraphEdge,
    LegalKnowledgeGraphNode,
    LegalKnowledgeGraphRun,
    LitigationIntelligenceReviewAction,
    Matter,
    MatterCourtOrder,
    MatterProceedingSignal,
    MockHearingQuestion,
    MockHearingResponse,
    PredictiveSignalEvidence,
    PredictiveSignalItem,
    PredictiveSignalRun,
    utcnow,
)
from caseops_api.schemas.legal_knowledge_graph import (
    LegalKnowledgeGraphEdgeRecord,
    LegalKnowledgeGraphNodeRecord,
    LegalKnowledgeGraphResponse,
    LegalKnowledgeGraphSummary,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access

DISCLAIMER = (
    "Legal knowledge graph materialization is source-backed decision support, "
    "not legal advice. Verify source records before relying on relationships."
)
LIMITATION_NOTE = (
    "LI-S11 materializes a matter-scoped graph from existing CaseOps litigation "
    "intelligence records only. It does not run corpus ingest, scrape external "
    "sources, create predictions, or infer uncited legal conclusions."
)
NO_SOURCE_LIMITATION = (
    "No source-backed LI records are available for graph materialization. Run "
    "proceeding, affidavit, mock-hearing, predictive, or review workflows first."
)
SOURCE_SNIPPET_LIMIT = 700
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")


@dataclass(frozen=True)
class _NodeSpec:
    node_key: str
    node_type: str
    label: str
    source_type: str
    source_id: str
    description: str | None = None
    source_quote: str | None = None
    confidence_label: str | None = None
    review_status: str | None = None
    limitation_note: str = LIMITATION_NOTE


@dataclass(frozen=True)
class _EdgeSpec:
    from_key: str
    to_key: str
    edge_type: str
    label: str
    source_type: str
    source_id: str
    source_quote: str | None = None
    confidence_label: str | None = None
    limitation_note: str = LIMITATION_NOTE


class _GraphBuilder:
    def __init__(self, matter: Matter) -> None:
        self.matter = matter
        self.nodes: dict[str, _NodeSpec] = {}
        self.edges: dict[tuple[str, str, str, str, str], _EdgeSpec] = {}

    def add_node(self, spec: _NodeSpec) -> None:
        spec = replace(spec, source_quote=_source_snippet(spec.source_quote))
        if spec.node_key not in self.nodes:
            self.nodes[spec.node_key] = spec

    def add_edge(self, spec: _EdgeSpec) -> None:
        spec = replace(spec, source_quote=_source_snippet(spec.source_quote))
        if spec.from_key not in self.nodes or spec.to_key not in self.nodes:
            return
        key = (
            spec.from_key,
            spec.to_key,
            spec.edge_type,
            spec.source_type,
            spec.source_id,
        )
        self.edges.setdefault(key, spec)


def get_legal_knowledge_graph(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> LegalKnowledgeGraphResponse:
    matter = _load_visible_matter(session, context=context, matter_id=matter_id)
    run = _latest_run(session, matter)
    record_from_context(
        session,
        context,
        action="legal_knowledge_graph.viewed",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={"run_id": run.id if run else None},
    )
    session.commit()
    return _response_from_run(matter, run)


def materialize_legal_knowledge_graph(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> LegalKnowledgeGraphResponse:
    matter = _load_visible_matter(session, context=context, matter_id=matter_id)
    run = _latest_run(session, matter)
    now = utcnow()
    if run is None:
        run = LegalKnowledgeGraphRun(
            company_id=matter.company_id,
            matter_id=matter.id,
            created_by_membership_id=context.membership.id,
            status="no_source_records",
            limitation_note=LIMITATION_NOTE,
            disclaimer=DISCLAIMER,
            created_at=now,
            updated_at=now,
        )
        session.add(run)
        session.flush()
    else:
        run.created_by_membership_id = context.membership.id
        run.updated_at = now
        session.execute(
            delete(LegalKnowledgeGraphEdge).where(
                LegalKnowledgeGraphEdge.run_id == run.id,
                LegalKnowledgeGraphEdge.company_id == matter.company_id,
                LegalKnowledgeGraphEdge.matter_id == matter.id,
            )
        )
        session.execute(
            delete(LegalKnowledgeGraphNode).where(
                LegalKnowledgeGraphNode.run_id == run.id,
                LegalKnowledgeGraphNode.company_id == matter.company_id,
                LegalKnowledgeGraphNode.matter_id == matter.id,
            )
        )
        session.flush()

    builder = _build_graph_specs(session, matter)
    node_rows: dict[str, LegalKnowledgeGraphNode] = {}
    for spec in builder.nodes.values():
        row = LegalKnowledgeGraphNode(
            run_id=run.id,
            company_id=matter.company_id,
            matter_id=matter.id,
            node_key=spec.node_key,
            node_type=spec.node_type,
            label=spec.label,
            description=spec.description,
            source_type=spec.source_type,
            source_id=spec.source_id,
            source_quote=_source_snippet(spec.source_quote),
            confidence_label=spec.confidence_label,
            review_status=spec.review_status,
            limitation_note=spec.limitation_note,
            created_at=now,
        )
        session.add(row)
        node_rows[spec.node_key] = row
    session.flush()

    edge_count = 0
    for spec in builder.edges.values():
        from_node = node_rows.get(spec.from_key)
        to_node = node_rows.get(spec.to_key)
        if from_node is None or to_node is None:
            continue
        session.add(
            LegalKnowledgeGraphEdge(
                run_id=run.id,
                company_id=matter.company_id,
                matter_id=matter.id,
                from_node_id=from_node.id,
                to_node_id=to_node.id,
                edge_type=spec.edge_type,
                label=spec.label,
                source_type=spec.source_type,
                source_id=spec.source_id,
                source_quote=_source_snippet(spec.source_quote),
                confidence_label=spec.confidence_label,
                limitation_note=spec.limitation_note,
                created_at=now,
            )
        )
        edge_count += 1

    source_record_count = sum(1 for key in builder.nodes if key != _matter_key(matter.id))
    run.source_record_count = source_record_count
    run.node_count = len(builder.nodes)
    run.edge_count = edge_count
    run.status = "completed" if source_record_count > 0 else "no_source_records"
    run.missing_data_json = (
        "[]" if source_record_count > 0 else json.dumps(["source_backed_li_records"])
    )
    run.limitation_note = LIMITATION_NOTE if source_record_count > 0 else NO_SOURCE_LIMITATION
    run.disclaimer = DISCLAIMER
    run.updated_at = now

    record_from_context(
        session,
        context,
        action="legal_knowledge_graph.materialized",
        target_type="legal_knowledge_graph_run",
        target_id=run.id,
        matter_id=matter.id,
        metadata={
            "status": run.status,
            "node_count": run.node_count,
            "edge_count": run.edge_count,
            "source_record_count": run.source_record_count,
        },
    )
    session.commit()
    session.refresh(run)
    return _response_from_run(matter, run)


def _load_visible_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    return matter


def _latest_run(session: Session, matter: Matter) -> LegalKnowledgeGraphRun | None:
    return session.scalar(
        select(LegalKnowledgeGraphRun)
        .where(
            LegalKnowledgeGraphRun.company_id == matter.company_id,
            LegalKnowledgeGraphRun.matter_id == matter.id,
        )
        .order_by(LegalKnowledgeGraphRun.updated_at.desc(), LegalKnowledgeGraphRun.id.desc())
    )


def _build_graph_specs(session: Session, matter: Matter) -> _GraphBuilder:
    builder = _GraphBuilder(matter)
    builder.add_node(
        _NodeSpec(
            node_key=_matter_key(matter.id),
            node_type="matter",
            label=matter.title,
            description="Matter root for source-backed litigation intelligence relationships.",
            source_type="matter",
            source_id=matter.id,
            limitation_note="Matter root node; relationships must be source-backed.",
        )
    )
    _add_proceeding_nodes(session, matter, builder)
    _add_affidavit_nodes(session, matter, builder)
    _add_mock_hearing_nodes(session, matter, builder)
    _add_predictive_nodes(session, matter, builder)
    _add_review_action_nodes(session, matter, builder)
    return builder


def _add_proceeding_nodes(session: Session, matter: Matter, builder: _GraphBuilder) -> None:
    signals = session.scalars(
        select(MatterProceedingSignal)
        .where(
            MatterProceedingSignal.company_id == matter.company_id,
            MatterProceedingSignal.matter_id == matter.id,
        )
        .order_by(MatterProceedingSignal.created_at.asc())
    )
    for signal in signals:
        order = session.get(MatterCourtOrder, signal.court_order_id)
        if order is None or order.matter_id != matter.id:
            continue
        if not _usable_text(order.order_text) or not _usable_text(signal.source_snippet):
            continue
        order_key = _source_key("matter_court_order", order.id)
        builder.add_node(
            _NodeSpec(
                node_key=order_key,
                node_type="legal_source",
                label=order.title or "Court order",
                description=order.source_reference,
                source_type="matter_court_order",
                source_id=order.id,
                source_quote=_source_snippet(order.order_text),
                limitation_note="Raw court order text is the source for proceeding signals.",
            )
        )
        signal_key = _source_key("matter_proceeding_signal", signal.id)
        builder.add_node(
            _NodeSpec(
                node_key=signal_key,
                node_type="proceeding_signal",
                label=_title(signal.signal_type),
                description=signal.signal_text,
                source_type="matter_proceeding_signal",
                source_id=signal.id,
                source_quote=_source_snippet(signal.source_snippet),
                confidence_label=signal.confidence_label,
                review_status=signal.review_status,
                limitation_note="Proceeding signal extracted from raw order text.",
            )
        )
        builder.add_edge(
            _EdgeSpec(
                from_key=_matter_key(matter.id),
                to_key=signal_key,
                edge_type="relates_to",
                label="Matter includes proceeding signal",
                source_type="matter_proceeding_signal",
                source_id=signal.id,
                source_quote=_source_snippet(signal.source_snippet),
                confidence_label=signal.confidence_label,
            )
        )
        builder.add_edge(
            _EdgeSpec(
                from_key=signal_key,
                to_key=order_key,
                edge_type="derived_from",
                label="Extracted from source order",
                source_type="matter_court_order",
                source_id=order.id,
                source_quote=_source_snippet(signal.source_snippet),
                confidence_label=signal.confidence_label,
            )
        )


def _add_affidavit_nodes(session: Session, matter: Matter, builder: _GraphBuilder) -> None:
    statements = list(
        session.scalars(
            select(AffidavitStatement)
            .where(
                AffidavitStatement.company_id == matter.company_id,
                AffidavitStatement.matter_id == matter.id,
            )
            .order_by(AffidavitStatement.created_at.asc())
        )
    )
    for statement in statements:
        if not _usable_text(statement.source_quote):
            continue
        source_key = _affidavit_source_key(statement)
        builder.add_node(_affidavit_source_node(statement, source_key))
        statement_key = _source_key("affidavit_statement", statement.id)
        builder.add_node(
            _NodeSpec(
                node_key=statement_key,
                node_type="affidavit_statement",
                label=_title(statement.statement_type),
                description=statement.statement_text,
                source_type="affidavit_statement",
                source_id=statement.id,
                source_quote=_source_snippet(statement.source_quote),
                confidence_label=statement.confidence_label,
                review_status=statement.review_status,
                limitation_note="Affidavit statement extracted from source attachment text/chunk.",
            )
        )
        builder.add_edge(
            _EdgeSpec(
                from_key=statement_key,
                to_key=source_key,
                edge_type="derived_from",
                label="Extracted from affidavit source chunk",
                source_type="affidavit_statement",
                source_id=statement.id,
                source_quote=_source_snippet(statement.source_quote),
                confidence_label=statement.confidence_label,
            )
        )
        builder.add_edge(
            _EdgeSpec(
                from_key=_matter_key(matter.id),
                to_key=statement_key,
                edge_type="relates_to",
                label="Matter includes affidavit statement",
                source_type="affidavit_statement",
                source_id=statement.id,
                source_quote=_source_snippet(statement.source_quote),
                confidence_label=statement.confidence_label,
            )
        )
        if statement.statement_type == "contradiction":
            builder.add_edge(
                _EdgeSpec(
                    from_key=statement_key,
                    to_key=source_key,
                    edge_type="contradicts",
                    label="Contradiction flag from affidavit source",
                    source_type="affidavit_statement",
                    source_id=statement.id,
                    source_quote=_source_snippet(statement.source_quote),
                    confidence_label=statement.confidence_label,
                )
            )
        elif statement.statement_type == "evidence_gap":
            builder.add_edge(
                _EdgeSpec(
                    from_key=statement_key,
                    to_key=source_key,
                    edge_type="has_limitation",
                    label="Needs supporting source document",
                    source_type="affidavit_statement",
                    source_id=statement.id,
                    source_quote=_source_snippet(statement.source_quote),
                    confidence_label=statement.confidence_label,
                )
            )

    questions = session.scalars(
        select(AffidavitQuestion)
        .where(
            AffidavitQuestion.company_id == matter.company_id,
            AffidavitQuestion.matter_id == matter.id,
        )
        .order_by(AffidavitQuestion.created_at.asc())
    )
    for question in questions:
        if not _usable_text(question.source_quote):
            continue
        source_key = _affidavit_question_source_key(question)
        builder.add_node(_affidavit_question_source_node(question, source_key))
        question_key = _source_key("affidavit_question", question.id)
        builder.add_node(
            _NodeSpec(
                node_key=question_key,
                node_type="affidavit_question",
                label=_title(question.category),
                description=question.question_text,
                source_type="affidavit_question",
                source_id=question.id,
                source_quote=_source_snippet(question.source_quote),
                confidence_label=question.confidence_label,
                review_status=question.review_status,
                limitation_note=(
                    "Affidavit question generated from a source-backed affidavit quote."
                ),
            )
        )
        target_key = (
            _source_key("affidavit_statement", question.statement_id)
            if question.statement_id
            else source_key
        )
        builder.add_edge(
            _EdgeSpec(
                from_key=question_key,
                to_key=target_key,
                edge_type="prompts",
                label="Question prompts review of source-backed statement",
                source_type="affidavit_question",
                source_id=question.id,
                source_quote=_source_snippet(question.source_quote),
                confidence_label=question.confidence_label,
            )
        )
        builder.add_edge(
            _EdgeSpec(
                from_key=question_key,
                to_key=source_key,
                edge_type="derived_from",
                label="Question generated from affidavit source chunk",
                source_type="affidavit_question",
                source_id=question.id,
                source_quote=_source_snippet(question.source_quote),
                confidence_label=question.confidence_label,
            )
        )


def _add_mock_hearing_nodes(session: Session, matter: Matter, builder: _GraphBuilder) -> None:
    questions = session.scalars(
        select(MockHearingQuestion)
        .where(
            MockHearingQuestion.company_id == matter.company_id,
            MockHearingQuestion.matter_id == matter.id,
        )
        .order_by(MockHearingQuestion.created_at.asc())
    )
    for question in questions:
        if not _usable_text(question.source_quote):
            continue
        question_key = _source_key("mock_hearing_question", question.id)
        builder.add_node(
            _NodeSpec(
                node_key=question_key,
                node_type="mock_hearing_question",
                label=_title(question.category),
                description=question.question_text,
                source_type="mock_hearing_question",
                source_id=question.id,
                source_quote=_source_snippet(question.source_quote),
                confidence_label=question.difficulty_label,
                review_status=question.status,
                limitation_note=(
                    "Mock-hearing question is copied from source-backed affidavit questions."
                ),
            )
        )
        if question.source_affidavit_question_id:
            target_key = _source_key("affidavit_question", question.source_affidavit_question_id)
            builder.add_edge(
                _EdgeSpec(
                    from_key=question_key,
                    to_key=target_key,
                    edge_type="derived_from",
                    label="Mock question derived from affidavit question",
                    source_type="mock_hearing_question",
                    source_id=question.id,
                    source_quote=_source_snippet(question.source_quote),
                    confidence_label=question.difficulty_label,
                )
            )

    responses = session.scalars(
        select(MockHearingResponse)
        .where(
            MockHearingResponse.company_id == matter.company_id,
            MockHearingResponse.matter_id == matter.id,
        )
        .order_by(MockHearingResponse.created_at.asc())
    )
    for response in responses:
        if not _usable_text(response.source_quote):
            continue
        response_key = _source_key("mock_hearing_response", response.id)
        builder.add_node(
            _NodeSpec(
                node_key=response_key,
                node_type="mock_hearing_response",
                label="Mock hearing response",
                description=response.feedback_text,
                source_type="mock_hearing_response",
                source_id=response.id,
                source_quote=_source_snippet(response.source_quote),
                confidence_label=response.confidence_label,
                review_status=response.review_status,
                limitation_note=(
                    "Mock-hearing feedback uses observable typed response metrics only."
                ),
            )
        )
        question_key = _source_key("mock_hearing_question", response.question_id)
        edge_type = "contradicts" if response.contradiction_with_source else "supports"
        label = (
            "Response contradicts source statement"
            if response.contradiction_with_source
            else "Response references source-backed question"
        )
        builder.add_edge(
            _EdgeSpec(
                from_key=response_key,
                to_key=question_key,
                edge_type=edge_type,
                label=label,
                source_type="mock_hearing_response",
                source_id=response.id,
                source_quote=_source_snippet(response.source_quote),
                confidence_label=response.confidence_label,
            )
        )
        if response.unsupported_assertion_added or response.missing_document_reference:
            builder.add_edge(
                _EdgeSpec(
                    from_key=response_key,
                    to_key=question_key,
                    edge_type="has_limitation",
                    label="Response needs source support review",
                    source_type="mock_hearing_response",
                    source_id=response.id,
                    source_quote=_source_snippet(response.source_quote),
                    confidence_label=response.confidence_label,
                )
            )


def _add_predictive_nodes(session: Session, matter: Matter, builder: _GraphBuilder) -> None:
    run = session.scalar(
        select(PredictiveSignalRun)
        .where(
            PredictiveSignalRun.company_id == matter.company_id,
            PredictiveSignalRun.matter_id == matter.id,
        )
        .order_by(PredictiveSignalRun.created_at.desc(), PredictiveSignalRun.id.desc())
    )
    if run is None:
        return
    evidence_rows = list(
        session.scalars(
            select(PredictiveSignalEvidence)
            .where(
                PredictiveSignalEvidence.company_id == matter.company_id,
                PredictiveSignalEvidence.matter_id == matter.id,
                PredictiveSignalEvidence.run_id == run.id,
            )
            .order_by(
                PredictiveSignalEvidence.weight.desc(),
                PredictiveSignalEvidence.created_at.asc(),
            )
        )
    )
    if not evidence_rows:
        return
    bench_key = _source_key("predictive_signal_run", run.id)
    builder.add_node(
        _NodeSpec(
            node_key=bench_key,
            node_type="bench_context",
            label="Bench context",
            description=f"Evidence quality: {run.evidence_quality}",
            source_type="predictive_signal_run",
            source_id=run.id,
            confidence_label=run.evidence_quality,
            review_status=run.status,
            limitation_note="Bench context is derived from controlled predictive signal evidence.",
        )
    )
    for item in session.scalars(
        select(PredictiveSignalItem)
        .where(
            PredictiveSignalItem.company_id == matter.company_id,
            PredictiveSignalItem.matter_id == matter.id,
            PredictiveSignalItem.run_id == run.id,
        )
        .order_by(PredictiveSignalItem.created_at.asc())
    ):
        item_evidence = [row for row in evidence_rows if row.item_id == item.id]
        if not item_evidence:
            continue
        item_key = _source_key("predictive_signal_item", item.id)
        builder.add_node(
            _NodeSpec(
                node_key=item_key,
                node_type="predictive_signal",
                label=item.label,
                description=item.estimate_label,
                source_type="predictive_signal_item",
                source_id=item.id,
                confidence_label=item.confidence_label,
                review_status=item.status,
                limitation_note=(
                    "Predictive signal node is included only because source evidence rows "
                    "exist and are linked as legal_source nodes."
                ),
            )
        )
        builder.add_edge(
            _EdgeSpec(
                from_key=bench_key,
                to_key=item_key,
                edge_type="references",
                label="Bench context references predictive signal",
                source_type="predictive_signal_item",
                source_id=item.id,
                confidence_label=item.confidence_label,
            )
        )
        for evidence in item_evidence[:5]:
            if not _usable_text(evidence.excerpt):
                continue
            source_key = _source_key(evidence.source_type, evidence.source_id)
            builder.add_node(
                _NodeSpec(
                    node_key=source_key,
                    node_type="legal_source",
                    label=evidence.title or evidence.source_reference or evidence.source_id,
                    description=evidence.source_reference,
                    source_type=evidence.source_type,
                    source_id=evidence.source_id,
                    source_quote=_source_snippet(evidence.excerpt),
                    limitation_note=(
                        "Predictive evidence source linked to controlled signal output."
                    ),
                )
            )
            builder.add_edge(
                _EdgeSpec(
                    from_key=item_key,
                    to_key=source_key,
                    edge_type="references",
                    label="Predictive signal cites source evidence",
                    source_type=evidence.source_type,
                    source_id=evidence.source_id,
                    source_quote=_source_snippet(evidence.excerpt),
                    confidence_label=item.confidence_label,
                )
            )


def _add_review_action_nodes(session: Session, matter: Matter, builder: _GraphBuilder) -> None:
    actions = session.scalars(
        select(LitigationIntelligenceReviewAction)
        .where(
            LitigationIntelligenceReviewAction.company_id == matter.company_id,
            LitigationIntelligenceReviewAction.matter_id == matter.id,
        )
        .order_by(LitigationIntelligenceReviewAction.created_at.asc())
    )
    for action in actions:
        action_key = _source_key("litigation_intelligence_review_action", action.id)
        builder.add_node(
            _NodeSpec(
                node_key=action_key,
                node_type="review_action",
                label=f"Review action: {_title(action.action)}",
                description=f"{_title(action.status_before)} to {_title(action.status_after)}",
                source_type="litigation_intelligence_review_action",
                source_id=action.id,
                review_status=action.status_after,
                limitation_note=(
                    "Review action metadata only; reviewer notes are not graph material."
                ),
            )
        )
        target_key = _source_key(action.source_type, action.source_id)
        if target_key in builder.nodes:
            builder.add_edge(
                _EdgeSpec(
                    from_key=action_key,
                    to_key=target_key,
                    edge_type="relates_to",
                    label="Review action applies to source-backed item",
                    source_type="litigation_intelligence_review_action",
                    source_id=action.id,
                    limitation_note=(
                        "Review action relationship is metadata-only and carries no legal advice."
                    ),
                )
            )


def _response_from_run(
    matter: Matter,
    run: LegalKnowledgeGraphRun | None,
) -> LegalKnowledgeGraphResponse:
    generated_at = utcnow()
    if run is None:
        return LegalKnowledgeGraphResponse(
            matter_id=matter.id,
            generated_at=generated_at,
            run_id=None,
            disclaimer=DISCLAIMER,
            limitation_note=NO_SOURCE_LIMITATION,
            summary=LegalKnowledgeGraphSummary(
                status="not_materialized",
                source_record_count=0,
                node_count=0,
                edge_count=0,
                missing_data=["legal_knowledge_graph_materialization_run"],
            ),
            nodes=[],
            edges=[],
        )
    nodes = list(run.nodes)
    edges = list(run.edges)
    return LegalKnowledgeGraphResponse(
        matter_id=matter.id,
        generated_at=run.updated_at,
        run_id=run.id,
        disclaimer=run.disclaimer,
        limitation_note=run.limitation_note,
        summary=LegalKnowledgeGraphSummary(
            status=run.status,  # type: ignore[arg-type]
            source_record_count=run.source_record_count,
            node_count=run.node_count,
            edge_count=run.edge_count,
            by_node_type=dict(Counter(node.node_type for node in nodes)),
            by_edge_type=dict(Counter(edge.edge_type for edge in edges)),
            missing_data=_json_list(run.missing_data_json),
        ),
        nodes=[_node_record(node) for node in nodes],
        edges=[_edge_record(edge) for edge in edges],
    )


def _node_record(node: LegalKnowledgeGraphNode) -> LegalKnowledgeGraphNodeRecord:
    return LegalKnowledgeGraphNodeRecord(
        id=node.id,
        node_key=node.node_key,
        node_type=node.node_type,  # type: ignore[arg-type]
        label=node.label,
        description=node.description,
        source_type=node.source_type,  # type: ignore[arg-type]
        source_id=node.source_id,
        source_quote=_source_snippet(node.source_quote),
        confidence_label=node.confidence_label,
        review_status=node.review_status,
        limitation_note=node.limitation_note,
        created_at=node.created_at,
    )


def _edge_record(edge: LegalKnowledgeGraphEdge) -> LegalKnowledgeGraphEdgeRecord:
    return LegalKnowledgeGraphEdgeRecord(
        id=edge.id,
        edge_type=edge.edge_type,  # type: ignore[arg-type]
        label=edge.label,
        from_node_id=edge.from_node_id,
        to_node_id=edge.to_node_id,
        source_type=edge.source_type,  # type: ignore[arg-type]
        source_id=edge.source_id,
        source_quote=_source_snippet(edge.source_quote),
        confidence_label=edge.confidence_label,
        limitation_note=edge.limitation_note,
        created_at=edge.created_at,
    )


def _affidavit_source_key(statement: AffidavitStatement) -> str:
    if statement.source_chunk_id:
        return _source_key("matter_attachment_chunk", statement.source_chunk_id)
    return _source_key("matter_document", statement.attachment_id)


def _affidavit_question_source_key(question: AffidavitQuestion) -> str:
    if question.source_chunk_id:
        return _source_key("matter_attachment_chunk", question.source_chunk_id)
    return _source_key("matter_document", question.attachment_id)


def _affidavit_source_node(statement: AffidavitStatement, key: str) -> _NodeSpec:
    source_type = "matter_attachment_chunk" if statement.source_chunk_id else "matter_document"
    source_id = statement.source_chunk_id or statement.attachment_id
    return _NodeSpec(
        node_key=key,
        node_type="legal_source",
        label="Affidavit source chunk",
        description=statement.page_reference,
        source_type=source_type,
        source_id=source_id,
        source_quote=_source_snippet(statement.source_quote),
        limitation_note="Affidavit source text/chunk backing extracted statements.",
    )


def _affidavit_question_source_node(question: AffidavitQuestion, key: str) -> _NodeSpec:
    source_type = "matter_attachment_chunk" if question.source_chunk_id else "matter_document"
    source_id = question.source_chunk_id or question.attachment_id
    return _NodeSpec(
        node_key=key,
        node_type="legal_source",
        label="Affidavit question source chunk",
        description=question.page_reference,
        source_type=source_type,
        source_id=source_id,
        source_quote=_source_snippet(question.source_quote),
        limitation_note="Affidavit source text/chunk backing generated questions.",
    )


def _matter_key(matter_id: str) -> str:
    return _source_key("matter", matter_id)


def _source_key(source_type: str, source_id: str) -> str:
    return f"{source_type}:{source_id}"


def _usable_text(value: str | None) -> bool:
    return bool(value and len(value.strip()) >= 8)


def _source_snippet(value: str | None, *, limit: int = SOURCE_SNIPPET_LIMIT) -> str | None:
    if not value:
        return None
    without_controls = _CONTROL_CHAR_RE.sub(" ", value)
    normalized = " ".join(without_controls.split())
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _title(value: str) -> str:
    return value.replace("_", " ").title()


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


__all__ = [
    "get_legal_knowledge_graph",
    "materialize_legal_knowledge_graph",
]
