from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AssistantActionPreview,
    AssistantActionStatus,
    AssistantSessionStatus,
    AssistantTurn,
    AssistantTurnRole,
    IpAsset,
    IpDocketRecord,
    IpProceeding,
    Matter,
    TrademarkApplication,
)
from caseops_api.schemas.matters import MatterTaskCreateRequest, MatterUpdateRequest
from caseops_api.schemas.shared_work import IpSharedTaskCreateRequest
from caseops_api.schemas.workspace_assistant import (
    AssistantActionChangeRecord,
    AssistantActionConfirmRequest,
    AssistantActionInput,
    AssistantActionPreviewRequest,
    AssistantActionPreviewResponse,
    AssistantProposedAction,
    AssistantScopeInput,
)
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.drafting import (
    create_draft,
    create_ip_draft,
    list_ip_drafting_templates,
)
from caseops_api.services.matters import create_matter_task, update_matter
from caseops_api.services.session_context import SessionContext
from caseops_api.services.shared_work import create_ip_shared_task
from caseops_api.services.workspace_assistant import (
    _locked_assistant_policy,
    _resolve_scope_versions,
    _session_or_404,
)

ACTION_PREVIEW_TTL = timedelta(minutes=15)
WRITABLE_IP_TARGETS = frozenset(
    {"ip_docket", "ip_asset", "trademark_application", "ip_proceeding"}
)


@dataclass(frozen=True, slots=True)
class _ActionTarget:
    target_type: str
    target_id: str
    target_version: str
    target_label: str
    matter_id: str | None
    docket_id: str | None
    proceeding_id: str | None


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _preview_token(row: AssistantActionPreview) -> str:
    material = _canonical_json(
        {
            "id": row.id,
            "company_id": row.company_id,
            "session_id": row.session_id,
            "turn_id": row.turn_id,
            "proposal_id": row.proposal_id,
            "action_type": row.action_type,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "target_version": row.target_version,
            "payload_sha256": row.payload_sha256,
            "session_version": row.session_version,
            "policy_version": row.policy_version,
            "actor_membership_id": row.created_by_membership_id,
            "expires_at": _aware(row.expires_at).isoformat(),
        }
    )
    return hmac.new(
        get_settings().auth_secret.encode("utf-8"),
        material.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _problem(*, code: str, detail: str, status_code: int = 409) -> ProblemHTTPException:
    return ProblemHTTPException(status_code=status_code, problem_type=code, detail=detail)


def _proposal_or_404(
    session: Session,
    *,
    context: SessionContext,
    session_id: str,
    turn_id: str,
    proposal_id: str,
) -> AssistantProposedAction:
    turn = session.scalar(
        select(AssistantTurn).where(
            AssistantTurn.id == turn_id,
            AssistantTurn.company_id == context.company.id,
            AssistantTurn.session_id == session_id,
            AssistantTurn.role == AssistantTurnRole.ASSISTANT,
        )
    )
    if turn is None:
        raise _problem(
            code="assistant_action_proposal_not_found",
            detail="The assistant proposal is no longer available.",
            status_code=404,
        )
    raw_actions = (turn.retrieval_manifest_json or {}).get("proposed_actions", [])
    for raw in raw_actions if isinstance(raw_actions, list) else []:
        try:
            proposal = AssistantProposedAction.model_validate(raw)
        except (TypeError, ValueError):
            continue
        if proposal.proposal_id == proposal_id:
            if proposal.action_type not in {"draft", "task", "field_update"}:
                raise _problem(
                    code="assistant_action_is_read_only",
                    detail="Navigation and search actions do not require a write confirmation.",
                    status_code=422,
                )
            if (
                not proposal.requires_confirmation
                or not proposal.execution_available
                or proposal.target_type is None
                or proposal.target_id is None
                or proposal.target_version is None
            ):
                raise _problem(
                    code="assistant_action_unavailable",
                    detail=(proposal.unavailable_reason or "This proposed write is not available."),
                    status_code=422,
                )
            return proposal
    raise _problem(
        code="assistant_action_proposal_not_found",
        detail="The assistant proposal is no longer available.",
        status_code=404,
    )


def _required_capabilities(proposal: AssistantProposedAction) -> tuple[str, ...]:
    if proposal.action_type == "task":
        return ("matters:write",) if proposal.target_type == "matter" else ("ip:write",)
    if proposal.action_type == "draft":
        return (
            ("drafts:create",)
            if proposal.target_type == "matter"
            else ("drafts:create", "ip:write")
        )
    return ("matters:edit",)


def _locked_actor_context(
    session: Session,
    *,
    context: SessionContext,
    capabilities: tuple[str, ...],
) -> SessionContext:
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={context.membership.id},
    )
    actor = memberships.get(context.membership.id)
    if actor is None:
        raise HTTPException(status_code=403, detail="Active company membership is required.")
    for capability in capabilities:
        require_locked_membership_capability(session, actor, capability)
    return SessionContext(
        company=context.company,
        user=actor.user,
        membership=actor,
        token_issued_at=context.token_issued_at,
    )


