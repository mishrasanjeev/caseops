"""Dated, synthetic Docker fixture; never an application route or live probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    DomainConsumerEffect,
    DomainOutboxEvent,
    Matter,
    ModelRun,
    ProviderSpendReservation,
    TrackedCase,
    TrackedCaseBookmark,
    TrackedCaseProviderOperation,
    TrackedCaseUpdate,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import _tracked_case_identity_key, apply_snapshot
from caseops_api.services.case_tracking_providers import ProviderCaseEvent, ProviderCaseSnapshot
from caseops_api.services.case_tracking_summary import CONSUMER, EVENT_TYPE, PURPOSE, _messages
from caseops_api.services.identity import get_session_context
from caseops_api.services.llm_cassette import cassette_key

SOURCE_PATH = "/api/partner/case/DLHC010091232026/order/summary-20260910"
SOURCE_TEXT = (
    "Synthetic order dated 10 September 2026. File the witness list before the next hearing."
)
SOURCE_TITLE = "Summary acceptance source 2026-09-10"
FALLBACK = "Provider fixture: review the order and prepare the witness list."
GENERATED = "The order directs filing of a witness list before the next hearing."
MODEL = "caseops-mock-1"
FROZEN_CASSETTE_KEY = "fb977e47e7dde573278d134ae98d89580cb2b6dbbcb847ac406d13d6600e20db"
COMPLETION = {
    "text": json.dumps(
        {
            "concise_summary": GENERATED,
            "procedural_impact": "Prepare the witness list for lawyer review.",
            "next_hearing_or_action_signals": ["File the witness list before the next hearing."],
            "risks_or_unknowns": ["The source does not specify a hearing date."],
            "source_reference": None,
            "confidence": "medium",
            "summary_source": "caseops",
            "review_framing": "Synthetic acceptance response for lawyer review.",
        }
    ),
    "provider": "mock",
    "model": MODEL,
    "prompt_tokens": 80,
    "completion_tokens": 40,
    "latency_ms": 1,
}


def guard_local_runtime() -> None:
    settings = get_settings()
    database = make_url(settings.database_url)
    if not (
        settings.env == "e2e"
        and os.environ.get("CASEOPS_SUMMARY_ACCEPTANCE") == "1"
        and database.host == "postgres"
        and database.database == "caseops"
        and settings.case_tracking_enabled
        and settings.case_tracking_provider == "ecourtsindia"
        and settings.ecourtsindia_api_base_url == "http://acceptance-case-provider:8080"
        and settings.ecourtsindia_api_token == "docker-acceptance-provider-token"
        and settings.llm_provider == "mock"
        and settings.llm_model == MODEL
        and not settings.llm_api_key
    ):
        raise RuntimeError(
            "Summary fixture requires the explicitly isolated, mock-only Docker stack."
        )


def frozen_call_key() -> str:
    update = TrackedCaseUpdate(
        update_type="new_order",
        title=SOURCE_TITLE,
        source_text=SOURCE_TEXT,
        source_text_truncated=False,
    )
    return cassette_key(
        model=MODEL,
        temperature=0.1,
        max_tokens=1200,
        messages=_messages(TrackedCase(), update),
    )


def cassette_row() -> dict:
    if frozen_call_key() != FROZEN_CASSETTE_KEY:
        raise RuntimeError("Dated summary prompt changed; reconcile the frozen cassette contract.")
    return {"key": FROZEN_CASSETTE_KEY, "completion": COMPLETION}


def seed(session, *, actor_id: str, matter_id: str, scenario: str) -> dict:
    if scenario not in {"positive", "marked", "persistent_qa"}:
        raise ValueError("Unknown summary fixture scenario.")
    context = get_session_context(session, actor_id)
    prefix = "summarypersistent-" if scenario == "persistent_qa" else "summaryacceptance-"
    matter = session.get(Matter, matter_id)
    if (
        not context.company.slug.startswith(prefix)
        or matter is None
        or matter.company_id != context.company.id
        or matter.status != "intake"
        or not matter.is_active
    ):
        raise ValueError("Fixture requires its own newly bootstrapped tenant and Intake Matter.")
    tracked = TrackedCase(
        company_id=context.company.id,
        provider="ecourtsindia",
        identity_key=_tracked_case_identity_key(
            cnr_number="DLHC010091232026",
            case_number=None,
            court_code="DLHC",
            court_name=None,
        ),
        cnr_number="DLHC010091232026",
        case_title=f"Summary acceptance {scenario}",
        court_code="DLHC",
    )
    session.add(tracked)
    session.flush()
    bookmark = TrackedCaseBookmark(
        company_id=context.company.id,
        tracked_case_id=tracked.id,
        created_by_membership_id=actor_id,
        matter_id=matter.id,
        name=f"Summary acceptance {scenario}",
        scope_key=f"matter:{matter.id}",
        active_scope_key=f"matter:{matter.id}",
    )
    session.add(bookmark)
    session.flush()
    marker = set_automated_test_request(
        NO_PAID_PROVIDERS_VALUE if scenario == "marked" else None,
    )
    try:
        updates = apply_snapshot(
            session,
            context=context,
            tracked_case=tracked,
            snapshot=ProviderCaseSnapshot(
                provider="ecourtsindia",
                case_title=tracked.case_title,
                cnr_number="DLHC010091232026",
                case_number=None,
                court_code="DLHC",
                court_name=None,
                orders=[
                    ProviderCaseEvent(
                        source_record_key="summary-20260910",
                        title=SOURCE_TITLE,
                        source_url=f"http://acceptance-case-provider:8080{SOURCE_PATH}",
                        text=SOURCE_TEXT,
                        provider_summary=FALLBACK,
                        metadata={"summary_terms_permitted": True},
                    )
                ],
            ),
        )
    finally:
        reset_automated_test_request(marker)
    if len(updates) != 1 or updates[0].model_run_id is not None:
        raise RuntimeError("Expected one immediate source update without generation.")
    session.commit()
    return {
        "company_id": context.company.id,
        "actor_id": actor_id,
        "matter_id": matter.id,
        "bookmark_id": bookmark.id,
        "update_id": updates[0].id,
        "scenario": scenario,
    }


def inspect_fixture(session, *, actor_id: str, update_id: str) -> dict:
    context = get_session_context(session, actor_id)
    if not context.company.slug.startswith(("summaryacceptance-", "summarypersistent-")):
        raise ValueError("Inspection is restricted to owned summary fixture tenants.")
    update = session.scalar(
        select(TrackedCaseUpdate).where(
            TrackedCaseUpdate.id == update_id,
            TrackedCaseUpdate.company_id == context.company.id,
        )
    )
    if update is None:
        raise ValueError("Fixture update not found in the current tenant.")
    event = session.scalars(
        select(DomainOutboxEvent).where(
            DomainOutboxEvent.company_id == context.company.id,
            DomainOutboxEvent.aggregate_id == update.id,
            DomainOutboxEvent.event_type == EVENT_TYPE,
        )
    ).one()
    effects = list(
        session.scalars(
            select(DomainConsumerEffect).where(
                DomainConsumerEffect.company_id == context.company.id,
                DomainConsumerEffect.outbox_event_id == event.id,
                DomainConsumerEffect.consumer_name == CONSUMER,
            )
        )
    )
    runs = list(
        session.scalars(
            select(ModelRun)
            .where(
                ModelRun.company_id == context.company.id,
                ModelRun.purpose == PURPOSE,
            )
            .order_by(ModelRun.id)
        )
    )
    return {
        "summary": update.summary,
        "ai_summary": update.ai_summary_json,
        "model_run_id": update.model_run_id,
        "source_sha256": update.source_text_sha256,
        "event": {
            "id": event.id,
            "state": event.state,
            "attempts": event.attempts,
            "no_paid_providers": event.payload_json["no_paid_providers"],
        },
        "effects": [
            {"state": e.state, "result_type": e.result_type, "result_id": e.result_id}
            for e in effects
        ],
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "provider": r.provider,
                "model": r.model,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
            }
            for r in runs
        ],
        "provider_operations": session.scalar(
            select(func.count())
            .select_from(
                TrackedCaseProviderOperation,
            )
            .where(TrackedCaseProviderOperation.company_id == context.company.id)
        ),
        "spend_reservations": session.scalar(
            select(func.count())
            .select_from(
                ProviderSpendReservation,
            )
            .where(ProviderSpendReservation.company_id == context.company.id)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "inspect", "worker", "contract"))
    parser.add_argument("--actor-id")
    parser.add_argument("--matter-id")
    parser.add_argument("--update-id")
    parser.add_argument("--scenario", choices=("positive", "marked", "persistent_qa"))
    args = parser.parse_args()
    guard_local_runtime()
    if args.command == "worker":
        executable = shutil.which("caseops-document-worker")
        if executable is None:
            raise RuntimeError("The image does not contain its document worker executable.")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as stream:
            stream.write(json.dumps(cassette_row()) + "\n")
        environment = {
            **os.environ,
            "CASEOPS_LLM_CASSETTE_MODE": "replay",
            "CASEOPS_LLM_CASSETTE_PATH": stream.name,
            "CASEOPS_LLM_TEMPERATURE": "0.1",
        }
        os.execve(
            executable,
            [
                executable,
                "--once",
                "--skip-migrations",
                "--skip-maintenance",
                "--summary-batch-size",
                "25",
            ],
            environment,
        )
    elif args.command == "contract":
        cassette_row()
        from caseops_api.services import case_tracking_summary
        from caseops_api.workers import document_processor

        print(
            json.dumps(
                {
                    "cassette_key": FROZEN_CASSETTE_KEY,
                    "source_sha256": hashlib.sha256(SOURCE_TEXT.encode()).hexdigest(),
                    "hashes": {
                        name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                        for name, module in {
                            "consumer": case_tracking_summary,
                            "worker": document_processor,
                        }.items()
                    },
                }
            )
        )
    else:
        with get_session_factory()() as session:
            if args.command == "seed":
                result = seed(
                    session,
                    actor_id=args.actor_id,
                    matter_id=args.matter_id,
                    scenario=args.scenario,
                )
            else:
                result = inspect_fixture(session, actor_id=args.actor_id, update_id=args.update_id)
            print(json.dumps(result))


if __name__ == "__main__":
    main()
