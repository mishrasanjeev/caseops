"""Whole retained HTTP journeys and every actual serving relation on PostgreSQL."""

import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import Exists

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    EthicalWall,
    HearingPack,
    Matter,
    MatterAccessGrant,
    Team,
    TeamMembership,
)
from caseops_api.db.session import _proven_read_statement, get_engine, get_session_factory
from tests.sql_observation import is_read_only_select
from tests.test_hearing_explicit_channels_20261027 import forbid_unadmitted_network as _offline
from tests.test_matter_readthrough_20261028 import (
    BASE,
    ROLES,
    STAMP,
    exercise_acl,
    exercise_foreign,
    exercise_latest,
    exercise_pages,
    exercise_policy_change,
    exercise_role,
    exercise_sql,
    exercise_stale_cursor,
    exercise_unsupported,
    member,
    request,
    seed,
    setup,
    uid,
)
from tests.test_matter_readthrough_20261028 import (
    test_cursor_local_clock_and_all_required_identity_claims as crypto_contract,
)
from tests.test_matter_readthrough_20261028 import (
    test_legacy_non_uuid_id_and_excluded_intelligent_review_are_honest as legacy_contract,
)
from tests.test_matter_readthrough_20261028 import (
    test_private_headers_on_current_membership_denial as inactive_headers_contract,
)
from tests.test_matter_readthrough_20261028 import (
    test_private_response_headers_cover_success_auth_validation_and_missing as private_contract,
)
from tests.test_matter_readthrough_evidence_20261028 import capture_plan, compact_plan_record

forbid_unadmitted_network = _offline
pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("reverse", [False, True], ids=["forward-source", "reverse-source"])
def test_pg_complete_chronological_and_child_keysets(isolated_postgres_client, reverse):
    exercise_pages(isolated_postgres_client, reverse)


@pytest.mark.parametrize("role", ROLES)
def test_pg_six_current_roles_read_only(isolated_postgres_client, role):
    exercise_role(isolated_postgres_client, role)


def test_pg_latest_pack_tie_null_and_exact_source(isolated_postgres_client):
    exercise_latest(isolated_postgres_client)


def test_pg_unsupported_retained_content_keeps_valid_siblings(isolated_postgres_client):
    exercise_unsupported(isolated_postgres_client)


@pytest.mark.parametrize("boundary", ["anchor_deleted", "anchor_time", "close_reopen"])
def test_pg_current_anchor_and_lifecycle(isolated_postgres_client, boundary):
    exercise_stale_cursor(isolated_postgres_client, boundary)


@pytest.mark.parametrize("boundary", ["wall", "restricted", "inactive_actor"])
def test_pg_live_scope_acl(isolated_postgres_client, boundary):
    exercise_acl(isolated_postgres_client, boundary)


@pytest.mark.parametrize("boundary", ["grant_revoke", "team_remove", "role_downgrade"])
def test_pg_current_grant_team_and_retained_role(isolated_postgres_client, boundary):
    exercise_policy_change(isolated_postgres_client, boundary)


def test_pg_foreign_tenant_matter_parent_and_child(isolated_postgres_client):
    exercise_foreign(isolated_postgres_client)


def test_pg_every_observed_statement_typed_and_bounded(isolated_postgres_client):
    exercise_sql(isolated_postgres_client)


INDEXES = (
    (
        "recommendations",
        "ix_recommendation_read_company_matter_created_id",
        "company_id,matter_id,created_at,id",
        "type <> 'intelligent_review'",
    ),
    (
        "recommendation_options",
        "ix_recommendation_option_parent_rank_id",
        "recommendation_id,rank,id",
        None,
    ),
    (
        "recommendation_decisions",
        "ix_recommendation_decision_parent_created_id",
        "recommendation_id,created_at,id",
        None,
    ),
    (
        "hearing_packs",
        "ix_hearing_pack_matter_hearing_generated_id",
        "matter_id,hearing_id,generated_at,id",
        None,
    ),
    ("hearing_pack_items", "ix_hearing_pack_item_parent_rank_id", "pack_id,rank,id", None),
)


def _plan_evidence_root(tmp_path, cohort_order, index_timing):
    assert cohort_order in {"visible_first", "competing_first"}
    assert index_timing in {"before_seed", "after_seed"}
    configured = os.environ.get("CASEOPS_READTHROUGH_EVIDENCE_DIR")
    if configured is None:
        return tmp_path
    root = Path(configured)
    assert root.is_absolute(), "Absolute retained readthrough evidence root required"
    root.mkdir(mode=0o700, exist_ok=True)
    observed = root.lstat()
    assert stat.S_ISDIR(observed.st_mode) and not stat.S_ISLNK(observed.st_mode)
    assert observed.st_uid == os.getuid() and root.resolve(strict=True) == root
    # A repeated attempt needs a fresh run root, never replacement of the
    # original failure's plans. Each of the four layouts owns a separate leaf.
    retained = root / (cohort_order + "-" + index_timing)
    retained.mkdir(mode=0o700, exist_ok=False)
    return retained


