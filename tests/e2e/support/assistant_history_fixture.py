"""Bounded loopback-only factual assistant history; never invokes a model."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from uuid import UUID


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("Local assistant fixture boundary rejected")


def main() -> None:
    global stage
    stage = "validate"
    raw = sys.stdin.read(8193)
    require(len(raw) <= 8192)
    data = json.loads(raw)
    require(isinstance(data, dict) and set(data) == {
        "web", "api", "run_id", "company_id", "membership_id", "user_id",
        "matter_id", "history_session_id", "other_session_id",
    })
    require(all(isinstance(value, str) for value in data.values()))
    require(re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", data["run_id"]) is not None)
    for key in set(data) - {"web", "api", "run_id"}:
        require(len(data[key]) == 36 and str(UUID(data[key])) == data[key])
    require(data["history_session_id"] != data["other_session_id"])
    for key in ("web", "api"):
        origin = urlsplit(data[key])
        require(origin.scheme == "http" and origin.hostname in {"127.0.0.1", "localhost", "::1"}
                and not origin.username and not origin.password
                and origin.path in {"", "/"} and not origin.query and not origin.fragment)
    require(os.environ.get("CASEOPS_ENV") == "e2e"
            and os.environ.get("CASEOPS_LLM_PROVIDER") == "mock"
            and not any(key.upper().startswith("PG") for key in os.environ))
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo / "apps" / "api" / "src"))

    from sqlalchemy import func, select
    from sqlalchemy.engine import make_url

    database = make_url(os.environ["CASEOPS_DATABASE_URL"])
    require(not database.query)
    if database.drivername == "sqlite+pysqlite":
        expected = repo / "caseops-e2e.db"
        require(not os.environ.get("CASEOPS_E2E_DOCKER_PROJECT")
                and database.database == expected.as_posix()
                and expected.is_file() and expected.resolve() == expected
                and not expected.is_symlink())
    else:
        require(database.drivername == "postgresql+psycopg"
                and database.host in {"127.0.0.1", "localhost", "::1"}
                and database.port is not None and 20000 <= database.port <= 49999
                and database.database == "caseops" and database.username == "caseops"
                and database.password == "caseops"
                and bool(os.environ.get("CASEOPS_E2E_DOCKER_PROJECT")))

    from caseops_api.db.models import (
        AssistantCitation, AssistantSession, AssistantSessionScope, AssistantTurn,
        Company, CompanyMembership, Matter, ModelRun, TenantAIPolicy, User,
    )
    from caseops_api.db.session import get_session_factory
    from caseops_api.schemas.matters import normalize_matter_code
    from caseops_api.services.session_context import SessionContext
    from caseops_api.services.workspace_assistant import (
        _persist_turn_pair, _resource_version, _sources_for_scopes, list_assistant_turns,
    )

    stage = "scope"
    with get_session_factory()() as session:
        require(session.get_bind().url == database)
        company = session.scalar(select(Company).where(Company.id == data["company_id"])
                                 .with_for_update(of=Company))
        member = session.get(CompanyMembership, data["membership_id"])
        user = session.get(User, data["user_id"])
        matter = session.get(Matter, data["matter_id"])
        run = data["run_id"]
        slug = f"assistant-history-{run}"
        require(company is not None and company.slug == slug
                and company.name == f"Synthetic assistant history {run}"
                and company.company_type == "law_firm" and company.is_active)
        created = company.created_at
        created = created.replace(tzinfo=UTC) if created.tzinfo is None else created
        require(0 <= (datetime.now(UTC) - created).total_seconds() <= 600)
        require(member is not None and member.company_id == company.id and member.user_id == data["user_id"]
                and member.role == "owner" and member.is_active
                and user is not None and user.is_active
                and user.email == f"assistant-{run}@example.com"
                and user.full_name == "Local assistant fixture owner")
        require(matter is not None and matter.company_id == company.id and matter.is_active
                and matter.title == f"Synthetic assistant Matter {run}"
                and matter.matter_code == normalize_matter_code(f"AIH-{run}"))
        policy = session.scalar(select(TenantAIPolicy).where(TenantAIPolicy.company_id == company.id))
        require(policy is not None and policy.workspace_assistant_enabled
                and json.loads(policy.allowed_models_assistant_json) == ["caseops-mock-1"])
        for model in (AssistantTurn, AssistantCitation, ModelRun):
            require(session.scalar(select(func.count()).select_from(model).where(model.company_id == company.id)) == 0)
        require(session.scalar(select(func.count()).select_from(Matter).where(Matter.company_id == company.id)) == 1)
        require(session.scalar(select(func.count()).select_from(CompanyMembership)
                               .where(CompanyMembership.company_id == company.id)) == 1)
        records = list(session.scalars(select(AssistantSession).where(AssistantSession.company_id == company.id)
                                      .order_by(AssistantSession.id).with_for_update(of=AssistantSession)))
        require({row.id for row in records} == {data["history_session_id"], data["other_session_id"]})
        context = SessionContext(company=company, user=user, membership=member)
        manifest: dict[str, list] = {}
        for record in records:
            history = record.id == data["history_session_id"]
            require(record.created_by_membership_id == member.id and record.status == "active"
                    and record.version == 1 and record.policy_version == policy.policy_version
                    and record.title == f"Synthetic {'history' if history else 'other'} {run}")
            scopes = list(session.scalars(select(AssistantSessionScope)
                                         .where(AssistantSessionScope.session_id == record.id,
                                                AssistantSessionScope.company_id == company.id)))
            require(len(scopes) == 1 and scopes[0].scope_type == "matter" and scopes[0].scope_id == matter.id
                    and scopes[0].resource_version == _resource_version(matter))
            sources = _sources_for_scopes(session, context=context, scope_rows=scopes,
                                          question="What is this matter's recorded status?")
            require(len(sources) == 1 and sources[0].source_type == "matter" and sources[0].source_id == matter.id
                    and sources[0].source_version == _resource_version(matter))
            stage = "persist"
            for index in range(26 if history else 1):
                question = f"Synthetic local fixture question {index + 1}: what is the recorded Matter status?"
                answer = (f"Synthetic local fixture {index + 1}: Matter {matter.matter_code} is recorded as "
                          f"{matter.status}. No model or provider was invoked.")
                pair = _persist_turn_pair(
                    session, context=context, assistant_session=record, question=question, answer=answer,
                    answer_status="completed", confidence="high", sources=sources,
                    suggested_searches=[], proposed_actions=[], model_run=None,
                )
                for turn in pair:
                    turn.retrieval_manifest_json = {
                        **turn.retrieval_manifest_json,
                        "fixture_provenance": {"kind": "synthetic_local_factual_history_no_model", "run_id": run},
                    }
            session.flush()
            stage = "verify"
            actual = []
            for offset in ((0, 50) if history else (0,)):
                page = list_assistant_turns(session, context=context, session_id=record.id, limit=50, offset=offset)
                actual.extend(page.items)
            require(len(actual) == (52 if history else 2)
                    and [turn.sequence for turn in actual] == list(range(1, len(actual) + 1))
                    and all(turn.render_status == "visible" and turn.model is None for turn in actual))
            manifest[record.id] = []
            for turn in actual:
                require(len(turn.citations) == (1 if turn.role == "assistant" else 0))
                manifest[record.id].append({
                    "id": turn.id, "sequence": turn.sequence,
                    "content_sha256": hashlib.sha256(turn.content.encode()).hexdigest(),
                    "citations": [{"id": item.id, "source_type": item.source_type, "source_id": item.source_id,
                                   "source_version": item.source_version, "source_sha256": item.source_sha256,
                                   "source_url": item.source_url} for item in turn.citations],
                })
        require(session.scalar(select(func.count()).select_from(ModelRun).where(ModelRun.company_id == company.id)) == 0)
        stage = "commit"
        session.commit()
        print(json.dumps({"schema_version": 1, "fixture_kind": "synthetic_local_factual_history_no_model",
                          "company_id": data["company_id"], "membership_id": data["membership_id"],
                          "matter_id": data["matter_id"], "history_session_id": data["history_session_id"],
                          "other_session_id": data["other_session_id"], "sessions": manifest}, separators=(",", ":")))


if __name__ == "__main__":
    stage = "validate"
    try:
        main()
    except Exception as error:
        sys.exit(f"Local assistant fixture failed at {stage} ({type(error).__name__}); no retry.")