def _resolve_target(
    session: Session,
    *,
    context: SessionContext,
    proposal: AssistantProposedAction,
) -> _ActionTarget:
    assert proposal.target_type is not None
    assert proposal.target_id is not None
    assert proposal.target_version is not None
    resolved = _resolve_scope_versions(
        session,
        context=context,
        scopes=[
            AssistantScopeInput(
                scope_type=proposal.target_type,  # type: ignore[arg-type]
                scope_id=proposal.target_id,
            )
        ],
        strict=True,
    )
    current_version = resolved.get((proposal.target_type, proposal.target_id))
    if current_version is None or str(current_version) != proposal.target_version:
        raise _problem(
            code="assistant_action_target_changed",
            detail="The proposed target changed. Ask again before previewing this write.",
        )

    matter_id: str | None = None
    docket_id: str | None = None
    proceeding_id: str | None = None
    if proposal.target_type == "matter":
        matter = session.scalar(
            select(Matter).where(
                Matter.id == proposal.target_id,
                Matter.company_id == context.company.id,
            )
        )
        if matter is None:
            raise _problem(code="assistant_action_target_changed", detail="Matter not found.")
        matter_id = matter.id
    elif proposal.target_type in WRITABLE_IP_TARGETS:
        if proposal.target_type == "ip_docket":
            row = session.scalar(
                select(IpDocketRecord).where(
                    IpDocketRecord.id == proposal.target_id,
                    IpDocketRecord.company_id == context.company.id,
                )
            )
            docket_id = row.id if row is not None else None
        else:
            model = {
                "ip_asset": IpAsset,
                "trademark_application": TrademarkApplication,
                "ip_proceeding": IpProceeding,
            }[proposal.target_type]
            row = session.scalar(
                select(model).where(
                    model.id == proposal.target_id,
                    model.company_id == context.company.id,
                )
            )
            docket_id = row.docket_id if row is not None else None
            if proposal.target_type == "ip_proceeding" and row is not None:
                proceeding_id = row.id
        if docket_id is None:
            raise _problem(code="assistant_action_target_changed", detail="IP target not found.")
    else:
        raise _problem(
            code="assistant_action_target_unsupported",
            detail="This record type cannot receive the proposed write.",
            status_code=422,
        )
    return _ActionTarget(
        target_type=proposal.target_type,
        target_id=proposal.target_id,
        target_version=proposal.target_version,
        target_label=proposal.target_label or proposal.target_type.replace("_", " ").title(),
        matter_id=matter_id,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
    )


def _title(value: str | None, *, fallback: str | None) -> str:
    clean = " ".join((value or fallback or "").split()).strip()
    if len(clean) < 3:
        raise _problem(
            code="assistant_action_input_required",
            detail="Enter a title of at least three characters before previewing.",
            status_code=422,
        )
    return clean[:255]