def _nodes(node, owner=None):
    current = node.get("Relation Name") or owner
    yield node, current
    for child in node.get("Plans", []):
        yield from _nodes(child, current)


def _plan_work(plan):
    work = 0
    attribution = []
    for node, owner in _nodes(plan["Plan"]):
        loops = node.get("Actual Loops", 1)
        charged = loops * (
            node.get("Actual Rows", 0)
            + node.get("Rows Removed by Filter", 0)
            + node.get("Rows Removed by Index Recheck", 0)
            + node.get("Rows Removed by Join Filter", 0)
        )
        work += charged
        attribution.append(
            {
                "node": node["Node Type"],
                "relation": owner,
                "index": node.get("Index Name"),
                "cte": node.get("CTE Name"),
                "loops": loops,
                "work": charged,
            }
        )
    return work, attribution


# These literal GET journeys are the proved plan scope, not "all readthrough plans".
# Each request keeps its complete authorization/actor/scope/parent/anchor SQL event
# sequence. Repeated identical statements are measured once per request and cost,
# with their actual occurrence count charged explicitly in the request total.
HTTP_AUTH_SHAPES = ("http_membership", "http_platform_mfa", "http_tenant_policy")
POSITIVE_PLAN_SHAPES = {
    "recommendations_first": ("actor", "scope", "recommendation_page", "actor", "scope"),
    "recommendations_next": (
        "actor",
        "scope",
        "recommendation_anchor",
        "recommendation_page",
        "actor",
        "scope",
    ),
    "recommendation_detail": ("actor", "scope", "recommendation_detail", "actor", "scope"),
    "options_first": (
        "actor",
        "scope",
        "recommendation_parent",
        "option_page",
        "actor",
        "scope",
        "recommendation_parent",
    ),
    "options_next": (
        "actor",
        "scope",
        "recommendation_parent",
        "option_anchor",
        "option_page",
        "actor",
        "scope",
        "recommendation_parent",
    ),
    "decisions_first": (
        "actor",
        "scope",
        "recommendation_parent",
        "decision_page",
        "actor",
        "scope",
        "recommendation_parent",
    ),
    "decisions_next": (
        "actor",
        "scope",
        "recommendation_parent",
        "decision_anchor",
        "decision_page",
        "actor",
        "scope",
        "recommendation_parent",
    ),
    "items_first": (
        "actor",
        "scope",
        "pack_parent",
        "item_page",
        "actor",
        "scope",
        "pack_parent",
    ),
    "items_next": (
        "actor",
        "scope",
        "pack_parent",
        "item_anchor",
        "item_page",
        "actor",
        "scope",
        "pack_parent",
    ),
    "latest_pack": ("actor", "scope", "hearing_parent", "pack_source", "actor", "scope"),
    "direct_pack": ("actor", "scope", "pack_source", "actor", "scope"),
}
DENIED_SCOPE_SHAPES = ("actor", "scope", "actor")
WRONG_PARENT_SHAPES = {
    "recommendation_detail": POSITIVE_PLAN_SHAPES["recommendation_detail"],
    "options_first": ("actor", "scope", "recommendation_parent", "actor", "scope"),
    "decisions_first": ("actor", "scope", "recommendation_parent", "actor", "scope"),
    "items_first": ("actor", "scope", "pack_parent", "actor", "scope"),
    "latest_pack": ("actor", "scope", "hearing_parent", "actor", "scope"),
    "direct_pack": POSITIVE_PLAN_SHAPES["direct_pack"],
}
FIRST_GETS = (
    "recommendations_first",
    "recommendation_detail",
    "options_first",
    "decisions_first",
    "items_first",
    "latest_pack",
    "direct_pack",
)
PAGED_GETS = ("recommendations_first", "options_first", "decisions_first", "items_first")
COSTS = ("default", "adverse")


