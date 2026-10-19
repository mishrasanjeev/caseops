"""The bounded docket barrier must not introduce an unrelated policy FROM."""
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from caseops_api.services.ip_specialist import list_records


@pytest.mark.parametrize("include_closed", [False, True])
def test_specialist_policy_adapts_every_docket_reference(include_closed):
    statements = []

    def capture(statement):
        statements.append(statement)
        return SimpleNamespace(all=lambda: [])

    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=postgresql.dialect()),
        execute=capture,
    )
    context = SimpleNamespace(
        company=SimpleNamespace(id="00000000-0000-4000-8000-000000000001"),
        membership=SimpleNamespace(id="00000000-0000-4000-8000-000000000002"),
    )
    result = list_records(session, context=context, domain="design", include_closed=include_closed)
    assert result.records == [] and result.next_cursor is None
    assert len(statements) == 1
    sql = str(
        statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert sql.count("FROM ip_docket_records") == 1
    lookup, boundary, policy = sql.partition("AS candidate_docket")
    assert boundary
    assert "WHERE ip_docket_records.id >= ip_specialist_records.docket_id" in lookup
    assert "ORDER BY ip_docket_records.id" in lookup and "LIMIT 1" in lookup
    assert "ip_docket_records" not in policy
    assert "candidate_docket.id = ip_specialist_records.docket_id" in policy
    assert "candidate_docket.company_id = ip_specialist_records.company_id" in policy
    assert "candidate_docket.restricted IS true" in policy
    assert ("candidate_docket.is_active IS true" in policy) is not include_closed
    assert "candidate_docket.archived_by_matter_disposal" in policy
    assert "candidate_docket.current_version" in sql
    assert "ip_specialist_versions" not in sql