def _str_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _preview_material(
    session: Session,
    *,
    context: SessionContext,
    proposal: AssistantProposedAction,
    target: _ActionTarget,
    action_input: AssistantActionInput,
    required_capabilities: tuple[str, ...],
) -> dict:
    changes: list[dict[str, str | None]] = []
    warnings = [
        "Nothing is written until you confirm this exact preview.",
        "A changed session, policy, permission, target, or input invalidates this preview.",
    ]
    canonical: dict[str, object]
    if proposal.action_type == "task":
        title = _title(action_input.title, fallback=proposal.instruction)
        canonical = {
            "title": title,
            "description": action_input.description,
            "due_on": action_input.due_on.isoformat() if action_input.due_on else None,
            "priority": action_input.priority,
            "owner_membership_id": context.membership.id,
        }
        changes = [
            {"field": "Title", "before": None, "after": title},
            {"field": "Description", "before": None, "after": action_input.description},
            {"field": "Due date", "before": None, "after": canonical["due_on"]},
            {"field": "Priority", "before": None, "after": action_input.priority},
            {"field": "Owner", "before": None, "after": context.user.full_name},
        ]
        summary = f"Create one task on {target.target_label}."
    elif proposal.action_type == "draft":
        title = _title(action_input.title, fallback=proposal.instruction)
        canonical = {"title": title, "draft_type": action_input.draft_type}
        changes = [
            {"field": "Title", "before": None, "after": title},
            {"field": "Draft type", "before": None, "after": action_input.draft_type},
        ]
        if target.matter_id is None:
            if target.docket_id is None or target.proceeding_id is None:
                raise _problem(
                    code="assistant_action_target_unsupported",
                    detail="An IP draft proposal requires an explicit proceeding scope.",
                    status_code=422,
                )
            templates = list_ip_drafting_templates(
                session,
                context=context,
                docket_id=target.docket_id,
                proceeding_id=target.proceeding_id,
            )
            selected = next(
                (
                    item
                    for item in templates
                    if action_input.template_key is not None
                    and item["key"] == action_input.template_key
                ),
                templates[0] if action_input.template_key is None and templates else None,
            )
            if selected is None:
                raise _problem(
                    code="assistant_action_template_unavailable",
                    detail="No reviewed pleading template matches this proceeding.",
                    status_code=422,
                )
            canonical["template_key"] = selected["key"]
            canonical["draft_type"] = selected["draft_type"]
            changes.append(
                {"field": "Reviewed template", "before": None, "after": selected["label"]}
            )
        summary = f"Create one review-required draft on {target.target_label}."
        warnings.append("The created draft remains unapproved and cannot be filed automatically.")
    else:
        if target.matter_id is None:
            raise _problem(
                code="assistant_action_target_unsupported",
                detail="Assistant field updates are currently limited to Matter metadata.",
                status_code=422,
            )
        if action_input.field_name is None or action_input.field_value is None:
            raise _problem(
                code="assistant_action_input_required",
                detail="Choose a Matter field and enter its proposed value.",
                status_code=422,
            )
        matter = session.get(Matter, target.matter_id)
        if matter is None:
            raise _problem(code="assistant_action_target_changed", detail="Matter not found.")
        validated = MatterUpdateRequest.model_validate(
            {
                action_input.field_name: action_input.field_value,
                # The assistant proposal carries the stronger composite private
                # source version (ACL plus row version) for its stale-target
                # check. The canonical Matter writer accepts the row's native
                # optimistic-concurrency timestamp.
                "expected_updated_at": matter.updated_at.isoformat(),
            }
        )
        canonical = validated.model_dump(mode="json", exclude_unset=True)
        before = _str_value(getattr(matter, action_input.field_name))
        after = _str_value(canonical[action_input.field_name])
        changes = [
            {
                "field": action_input.field_name.replace("_", " ").title(),
                "before": before,
                "after": after,
            }
        ]
        summary = f"Update one Matter field on {target.target_label}."
        warnings.append(
            "Lifecycle status, identifiers, responsibility, access, and hearing dates are excluded."
        )

    return {
        "target_label": target.target_label,
        "summary": summary,
        "changes": changes,
        "warnings": warnings,
        "required_capabilities": list(required_capabilities),
        "instruction": proposal.instruction,
        "canonical": canonical,
    }