def _captured_shape(statement):
    """Classify exact typed projections; unknown/new SQL is not silently omitted."""
    columns = list(statement.selected_columns)
    # Compound packed/canonical reads retain the original typed source-column
    # lineage. Follow those exact proxies; an unknown shape still refuses.
    top = {
        getattr(getattr(origin, "table", None), "name", None)
        for column in columns
        for origin in column.proxy_set
    }
    names = {getattr(node, "name", None) for node in visitors.iterate(statement)}
    keys = tuple(column.key for column in columns)
    limit = getattr(getattr(statement, "_limit_clause", None), "value", None)
    if "company_memberships" in top:
        return "http_membership"
    if "platform_admin_memberships" in top:
        return "http_platform_mfa"
    if "tenant_security_policies" in top:
        return "http_tenant_policy"
    if "matters" in top and "lifecycle_version" in keys and limit == 1:
        return "scope"
    if "recommendations" in top:
        if keys == ("id", "created_at") and limit == 1:
            return "recommendation_anchor"
        if limit == 26:
            return "recommendation_page"
        if limit == 1:
            return "recommendation_detail"
    for table, first, anchor in (
        ("recommendation_options", "option_page", "option_anchor"),
        ("recommendation_decisions", "decision_page", "decision_anchor"),
        ("hearing_pack_items", "item_page", "item_anchor"),
    ):
        if table in top:
            if len(keys) == 2 and limit == 1:
                return anchor
            if limit == 26:
                return first
    if "hearing_packs" in top and limit == 1:
        return "pack_parent" if keys == ("id",) else "pack_source"
    if "matter_hearings" in top and keys == ("id",) and limit == 1:
        return "hearing_parent"
    if len(columns) == 1 and isinstance(columns[0], Exists) and limit is None:
        if "recommendations" in names:
            return "recommendation_parent"
        if "hearing_packs" in names:
            return "pack_parent"
        if "readthrough_actor" in names and "readthrough_actor_user" in names:
            return "actor"
    raise AssertionError(
        ("Uninventoried actual typed SQL", sorted(str(name) for name in top), keys)
    )


def _matrix_journeys():
    journeys = []
    for profile in ("owner", "team_grant_viewer"):
        journeys.extend((profile, name, "positive") for name in POSITIVE_PLAN_SHAPES)
    journeys.extend(("team_grant_viewer", name, "denied_neighbor") for name in FIRST_GETS)
    journeys.extend(("team_grant_viewer", name, "wrong_parent") for name in WRONG_PARENT_SHAPES)
    journeys.append(("team_grant_viewer", "recommendations_first", "team_removed"))
    return journeys


def _expected_shapes(name, mode):
    if mode == "positive":
        return HTTP_AUTH_SHAPES + POSITIVE_PLAN_SHAPES[name]
    if mode in {"denied_neighbor", "team_removed"}:
        return HTTP_AUTH_SHAPES + DENIED_SCOPE_SHAPES
    if mode == "wrong_parent":
        return HTTP_AUTH_SHAPES + WRONG_PARENT_SHAPES[name]
    raise ValueError("Unsupported matrix boundary")


def _read_path(case, name):
    routes = {
        "recommendations_first": "/recommendations",
        "recommendations_next": "/recommendations",
        "recommendation_detail": "/recommendations/" + case["recommendation"],
        "options_first": "/recommendations/" + case["recommendation"] + "/options",
        "options_next": "/recommendations/" + case["recommendation"] + "/options",
        "decisions_first": "/recommendations/" + case["recommendation"] + "/decisions",
        "decisions_next": "/recommendations/" + case["recommendation"] + "/decisions",
        "items_first": "/hearing-packs/" + case["pack"] + "/items",
        "items_next": "/hearing-packs/" + case["pack"] + "/items",
        "latest_pack": "/hearings/" + case["hearing"]["id"] + "/pack",
        "direct_pack": "/hearing-packs/" + case["pack"],
    }
    return routes[name]


def _expected_ids(case, name):
    start = case["start"]
    offsets = {
        "recommendations_first": [*reversed(range(5, 30))],
        "recommendations_next": [*reversed(range(5)), *range(30, 50)],
        "options_first": [1000 + n for n in range(25)],
        "options_next": [1000 + n for n in range(25, 50)],
        "decisions_first": [2000 + n for n in reversed(range(135, 160))],
        "decisions_next": [2000 + n for n in reversed(range(110, 135))],
        "items_first": [4000 + n for n in range(25)],
        "items_next": [4000 + n for n in range(25, 50)],
    }
    return [uid(start + offset) for offset in offsets[name]]


