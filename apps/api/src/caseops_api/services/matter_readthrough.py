"""Bounded reads of stored decision support; no generation, workflow or provider calls.

All source rows remain authoritative. SQL projections read at most prefix+1
codepoints per text field; an unsupported result is explicit, never truncated
into a purported complete value. Child identities remain in their page even
when their stored content is too large or malformed for this read surface.
"""

import json
from datetime import datetime

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import LargeBinary, and_, cast, exists, func, literal, or_, select, tuple_
from sqlalchemy.orm import aliased

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    HearingPack,
    HearingPackItem,
    Matter,
    MatterHearing,
    MembershipRole,
    Recommendation,
    RecommendationDecision,
    RecommendationOption,
    User,
)
from caseops_api.db.statement_clock import StatementUtc
from caseops_api.schemas.litigation_strategy import LitigationStrategyPayload
from caseops_api.schemas.matter_readthrough import (
    HearingPackContent,
    HearingPackItemContent,
    HearingPackItemPage,
    HearingPackItemRead,
    HearingPackRead,
    MatterReadScope,
    RecommendationContent,
    RecommendationDecisionContent,
    RecommendationDecisionPage,
    RecommendationDecisionRead,
    RecommendationDetail,
    RecommendationMetadata,
    RecommendationOptionContent,
    RecommendationOptionPage,
    RecommendationOptionRead,
    RecommendationPage,
    RecommendationSummary,
)
from caseops_api.schemas.recommendations import RecommendationAnalysisRecord
from caseops_api.services.matter_readthrough_cursor import (
    decode_cursor,
    encode_cursor,
    record_id,
    utc,
)
from caseops_api.services.record_access_policy import visible_matters_filter

TEXT_CHARS = 16_384
CHILD_ROW_BYTES = 32_768
DETAIL_BYTES = 262_144
RESPONSE_BYTES = 1_048_576


class _Unsupported(ValueError):
    def __init__(self, state):
        self.state = state


def _problem(status, code, message):
    raise HTTPException(status, detail={"code": code, "message": message})


def _actor(context):
    member = aliased(CompanyMembership, name="readthrough_actor")
    user = aliased(User, name="readthrough_actor_user")
    return exists(
        select(member.id)
        .join(user, user.id == member.user_id)
        .join(Company, Company.id == member.company_id)
        .where(
            member.id == context.membership.id,
            member.company_id == context.company.id,
            member.user_id == context.user.id,
            member.role == context.membership.role,
            member.role.in_([role.value for role in MembershipRole]),
            member.is_active.is_(True),
            user.is_active.is_(True),
            Company.is_active.is_(True),
        )
    )


def _require_actor(session, context):
    if not session.scalar(select(_actor(context))):
        _problem(
            403, "matter_read_authority_changed", "Account access changed. Reload your account."
        )


def _policy(session, context, matter_id, lifecycle=None):
    predicates = [
        Matter.id == matter_id,
        Matter.company_id == context.company.id,
        _actor(context),
        visible_matters_filter(session, context=context, statement_time=StatementUtc()),
    ]
    if lifecycle is not None:
        predicates.append(Matter.lifecycle_version == lifecycle)
    return and_(*predicates)