def _response(row: AssistantActionPreview) -> AssistantActionPreviewResponse:
    payload = row.payload_json or {}
    return AssistantActionPreviewResponse(
        preview_id=row.id,
        proposal_id=row.proposal_id,
        action_type=row.action_type,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        session_version=row.session_version,
        resulting_session_version=(
            row.session_version + 1 if row.status == AssistantActionStatus.CONFIRMED else None
        ),
        target_type=row.target_type,
        target_id=row.target_id,
        target_label=str(payload.get("target_label") or row.target_type),
        summary=str(payload.get("summary") or "Review the proposed action."),
        changes=[
            AssistantActionChangeRecord.model_validate(change)
            for change in payload.get("changes", [])
            if isinstance(change, dict)
        ],
        warnings=[str(item) for item in payload.get("warnings", [])],
        required_capabilities=[
            str(item) for item in payload.get("required_capabilities", [])
        ],
        preview_token=_preview_token(row),
        expires_at=row.expires_at,
        result_type=row.result_type,
        result_id=row.result_id,
        result_href=row.result_href,
    )


def preview_assistant_action(
    session: Session,
    *,
    context: SessionContext,
    session_id: str,
    payload: AssistantActionPreviewRequest,
) -> AssistantActionPreviewResponse:
    proposal = _proposal_or_404(
        session,
        context=context,
        session_id=session_id,
        turn_id=payload.turn_id,
        proposal_id=payload.proposal_id,
    )
    capabilities = _required_capabilities(proposal)
    context = _locked_actor_context(session, context=context, capabilities=capabilities)
    policy = _locked_assistant_policy(session, context=context)
    assistant_session = _session_or_404(
        session,
        context=context,
        session_id=session_id,
        for_update=True,
    )
    if assistant_session.status != AssistantSessionStatus.ACTIVE:
        raise _problem(code="assistant_session_archived", detail="Archived sessions are read-only.")
    if assistant_session.version != payload.expected_version:
        raise _problem(
            code="assistant_session_version_conflict",
            detail="The assistant session changed. Reload before previewing this write.",
        )
    proposal = _proposal_or_404(
        session,
        context=context,
        session_id=session_id,
        turn_id=payload.turn_id,
        proposal_id=payload.proposal_id,
    )
    target = _resolve_target(session, context=context, proposal=proposal)
    material = _preview_material(
        session,
        context=context,
        proposal=proposal,
        target=target,
        action_input=payload.input,
        required_capabilities=capabilities,
    )
    now = datetime.now(UTC)
    session.execute(
        update(AssistantActionPreview)
        .where(
            AssistantActionPreview.company_id == context.company.id,
            AssistantActionPreview.session_id == assistant_session.id,
            AssistantActionPreview.turn_id == payload.turn_id,
            AssistantActionPreview.proposal_id == payload.proposal_id,
            AssistantActionPreview.created_by_membership_id == context.membership.id,
            AssistantActionPreview.status == AssistantActionStatus.PENDING,
        )
        .values(status=AssistantActionStatus.SUPERSEDED, updated_at=now)
    )
    preview_id = str(uuid4())
    expires_at = now + ACTION_PREVIEW_TTL
    row = AssistantActionPreview(
        id=preview_id,
        company_id=context.company.id,
        session_id=assistant_session.id,
        turn_id=payload.turn_id,
        proposal_id=payload.proposal_id,
        action_type=proposal.action_type,
        target_type=target.target_type,
        target_id=target.target_id,
        target_version=target.target_version,
        payload_json=material,
        payload_sha256=_sha256(_canonical_json(material["canonical"])),
        preview_token_sha256="0" * 64,
        session_version=assistant_session.version,
        policy_version=policy.policy_version,
        status=AssistantActionStatus.PENDING,
        created_by_membership_id=context.membership.id,
        expires_at=expires_at,
        created_at=now,
        updated_at=now,
    )
    row.preview_token_sha256 = _sha256(_preview_token(row))
    session.add(row)
    record_from_context(
        session,
        context,
        action="workspace_assistant.action_previewed",
        target_type="assistant_action_preview",
        target_id=row.id,
        matter_id=target.matter_id,
        ip_docket_id=target.docket_id,
        metadata={
            "assistant_session_id": row.session_id,
            "assistant_turn_id": row.turn_id,
            "proposal_id": row.proposal_id,
            "action_type": row.action_type,
            "payload_sha256": row.payload_sha256,
            "expires_at": row.expires_at.isoformat(),
        },
    )
    session.commit()
    session.refresh(row)
    return _response(row)