def _install_non_owner_matrix_policy(client, visible, competing):
    membership, token = member(client, visible, "viewer")
    company_id = visible["auth"]["company"]["id"]
    with get_session_factory()() as session:
        viewer_user = session.get(CompanyMembership, membership).user_id
        session.get(Company, company_id).team_scoping_enabled = True
        actor_team = Team(
            id=uid(900001), company_id=company_id, name="Granted team", slug="granted"
        )
        other_team = Team(id=uid(900002), company_id=company_id, name="Other team", slug="other")
        session.add_all([actor_team, other_team])
        session.flush()
        visible_matter = session.get(Matter, visible["matter"]["id"])
        visible_matter.team_id = other_team.id
        visible_matter.restricted_access = True
        denied = session.get(Matter, competing["matter"]["id"])
        denied.team_id = other_team.id
        denied.restricted_access = True
        # Access crosses the Matter's different team only through this current
        # active team grant. The same company's dense neighboring source has no
        # matching grant and is also walled from this exact actor team.
        session.add(TeamMembership(id=uid(900003), team_id=actor_team.id, membership_id=membership))
        session.add(
            MatterAccessGrant(
                id=uid(900004),
                company_id=company_id,
                matter_id=visible_matter.id,
                team_id=actor_team.id,
                access_level="viewer",
                effective_from=STAMP - timedelta(days=10),
            )
        )
        session.add(
            EthicalWall(
                id=uid(900005),
                company_id=company_id,
                matter_id=denied.id,
                excluded_team_id=actor_team.id,
                reason="Synthetic denied neighbor",
                effective_from=STAMP - timedelta(days=10),
            )
        )
        session.commit()
    return membership, viewer_user, token


_PUBLIC_PREFIX_FIELDS = {
    "type",
    "title",
    "confidence",
    "status",
    "rationale",
    "assumptions_json",
    "missing_facts_json",
    "next_action",
    "retrieved_authorities_json",
    "strategy_payload_json",
    "analysis_json",
    "label",
    "supporting_citations_json",
    "risk_notes",
    "actor_membership_id",
    "decision",
    "notes",
    "generated_by_membership_id",
    "reviewed_by_membership_id",
    "model_run_id",
    "summary",
    "item_type",
    "body",
    "source_ref",
}
_PUBLIC_PROJECTION_KEYS = (
    _PUBLIC_PREFIX_FIELDS
    | {name + "_source_bytes" for name in _PUBLIC_PREFIX_FIELDS}
    | {
        "id",
        "company_id",
        "matter_id",
        "created_at",
        "updated_at",
        "review_required",
        "primary_option_index",
        "recommendation_id",
        "rank",
        "selected_option_index",
        "hearing_id",
        "generated_at",
        "reviewed_at",
        "pack_id",
        "__company_id",
        "__matter_id",
    }
)
_PUBLIC_READ_INTEGERS = {*range(27), 37, 41, 256, 401, 501, 16385}


def _public_probe_binding(value, public_ids):
    # These GETs bind synthetic IDs, role/status literals, exact cursor dates
    # and scalar limits only. No token/password/session hash is admitted to a
    # persisted probe. Unknown binding content fails without reflecting it.
    if value is None or type(value) is bool:
        return value
    if type(value) is int and value in _PUBLIC_READ_INTEGERS:
        return value
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, str) and value in public_ids | set(ROLES) | _PUBLIC_PROJECTION_KEYS | {
        "active",
        "intelligent_review",
        "",
        "chron",
        "rank",
        "id",
        "latest",
    }:
        return value
    if isinstance(value, datetime) and value == STAMP:
        return value.isoformat(timespec="microseconds")
    if isinstance(value, (tuple, list)):
        return [_public_probe_binding(item, public_ids) for item in value]
    raise AssertionError("Captured binding is outside the admitted synthetic public probe")


def _write_attempt(path, row, *, exclusive=False):
    with path.open("x" if exclusive else "w") as output:
        output.write(json.dumps(row, indent=2, default=str) + "\n")
        output.flush()
        os.fsync(output.fileno())