def _scope(session, context, matter_id):
    record_id(matter_id)
    _require_actor(session, context)
    row = (
        session.execute(
            select(
                Matter.id,
                *_prefix(session, Matter.status, 24),
                Matter.is_active,
                Matter.lifecycle_version,
            )
            .where(_policy(session, context, matter_id))
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        _require_actor(session, context)
        _problem(404, "matter_read_not_found", "Matter not found.")
    try:
        status = _text(row, "status", 24)
    except _Unsupported:
        _problem(
            409, "matter_read_unavailable", "This retained Matter state cannot be displayed safely."
        )
    return MatterReadScope(
        company_id=context.company.id,
        matter_id=row["id"],
        matter_status=status,
        matter_is_active=row["is_active"],
        matter_lifecycle_version=row["lifecycle_version"],
    )


def _matter_exists(session, context, scope):
    return exists(
        select(Matter.id).where(
            _policy(session, context, scope.matter_id, scope.matter_lifecycle_version)
        )
    )


def _after(session, context, scope):
    current = _scope(session, context, scope.matter_id)
    if current != scope:
        _problem(409, "matter_read_changed", "Matter changed. Reload this read view.")


def _prefix(session, column, maximum=TEXT_CHARS):
    # SQLite text substr stops at NUL. Keep the original UTF-8 extent in the
    # same scalar read so that loss cannot be presented as complete content.
    size = (
        func.length(cast(column, LargeBinary))
        if session.get_bind().dialect.name == "sqlite"
        else func.octet_length(column)
    )
    return (
        func.substr(column, 1, maximum + 1).label(column.key),
        size.label(column.key + "_source_bytes"),
    )


def _text(row, name, maximum=TEXT_CHARS, nullable=False):
    value = row[name]
    if value is None and nullable:
        return None
    if type(value) is not str:
        raise _Unsupported("unsupported_legacy")
    if len(value) > maximum:
        raise _Unsupported("unsupported_size")
    try:
        encoded_size = len(value.encode("utf-8", "strict"))
    except UnicodeError as exc:
        raise _Unsupported("unsupported_legacy") from exc
    size = row[name + "_source_bytes"]
    if type(size) is not int or size != encoded_size:
        raise _Unsupported("unsupported_legacy")
    return value


def _strings(row, name):
    raw = _text(row, name)
    try:
        value = json.loads(raw)
    except ValueError as exc:
        # The standard parser also refuses overly long integer tokens with a
        # plain ValueError. Preserve the bounded-text classification above.
        raise _Unsupported("unsupported_legacy") from exc
    if type(value) is not list or any(type(item) is not str for item in value):
        raise _Unsupported("unsupported_legacy")
    return value


def _optional_model(row, name, model):
    raw = _text(row, name, nullable=True)
    if raw is None or raw == "":
        return None
    try:
        return model.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise _Unsupported("unsupported_legacy") from exc


def _read(model, identity, payload, byte_limit):
    try:
        record = payload()
        result = model(**identity, read_state="available", record=record)
        if len(result.model_dump_json().encode("utf-8")) > byte_limit:
            raise _Unsupported("unsupported_size")
        return result
    except (_Unsupported, ValidationError) as exc:
        state = exc.state if isinstance(exc, _Unsupported) else "unsupported_legacy"
        # No source row is omitted and no incomplete value is represented as complete.
        return model(**identity, read_state=state, record=None)


def _recommendation_statement(session, context, scope, *, detail=False):
    columns = [
        Recommendation.id,
        Recommendation.created_at,
        Recommendation.updated_at,
        *_prefix(session, Recommendation.type, 40),
        *_prefix(session, Recommendation.title, 400),
        *_prefix(session, Recommendation.confidence, 16),
        Recommendation.review_required,
        *_prefix(session, Recommendation.status, 24),
    ]
    if detail:
        columns.append(Recommendation.primary_option_index)
        for name in (
            "rationale",
            "assumptions_json",
            "missing_facts_json",
            "next_action",
            "retrieved_authorities_json",
            "strategy_payload_json",
            "analysis_json",
        ):
            columns.extend(_prefix(session, getattr(Recommendation, name)))
    return select(*columns).where(
        Recommendation.company_id == context.company.id,
        Recommendation.matter_id == scope.matter_id,
        Recommendation.type != literal("intelligent_review", literal_execute=True),
        _matter_exists(session, context, scope),
    )


def _recommendation_exists(session, context, scope, recommendation_id, foreign_id=None):
    return exists(
        select(Recommendation.id).where(
            Recommendation.id == (foreign_id if foreign_id is not None else recommendation_id),
            Recommendation.id == recommendation_id,
            Recommendation.company_id == context.company.id,
            Recommendation.matter_id == scope.matter_id,
            Recommendation.type != literal("intelligent_review", literal_execute=True),
            _matter_exists(session, context, scope),
        )
    )


def _require_recommendation(session, context, scope, recommendation_id):
    record_id(recommendation_id)
    if not session.scalar(
        select(_recommendation_exists(session, context, scope, recommendation_id))
    ):
        _after(session, context, scope)
        _problem(404, "matter_read_not_found", "Recommendation not found.")


def _metadata(row):
    return dict(
        type=_text(row, "type", 40),
        title=_text(row, "title", 400),
        confidence=_text(row, "confidence", 16),
        review_required=row["review_required"],
        status=_text(row, "status", 24),
    )


def _recommendation_summary(row):
    return _read(
        RecommendationSummary,
        {
            "id": row["id"],
            "created_at": utc(row["created_at"]),
            "updated_at": utc(row["updated_at"]),
        },
        lambda: RecommendationMetadata(**_metadata(row)),
        CHILD_ROW_BYTES,
    )


def get_recommendation(session, *, context, matter_id, recommendation_id):
    scope = _scope(session, context, matter_id)
    record_id(recommendation_id)
    row = (
        session.execute(
            _recommendation_statement(session, context, scope, detail=True)
            .where(Recommendation.id == recommendation_id)
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    _after(session, context, scope)
    if row is None:
        _problem(404, "matter_read_not_found", "Recommendation not found.")
    return _read(
        RecommendationDetail,
        {
            "id": row["id"],
            "scope": scope,
            "created_at": utc(row["created_at"]),
            "updated_at": utc(row["updated_at"]),
        },
        lambda: RecommendationContent(
            **_metadata(row),
            rationale=_text(row, "rationale"),
            primary_option_index=row["primary_option_index"],
            assumptions=_strings(row, "assumptions_json"),
            missing_facts=_strings(row, "missing_facts_json"),
            next_action=_text(row, "next_action", nullable=True),
            retrieved_authorities=_strings(row, "retrieved_authorities_json"),
            strategy_payload=_optional_model(
                row, "strategy_payload_json", LitigationStrategyPayload
            ),
            analysis=_optional_model(row, "analysis_json", RecommendationAnalysisRecord),
        ),
        DETAIL_BYTES,
    )


def _page(
    session,
    context,
    scope,
    *,
    kind,
    parent_id,
    model,
    statement,
    key,
    ascending,
    response_model,
    make_row,
    limit,
    cursor,
):
    if type(limit) is not int or not 1 <= limit <= 25:
        _problem(422, "matter_read_limit_invalid", "Read limits are between 1 and 25.")
    if cursor is not None:
        anchor = decode_cursor(cursor, context, scope, kind, parent_id, limit)
        current = (
            session.execute(
                statement.with_only_columns(model.id, key, maintain_column_froms=True)
                .where(model.id == anchor["id"])
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        anchor_key = anchor["key"]
        if key.type.python_type is datetime:
            anchor_key = datetime.fromisoformat(anchor_key)
        current_key = current[key.key] if current is not None else None
        if isinstance(current_key, datetime):
            current_key = utc(current_key).isoformat(timespec="microseconds")
        if current is None or current_key != anchor["key"]:
            _after(session, context, scope)
            _problem(409, "matter_read_cursor_stale", "Source changed. Reload the first page.")
        pair = tuple_(key, model.id)
        statement = statement.where(
            pair > tuple_(anchor_key, anchor["id"])
            if ascending
            else pair < tuple_(anchor_key, anchor["id"])
        )
    rows = list(
        session.execute(
            statement.order_by(
                key.asc() if ascending else key.desc(),
                model.id.asc() if ascending else model.id.desc(),
            ).limit(limit + 1)
        ).mappings()
    )
    _after(session, context, scope)
    kept = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = kept[-1]
        value = last[key.key]
        if isinstance(value, datetime):
            value = utc(value).isoformat(timespec="microseconds")
        next_cursor = encode_cursor(context, scope, kind, parent_id, limit, last["id"], value)
    page = response_model(
        scope=scope,
        parent_id=parent_id,
        limit=limit,
        order=(key.key + "_asc_id_asc" if ascending else key.key + "_desc_id_desc"),
        items=[make_row(row) for row in kept],
        next_cursor=next_cursor,
    )
    if len(page.model_dump_json().encode("utf-8")) > RESPONSE_BYTES:
        _problem(409, "matter_read_unavailable", "This retained read cannot be displayed safely.")
    return page


def list_recommendations(session, *, context, matter_id, limit=25, cursor=None):
    scope = _scope(session, context, matter_id)
    return _page(
        session,
        context,
        scope,
        kind="recommendations",
        parent_id=None,
        model=Recommendation,
        statement=_recommendation_statement(session, context, scope),
        key=Recommendation.created_at,
        ascending=False,
        response_model=RecommendationPage,
        make_row=_recommendation_summary,
        limit=limit,
        cursor=cursor,
    )


def list_options(session, *, context, matter_id, recommendation_id, limit=25, cursor=None):
    scope = _scope(session, context, matter_id)
    _require_recommendation(session, context, scope, recommendation_id)
    statement = select(
        RecommendationOption.id,
        RecommendationOption.rank,
        *_prefix(session, RecommendationOption.label, 400),
        *_prefix(session, RecommendationOption.confidence, 16),
        *_prefix(session, RecommendationOption.rationale),
        *_prefix(session, RecommendationOption.supporting_citations_json),
        *_prefix(session, RecommendationOption.risk_notes),
    ).where(
        RecommendationOption.recommendation_id == recommendation_id,
        _recommendation_exists(
            session, context, scope, recommendation_id, RecommendationOption.recommendation_id
        ),
    )

    def row(value):
        return _read(
            RecommendationOptionRead,
            {"id": value["id"], "rank": value["rank"]},
            lambda: RecommendationOptionContent(
                label=_text(value, "label", 400),
                confidence=_text(value, "confidence", 16),
                rationale=_text(value, "rationale"),
                supporting_citations=_strings(value, "supporting_citations_json"),
                risk_notes=_text(value, "risk_notes", nullable=True),
            ),
            CHILD_ROW_BYTES,
        )

    page = _page(
        session,
        context,
        scope,
        kind="recommendation_options",
        parent_id=recommendation_id,
        model=RecommendationOption,
        statement=statement,
        key=RecommendationOption.rank,
        ascending=True,
        response_model=RecommendationOptionPage,
        make_row=row,
        limit=limit,
        cursor=cursor,
    )
    _require_recommendation(session, context, scope, recommendation_id)
    return page


def list_decisions(session, *, context, matter_id, recommendation_id, limit=25, cursor=None):
    scope = _scope(session, context, matter_id)
    _require_recommendation(session, context, scope, recommendation_id)
    statement = select(
        RecommendationDecision.id,
        RecommendationDecision.created_at,
        *_prefix(session, RecommendationDecision.actor_membership_id, 36),
        RecommendationDecision.selected_option_index,
        *_prefix(session, RecommendationDecision.decision, 24),
        *_prefix(session, RecommendationDecision.notes),
    ).where(
        RecommendationDecision.recommendation_id == recommendation_id,
        _recommendation_exists(
            session, context, scope, recommendation_id, RecommendationDecision.recommendation_id
        ),
    )

    def row(value):
        return _read(
            RecommendationDecisionRead,
            {"id": value["id"], "created_at": utc(value["created_at"])},
            lambda: RecommendationDecisionContent(
                actor_membership_id=_text(value, "actor_membership_id", 36, nullable=True),
                selected_option_index=value["selected_option_index"],
                decision=_text(value, "decision", 24),
                notes=_text(value, "notes", nullable=True),
            ),
            CHILD_ROW_BYTES,
        )

    page = _page(
        session,
        context,
        scope,
        kind="recommendation_decisions",
        parent_id=recommendation_id,
        model=RecommendationDecision,
        statement=statement,
        key=RecommendationDecision.created_at,
        ascending=False,
        response_model=RecommendationDecisionPage,
        make_row=row,
        limit=limit,
        cursor=cursor,
    )
    _require_recommendation(session, context, scope, recommendation_id)
    return page


def _pack_statement(session, context, scope):
    return select(
        HearingPack.id,
        HearingPack.hearing_id,
        HearingPack.generated_at,
        HearingPack.reviewed_at,
        *_prefix(session, HearingPack.generated_by_membership_id, 36),
        *_prefix(session, HearingPack.reviewed_by_membership_id, 36),
        *_prefix(session, HearingPack.model_run_id, 36),
        *_prefix(session, HearingPack.status, 24),
        HearingPack.review_required,
        *_prefix(session, HearingPack.summary),
    ).where(
        HearingPack.matter_id == scope.matter_id,
        _matter_exists(session, context, scope),
        or_(
            HearingPack.hearing_id.is_(None),
            exists(
                select(MatterHearing.id).where(
                    MatterHearing.id == HearingPack.hearing_id,
                    MatterHearing.matter_id == scope.matter_id,
                )
            ),
        ),
    )


def _pack_row(row, scope):
    return _read(
        HearingPackRead,
        {
            "id": row["id"],
            "scope": scope,
            "hearing_id": row["hearing_id"],
            "generated_at": utc(row["generated_at"]),
            "reviewed_at": utc(row["reviewed_at"]) if row["reviewed_at"] else None,
        },
        lambda: HearingPackContent(
            generated_by_membership_id=_text(row, "generated_by_membership_id", 36, nullable=True),
            reviewed_by_membership_id=_text(row, "reviewed_by_membership_id", 36, nullable=True),
            model_run_id=_text(row, "model_run_id", 36, nullable=True),
            status=_text(row, "status", 24),
            summary=_text(row, "summary"),
            review_required=row["review_required"],
        ),
        DETAIL_BYTES,
    )


def get_latest_pack(session, *, context, matter_id, hearing_id):
    scope = _scope(session, context, matter_id)
    record_id(hearing_id)
    hearing = session.scalar(
        select(MatterHearing.id)
        .where(
            MatterHearing.id == hearing_id,
            MatterHearing.matter_id == matter_id,
            _matter_exists(session, context, scope),
        )
        .limit(1)
    )
    if hearing is None:
        _after(session, context, scope)
        _problem(404, "matter_read_not_found", "Hearing not found.")
    row = (
        session.execute(
            _pack_statement(session, context, scope)
            .where(HearingPack.hearing_id == hearing_id)
            .order_by(HearingPack.generated_at.desc(), HearingPack.id.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    _after(session, context, scope)
    return _pack_row(row, scope) if row is not None else None


def get_pack(session, *, context, matter_id, pack_id):
    scope = _scope(session, context, matter_id)
    record_id(pack_id)
    row = (
        session.execute(
            _pack_statement(session, context, scope).where(HearingPack.id == pack_id).limit(1)
        )
        .mappings()
        .one_or_none()
    )
    _after(session, context, scope)
    if row is None:
        _problem(404, "matter_read_not_found", "Hearing pack not found.")
    return _pack_row(row, scope)


def list_pack_items(session, *, context, matter_id, pack_id, limit=25, cursor=None):
    scope = _scope(session, context, matter_id)
    record_id(pack_id)
    parent = _pack_statement(session, context, scope).with_only_columns(
        HearingPack.id, maintain_column_froms=True
    )
    if not session.scalar(parent.where(HearingPack.id == pack_id).limit(1)):
        _after(session, context, scope)
        _problem(404, "matter_read_not_found", "Hearing pack not found.")
    statement = select(
        HearingPackItem.id,
        HearingPackItem.rank,
        HearingPackItem.created_at,
        *_prefix(session, HearingPackItem.item_type, 40),
        *_prefix(session, HearingPackItem.title, 255),
        *_prefix(session, HearingPackItem.body),
        *_prefix(session, HearingPackItem.source_ref, 500),
    ).where(
        HearingPackItem.pack_id == pack_id,
        exists(parent.where(HearingPack.id == HearingPackItem.pack_id, HearingPack.id == pack_id)),
    )

    def row(value):
        return _read(
            HearingPackItemRead,
            {"id": value["id"], "rank": value["rank"], "created_at": utc(value["created_at"])},
            lambda: HearingPackItemContent(
                item_type=_text(value, "item_type", 40),
                title=_text(value, "title", 255),
                body=_text(value, "body"),
                source_ref=_text(value, "source_ref", 500, nullable=True),
            ),
            CHILD_ROW_BYTES,
        )

    page = _page(
        session,
        context,
        scope,
        kind="hearing_pack_items",
        parent_id=pack_id,
        model=HearingPackItem,
        statement=statement,
        key=HearingPackItem.rank,
        ascending=True,
        response_model=HearingPackItemPage,
        make_row=row,
        limit=limit,
        cursor=cursor,
    )
    if not session.scalar(parent.where(HearingPack.id == pack_id).limit(1)):
        _after(session, context, scope)
        _problem(404, "matter_read_not_found", "Hearing pack not found.")
    return page