def _execute(
    session: Session,
    *,
    context: SessionContext,
    row: AssistantActionPreview,
    target: _ActionTarget,
) -> tuple[str, str, str]:
    canonical = dict((row.payload_json or {}).get("canonical") or {})
    if row.action_type == "task":
        if target.matter_id is not None:
            task = create_matter_task(
                session,
                context=context,
                matter_id=target.matter_id,
                payload=MatterTaskCreateRequest.model_validate(
                    {**canonical, "status": "todo"}
                ),
                commit=False,
            )
            return "matter_task", task.id, f"/app/matters/{target.matter_id}/tasks"
        assert target.docket_id is not None
        task = create_ip_shared_task(
            session,
            context=context,
            payload=IpSharedTaskCreateRequest.model_validate(
                {**canonical, "docket_id": target.docket_id, "status": "todo"}
            ),
            commit=False,
        )
        return "matter_task", task.id, f"/app/ip?docket={target.docket_id}&view=schedule"
    if row.action_type == "draft":
        if target.matter_id is not None:
            draft = create_draft(
                session,
                context=context,
                matter_id=target.matter_id,
                title=str(canonical["title"]),
                draft_type=str(canonical["draft_type"]),
                commit=False,
            )
            return "draft", draft.id, f"/app/matters/{target.matter_id}/drafts/{draft.id}"
        assert target.docket_id is not None and target.proceeding_id is not None
        draft = create_ip_draft(
            session,
            context=context,
            docket_id=target.docket_id,
            proceeding_id=target.proceeding_id,
            title=str(canonical["title"]),
            template_key=str(canonical["template_key"]),
            commit=False,
        )
        return (
            "draft",
            draft.id,
            f"/app/ip?docket={target.docket_id}&view=proceedings"
            f"&proceeding={target.proceeding_id}&draft={draft.id}",
        )
    assert target.matter_id is not None
    update_payload = MatterUpdateRequest.model_validate(canonical)
    updated = update_matter(
        session,
        context=context,
        matter_id=target.matter_id,
        payload=update_payload,
        commit=False,
    )
    return "matter", updated.id, f"/app/matters/{updated.id}"