@pytest.mark.parametrize("index_timing", ["before_seed", "after_seed"])
@pytest.mark.parametrize("cohort_order", ["visible_first", "competing_first"])
def test_pg_named_get_policy_and_continuation_plan_matrix(
    isolated_postgres_client,
    index_timing,
    cohort_order,
    tmp_path,
):
    tmp_path = _plan_evidence_root(tmp_path, cohort_order, index_timing)
    control_work, _ = _plan_work(
        {
            "Plan": {
                "Node Type": "Nested Loop",
                "Actual Rows": 1,
                "Actual Loops": 1,
                "Rows Removed by Join Filter": 401,
            }
        }
    )
    assert control_work == 402 and control_work > 400
    admitted_binding = _public_probe_binding([uid(1), "viewer", 26, STAMP], {uid(1)})
    assert admitted_binding == [uid(1), "viewer", 26, STAMP.isoformat(timespec="microseconds")]
    with pytest.raises(AssertionError, match="outside the admitted synthetic public probe"):
        _public_probe_binding("synthetic-bearer-token-or-session-hash", {uid(1)})
    with pytest.raises(AssertionError, match="outside the admitted synthetic public probe"):
        _public_probe_binding("unreviewed_projection_field", {uid(1)})
    with pytest.raises(AssertionError, match="outside the admitted synthetic public probe"):
        _public_probe_binding(99991, {uid(1)})
    journeys = _matrix_journeys()
    assert len(journeys) == len(set(journeys)) == 36
    expected = {}
    for profile, name, mode in journeys:
        for shape in dict.fromkeys(_expected_shapes(name, mode)):
            for cost in COSTS:
                label = "/".join((profile, mode, name, shape, cost))
                assert label not in expected
                expected[label] = {"status": "unreached"}
    assert len(expected) == 460
    (tmp_path / "complete-plan-inventory.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "literalJourneys": journeys,
                "expectedLabels": list(expected),
                "observed": expected,
                "completeHTTPInventory": [],
                "complete": False,
                "stage": "before_fixture_source_creation",
                "perStatementWorkCap": 400,
                "perStatementMilliseconds": 5000,
                "perHTTPRequestStatementCap": 20,
                "universalOrNativeAcceptanceClaim": False,
            },
            indent=2,
        )
        + "\n"
    )
    client = isolated_postgres_client
    engine = get_engine()
    if index_timing == "after_seed":
        with engine.begin() as connection:
            for _table, name, _columns, _predicate in INDEXES:
                connection.exec_driver_sql(f'DROP INDEX "{name}"')
    visible = setup(client, count=0, start=100000, seed_records=False)
    competing = setup(client, count=0, start=200000, seed_records=False, auth=visible["auth"])
    cases = {"visible": visible, "competing": competing}
    order = [("visible", 160), ("competing", 640)]
    if cohort_order == "competing_first":
        order.reverse()
    for name, count in order:
        case = cases[name]
        seed(case, count=count, reverse=True)
        with get_session_factory()() as session:
            for n in range(3, count):
                session.add(
                    HearingPack(
                        id=uid(case["start"] + 8000 + n),
                        matter_id=case["matter"]["id"],
                        hearing_id=case["hearing"]["id"],
                        status="draft",
                        summary="Historical pack source",
                        review_required=True,
                        generated_at=STAMP - timedelta(days=20 + n),
                    )
                )
            session.commit()
    if index_timing == "after_seed":
        with engine.begin() as connection:
            for table, name, columns, predicate in INDEXES:
                sql = f'CREATE INDEX "{name}" ON "{table}" ({columns})'
                if predicate:
                    sql += " WHERE " + predicate
                connection.exec_driver_sql(sql)
    viewer_membership, viewer_user, viewer = _install_non_owner_matrix_policy(
        client, visible, competing
    )
    public_ids = {viewer_membership, viewer_user, *[uid(n) for n in range(900001, 900006)]}
    for source, count in ((visible, 160), (competing, 640)):
        public_ids.update(source["auth"][kind]["id"] for kind in ("company", "user", "membership"))
        public_ids.update((source["matter"]["id"], source["hearing"]["id"]))
        for offset in (0, 1000, 2000, 4000):
            public_ids.update(uid(source["start"] + offset + n) for n in range(count))
        public_ids.update(uid(source["start"] + n) for n in (3001, 3002, 3999))
        public_ids.update(uid(source["start"] + 8000 + n) for n in range(3, count))
    observed = {}
    failures = []
    owner_dtos = {}
    first_pages = {}
    http_inventory = []
    http_attempts = []
    active_attempt = None
    active_attempt_file = None
    complete = False
    try:
        for profile, name, mode in journeys:
            operation = "/".join((profile, mode, name))
            if mode == "team_removed":
                with get_session_factory()() as session:
                    session.delete(session.get(TeamMembership, uid(900003)))
                    session.commit()
            token = visible["token"] if profile == "owner" else viewer
            path_case = competing if mode in {"denied_neighbor", "wrong_parent"} else visible
            matter_case = competing if mode == "denied_neighbor" else visible
            url = BASE + "/" + matter_case["matter"]["id"] + _read_path(path_case, name)
            params = {}
            if name.endswith(("_first", "_next")):
                params["limit"] = 25
            if name.endswith("_next"):
                source_first = name.removesuffix("_next") + "_first"
                prior = first_pages[(profile, source_first)]
                assert prior["items"] and isinstance(prior["next_cursor"], str)
                params["cursor"] = prior["next_cursor"]
            captured = []
            attempt = {
                "operation": operation,
                "stage": "reserved_before_request",
                "reached": True,
                "responseReceived": False,
                "acceptedMeasurementComplete": False,
                "observedSQLAttempts": [],
            }
            attempt_file = tmp_path / (operation.replace("/", "-") + "-attempt.json")
            _write_attempt(attempt_file, attempt, exclusive=True)
            http_attempts.append(attempt)
            active_attempt, active_attempt_file = attempt, attempt_file

            def observe(
                _conn,
                _cursor,
                sql,
                parameters,
                execution_context,
                many,
                _captured=captured,
                _attempt=attempt,
                _file=attempt_file,
            ):
                event_row = {
                    "ordinal": len(_attempt["observedSQLAttempts"]),
                    "stage": "observed_before_binding_validation",
                    "driverSQLSha256": hashlib.sha256(sql.encode()).hexdigest(),
                    "template": None,
                }
                _attempt["observedSQLAttempts"].append(event_row)
                _attempt["stage"] = "observing_actual_sql"
                _write_attempt(_file, _attempt)
                try:
                    _observe_bound(event_row, sql, execution_context, many)
                except BaseException as exc:
                    event_row["stage"] = "observer_refused"
                    event_row["failureClass"] = type(exc).__name__
                    _attempt["stage"] = "observer_refused"
                    _write_attempt(_file, _attempt)
                    raise

            def _observe_bound(
                event_row,
                sql,
                execution_context,
                many,
                _captured=captured,
                _attempt=attempt,
                _file=attempt_file,
            ):
                statement = (
                    execution_context.compiled.statement if execution_context.compiled else None
                )
                proven = is_read_only_select(statement) and _proven_read_statement(statement)
                if not proven:
                    raise AssertionError("Actual typed read-only SQL required")
                # This is the compiler's parameterized template, before literal
                # or expanded values: unknown bindings never reach the journal.
                event_row["template"] = str(execution_context.compiled)
                _write_attempt(_file, _attempt)
                bound = (
                    execution_context.compiled_parameters[0]
                    if execution_context.compiled_parameters
                    else {}
                )
                effective = {}
                if execution_context.compiled:
                    expanded = getattr(execution_context, "_expanded_parameters", {}) or {}
                    for parameter, rendered in execution_context.compiled.bind_names.items():
                        if rendered in bound:
                            effective[parameter.key] = bound[rendered]
                        elif rendered in expanded:
                            effective[parameter.key] = [bound[key] for key in expanded[rendered]]
                        elif parameter.literal_execute:
                            effective[parameter.key] = parameter.effective_value
                        else:
                            raise AssertionError(("Missing actual captured bind", rendered))
                public = {
                    rendered: _public_probe_binding(value, public_ids)
                    for rendered, value in bound.items()
                }
                for value in effective.values():
                    _public_probe_binding(value, public_ids)
                # The effective values use original BindParameter keys, not
                # just the rendered _id/param names, including expanded roles.
                _captured.append((sql, statement, effective, many, public))
                event_row["stage"] = "public_bindings_admitted"
                event_row["actualPublicBindings"] = public
                _write_attempt(_file, _attempt)

            event.listen(engine, "before_cursor_execute", observe)
            try:
                response = request(client, "GET", url, token, params=params)
            except BaseException as exc:
                attempt["stage"] = "request_exception"
                attempt["failureClass"] = type(exc).__name__
                _write_attempt(attempt_file, attempt)
                raise
            finally:
                event.remove(engine, "before_cursor_execute", observe)
            attempt["responseReceived"] = True
            attempt["responseStatus"] = response.status_code
            attempt["stage"] = "response_received_before_validation"
            _write_attempt(attempt_file, attempt)
            # Persist every actual event before DTO/shape assertions. No SQL is
            # discarded because it is a preflight, source anchor, CTE or repeated.
            http_row = {
                "operation": operation,
                "status": response.status_code,
                "actualReadOnlyHTTPDTO": response.json(),
                "allActualSQL": [
                    {"ordinal": n, "driverSQL": sql, "actualPublicBindings": captured[n][4]}
                    for n, (sql, *_rest) in enumerate(captured)
                ],
                "expectedTypedShapes": _expected_shapes(name, mode),
            }
            http_file = tmp_path / (operation.replace("/", "-") + "-http.json")
            http_file.write_text(json.dumps(http_row, indent=2, default=str) + "\n")
            assert captured and len(captured) <= 20
            typed = []
            for sql, statement, bound, many, public in captured:
                assert not many
                proven = is_read_only_select(statement) and _proven_read_statement(statement)
                assert proven
                bound_statement = statement.params(**bound)
                shape = _captured_shape(bound_statement)
                typed.append((shape, sql, bound_statement, public))
            assert tuple(shape for shape, *_ in typed) == _expected_shapes(name, mode)
            http_row["observedTypedShapes"] = [shape for shape, *_ in typed]
            positive = mode == "positive"
            assert response.status_code == (200 if positive else 404), response.text
            body = response.json()
            if positive:
                assert body["scope"]["company_id"] == visible["auth"]["company"]["id"]
                assert body["scope"]["matter_id"] == visible["matter"]["id"]
                assert (
                    body["scope"]["matter_lifecycle_version"]
                    == visible["matter"]["lifecycle_version"]
                )
                if "items" in body:
                    assert [row["id"] for row in body["items"]] == _expected_ids(visible, name)
                    assert len(body["items"]) == 25 and body["next_cursor"]
                    assert all(
                        row["read_state"] == "available" and row["record"] for row in body["items"]
                    )
                    if name.endswith("_first"):
                        first_pages[(profile, name)] = body
                    else:
                        old_ids = {
                            row["id"] for row in first_pages[(profile, source_first)]["items"]
                        }
                        assert old_ids.isdisjoint(row["id"] for row in body["items"])
                else:
                    assert body["id"] == (
                        visible["recommendation"]
                        if name == "recommendation_detail"
                        else visible["pack"]
                    )
                    assert body["read_state"] == "available" and body["record"]
                dto_without_cursor = {
                    key: value for key, value in body.items() if key != "next_cursor"
                }
                if profile == "owner":
                    owner_dtos[name] = dto_without_cursor
                else:
                    assert dto_without_cursor == owner_dtos[name]
            else:
                assert "items" not in body and "Recorded rationale" not in response.text
            # The complete occurrence sequence was checked above. A repeated
            # shape is reusable here only if it has identical actual typed SQL.
            unique = {}
            occurrences = {}
            for shape, _sql, statement, public in typed:
                sql = str(
                    statement.compile(
                        dialect=postgresql.dialect(),
                        compile_kwargs={"literal_binds": True},
                    )
                )
                if shape in unique:
                    assert unique[shape][0] == sql
                else:
                    unique[shape] = (sql, statement, public)
                occurrences[shape] = occurrences.get(shape, 0) + 1
            attempt["stage"] = "measuring_admitted_actual_shapes"
            _write_attempt(attempt_file, attempt)
            totals = {cost: 0 for cost in COSTS}
            for shape, (sql, statement, public) in unique.items():
                baseline_rows = None
                for cost in COSTS:
                    label = "/".join((profile, mode, name, shape, cost))
                    assert label in expected and label not in observed
                    with engine.begin() as connection:
                        connection.exec_driver_sql("SET LOCAL statement_timeout = 5000")
                        if cost == "adverse":
                            connection.exec_driver_sql("SET LOCAL random_page_cost = 100")
                        encoded = connection.exec_driver_sql(
                            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql,
                            execution_options={"no_parameters": True},
                        ).scalar_one()
                        plan = encoded[0]
                        work, attribution = _plan_work(plan)
                        canonical_reads = [
                            {
                                "relation": owner,
                                "node": node["Node Type"],
                                "actualLoops": node.get("Actual Loops", 1),
                            }
                            for node, owner in _nodes(plan["Plan"])
                            if owner
                            in {
                                "recommendations",
                                "recommendation_options",
                                "recommendation_decisions",
                                "hearing_packs",
                                "hearing_pack_items",
                            }
                            and node["Node Type"]
                            in {
                                "Seq Scan",
                                "Index Scan",
                                "Index Only Scan",
                                "Bitmap Heap Scan",
                                "Bitmap Index Scan",
                                "Tid Scan",
                                "Tid Range Scan",
                                "Sample Scan",
                                "Foreign Scan",
                            }
                            and node.get("Actual Loops", 1) > 0
                        ]
                        # Retain the actual plan before a projection/readback
                        # failure can interrupt this measurement. Its original
                        # unverified record is never relabeled as accepted.
                        raw = {
                            "label": label,
                            "status": "plan_captured_projection_unverified",
                            "work": work,
                            "cap": 400,
                            "plan": plan,
                            "actualTypedSQL": sql,
                            "actualPublicBindings": public,
                            "allNodeAttribution": attribution,
                            "cleanCanonicalSourceReads": canonical_reads,
                            "actualOccurrences": occurrences[shape],
                            "occurrenceWeightedWork": work * occurrences[shape],
                        }
                        captured_path = tmp_path / (label.replace("/", "-") + "-captured.json")
                        try:
                            captured_ref = capture_plan(captured_path, raw)
                        except BaseException:
                            observed[label] = {
                                "status": "capture_incomplete",
                                "capturedBasename": captured_path.name,
                            }
                            raise
                        observed[label] = compact_plan_record(raw, captured_ref)
                        projected = [dict(row) for row in connection.execute(statement).mappings()]
                    # A cheap EXPLAIN for a wrongly rebound statement is not
                    # source evidence. Match the actual projected identities to
                    # this exact HTTP response/continuation before accepting work.
                    if shape in {
                        "recommendation_page",
                        "option_page",
                        "decision_page",
                        "item_page",
                    }:
                        assert positive
                        assert [row["id"] for row in projected[:25]] == [
                            row["id"] for row in body["items"]
                        ]
                        assert len(projected) == 26
                    elif shape.endswith("_anchor"):
                        preceding = first_pages[(profile, name.removesuffix("_next") + "_first")]
                        assert (
                            len(projected) == 1
                            and projected[0]["id"] == preceding["items"][-1]["id"]
                        )
                    elif shape in {"recommendation_detail", "pack_source"}:
                        if positive:
                            assert len(projected) == 1 and projected[0]["id"] == body["id"]
                        else:
                            assert not projected
                    elif shape == "pack_parent":
                        # Parent admission is an actual EXISTS over the exact
                        # requested packed source, not an actor-only Boolean.
                        assert len(projected) == 1
                        assert list(projected[0].values()) == [positive]
                        assert path_case["pack"] in public.values()
                    elif shape == "hearing_parent":
                        if positive:
                            expected_parent = visible["hearing"]["id"]
                            assert len(projected) == 1 and projected[0]["id"] == expected_parent
                        else:
                            assert not projected
                    elif shape == "recommendation_parent":
                        assert len(projected) == 1 and next(iter(projected[0].values())) is positive
                    elif shape == "scope":
                        if mode in {"denied_neighbor", "team_removed"}:
                            assert not projected
                        else:
                            assert (
                                len(projected) == 1
                                and projected[0]["id"] == visible["matter"]["id"]
                            )
                    elif shape == "actor":
                        assert len(projected) == 1 and next(iter(projected[0].values())) is True
                    elif shape == "http_membership":
                        expected_member = (
                            visible["auth"]["membership"]["id"]
                            if profile == "owner"
                            else viewer_membership
                        )
                        assert len(projected) == 1 and projected[0]["id"] == expected_member
                    if baseline_rows is None:
                        baseline_rows = projected
                    assert projected == baseline_rows
                    charged = work * occurrences[shape]
                    totals[cost] += charged
                    observed[label] = compact_plan_record(
                        raw,
                        captured_ref,
                        measured=True,
                        index_timing=index_timing,
                        cohort_order=cohort_order,
                    )
                    if work > 400:
                        failures.append({"label": label, "work": work})
                        if canonical_reads:
                            failures.append(
                                {
                                    "label": label,
                                    "work": work,
                                    "cleanCanonicalSourceReads": canonical_reads,
                                }
                            )
            http_row["allActualSQLCount"] = len(captured)
            http_row["allStatementOccurrenceWeightedWork"] = totals
            http_row["aggregateHTTP400Claim"] = False
            http_file.write_text(json.dumps(http_row, indent=2, default=str) + "\n")
            http_inventory.append(
                {"operation": operation, "sqlCount": len(captured), "work": totals}
            )
            attempt["acceptedMeasurementComplete"] = True
            attempt["stage"] = "completed"
            _write_attempt(attempt_file, attempt)
        complete = True
    finally:
        exception_type = sys.exc_info()[0]
        if exception_type is not None and active_attempt is not None:
            active_attempt["failureClass"] = exception_type.__name__
            _write_attempt(active_attempt_file, active_attempt)
        inventory = {label: observed.get(label, pending) for label, pending in expected.items()}
        (tmp_path / "complete-plan-inventory.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "literalJourneys": journeys,
                    "expectedLabels": list(expected),
                    "observed": inventory,
                    "completeHTTPInventory": http_inventory,
                    "complete": complete,
                    "perStatementWorkCap": 400,
                    "perStatementMilliseconds": 5000,
                    "perHTTPRequestStatementCap": 20,
                    "universalOrNativeAcceptanceClaim": False,
                },
                indent=2,
            )
            + "\n"
        )
    assert len(observed) == len(expected) and set(observed) == set(expected)
    assert len(http_inventory) == len(journeys) == 36
    assert not failures, failures


def test_pg_cursor_local_clock_and_required_claims(isolated_postgres_client):
    crypto_contract(isolated_postgres_client)


def test_pg_legacy_identity_and_intelligent_review_boundary(isolated_postgres_client):
    legacy_contract(isolated_postgres_client)


def test_pg_private_success_auth_validation_missing_headers(isolated_postgres_client):
    private_contract(isolated_postgres_client)


def test_pg_private_inactive_actor_headers(isolated_postgres_client):
    inactive_headers_contract(isolated_postgres_client)