def confirm_assistant_action(
    session: Session,
    *,
    context: SessionContext,
    session_id: str,
    preview_id: str,
    payload: AssistantActionConfirmRequest,
) -> AssistantActionPreviewResponse:
    discovered = session.scalar(
        select(AssistantActionPreview).where(
            AssistantActionPreview.id == preview_id,
            AssistantActionPreview.company_id == context.company.id,
            AssistantActionPreview.session_id == session_id,
            AssistantActionPreview.created_by_membership_id == context.membership.id,
        )
    )
    if discovered is None:
        raise _problem(
            code="assistant_action_preview_not_found",
            detail="Action preview not found.",
            status_code=404,
        )
    raw_proposal = AssistantProposedAction(
        proposal_id=discovered.proposal_id,
        action_type=discovered.action_type,  # type: ignore[arg-type]
        label="Stored assistant action",
        target_type=discovered.target_type,
        target_id=discovered.target_id,
        target_version=discovered.target_version,
        requires_confirmation=True,
        execution_available=True,
    )
    capabilities = _required_capabilities(raw_proposal)
    context = _locked_actor_context(session, context=context, capabilities=capabilities)
    policy = _locked_assistant_policy(session, context=context)
    assistant_session = _session_or_404(
        session,
        context=context,
        session_id=session_id,
        for_update=True,
    )
    row = session.scalar(
        select(AssistantActionPreview)
        .where(
            AssistantActionPreview.id == preview_id,
            AssistantActionPreview.company_id == context.company.id,
            AssistantActionPreview.session_id == assistant_session.id,
            AssistantActionPreview.created_by_membership_id == context.membership.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _problem(
            code="assistant_action_preview_not_found",
            detail="Action preview not found.",
            status_code=404,
        )
    expected_token = _preview_token(row)
    if not hmac.compare_digest(expected_token, payload.preview_token) or not hmac.compare_digest(
        row.preview_token_sha256, _sha256(payload.preview_token)
    ):
        raise _problem(
            code="assistant_action_preview_invalid",
            detail="The confirmation token does not match this preview.",
        )
    if row.status == AssistantActionStatus.CONFIRMED:
        response = _response(row)
        session.rollback()
        return response
    if row.status != AssistantActionStatus.PENDING:
        raise _problem(
            code="assistant_action_preview_superseded",
            detail="This preview was replaced. Create a current preview before confirming.",
        )
    if _aware(row.expires_at) <= datetime.now(UTC):
        row.status = AssistantActionStatus.SUPERSEDED
        session.commit()
        raise _problem(
            code="assistant_action_preview_expired",
            detail="This preview expired. Review the action again before confirming.",
        )
    if assistant_session.status != AssistantSessionStatus.ACTIVE:
        raise _problem(code="assistant_session_archived", detail="Archived sessions are read-only.")
    if (
        assistant_session.version != payload.expected_version
        or row.session_version != payload.expected_version
    ):
        raise _problem(
            code="assistant_session_version_conflict",
            detail="The assistant session changed. Create a new preview before confirming.",
        )
    if policy.policy_version != row.policy_version:
        raise _problem(
            code="assistant_action_policy_changed",
            detail="Workspace AI policy changed. Create a new preview before confirming.",
        )
    proposal = _proposal_or_404(
        session,
        context=context,
        session_id=session_id,
        turn_id=row.turn_id,
        proposal_id=row.proposal_id,
    )
    target = _resolve_target(session, context=context, proposal=proposal)
    if target.target_type != row.target_type or target.target_id != row.target_id:
        raise _problem(
            code="assistant_action_target_changed",
            detail="The proposed target changed. Create a new preview before confirming.",
        )
    result_type, result_id, result_href = _execute(
        session,
        context=context,
        row=row,
        target=target,
    )
    now = datetime.now(UTC)
    row.status = AssistantActionStatus.CONFIRMED
    row.result_type = result_type
    row.result_id = result_id
    row.result_href = result_href
    row.confirmed_at = now
    row.updated_at = now
    assistant_session.version += 1
    assistant_session.updated_at = now
    session.execute(
        update(AssistantActionPreview)
        .where(
            AssistantActionPreview.company_id == context.company.id,
            AssistantActionPreview.session_id == assistant_session.id,
            AssistantActionPreview.id != row.id,
            AssistantActionPreview.status == AssistantActionStatus.PENDING,
        )
        .values(status=AssistantActionStatus.SUPERSEDED, updated_at=now)
    )
    record_from_context(
        session,
        context,
        action="workspace_assistant.action_confirmed",
        target_type="assistant_action_preview",
        target_id=row.id,
        matter_id=target.matter_id,
        ip_docket_id=target.docket_id,
        metadata={
            "assistant_session_id": row.session_id,
            "assistant_turn_id": row.turn_id,
            "proposal_id": row.proposal_id,
            "action_type": row.action_type,
            "payload_sha256": row.payload_sha256,
            "result_type": result_type,
            "result_id": result_id,
        },
    )
    session.commit()
    session.refresh(row)
    return _response(row)


__all__ = ["confirm_assistant_action", "preview_assistant_action"]
