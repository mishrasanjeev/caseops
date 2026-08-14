"""Regressions for CaseOps_Bug_list_Ram14Aug2026.xlsx (bulk matter upload).

Root cause shared by BUG-001 and BUG-002: bulk import was strictly stricter
than manual matter creation for the same business object. Manual
``_resolve_forum_selection`` accepts a forum level plus a free-text court name;
bulk ``_resolve_import_forum`` failed closed for every catalog category the
2026-08-11 forum expansion introduced. Production carries 4 DRT and 3
recovery-forum entries for the whole of India, so that gate could never be
closed by improving catalog coverage — a Mumbai DRT matter was unimportable.

BUG-003 is a classification defect: duplicates were already excluded from
creation, but were reported as validation errors, so the UI demanded the user
edit the file. BUG-004 is a vocabulary mismatch: the header aliases accept a
bare "Matter Owner"/"Responsible Lawyer" column, but resolution was email-only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import CompanyMembership, Matter
from caseops_api.db.session import get_session_factory
from caseops_api.services.matter_imports import MATTER_IMPORT_TEMPLATE_FORUMS
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_matter_imports import _create_matter, _invite_user


def _dry_run_rows(client: TestClient, token: str, csv_body: bytes) -> list[dict]:
    response = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(token),
        files={"mapping_file": ("matters.csv", csv_body, "text/csv")},
    )
    assert response.status_code == 200, response.text
    return list(response.json()["rows"])


def test_bulk_import_matches_manual_creation_for_uncatalogued_courts(
    client: TestClient,
) -> None:
    """BUG-001/BUG-002: bulk must accept every forum the manual path accepts."""
    token = str(bootstrap_company(client)["access_token"])
    csv_body = (
        b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
        # Reported verbatim: DRT/DRAT and State Commission with natural names.
        b"DRT natural name,RAM814-01,Commercial,DRAT / DRT,DRT Delhi\n"
        b"DRT no court at all,RAM814-02,Commercial,DRAT / DRT,\n"
        b"State Commission short,RAM814-03,Commercial,State Commission,Delhi State Commission\n"
        b"State Commission no court,RAM814-04,Commercial,State Commission,\n"
        b"Recovery elsewhere,RAM814-05,Commercial,Recovery Forums,Recovery Officer Mumbai\n"
        b"NCLT other bench,RAM814-06,Commercial,NCLAT / NCLT,NCLT Chennai Bench\n"
    )

    rows = _dry_run_rows(client, token, csv_body)

    assert [row["status"] for row in rows] == ["valid"] * 6, [row["errors"] for row in rows]
    # Every category resolves to its canonical level, never None.
    assert [row["forum_level"] for row in rows] == ["tribunal"] * 6
    # The court the user typed survives instead of being discarded.
    assert rows[0]["court_name"] == "DRT Delhi"
    assert rows[1]["court_name"] is None
    # BUG-002 specifically: "Delhi State Commission" still enriches from the
    # full catalog name via scoped token matching, so lineage is not lost.
    assert rows[2]["forum_catalog_entry_id"] == "consumer:scdrc:11070000"
    assert rows[2]["court_name"] == "Delhi State Consumer Disputes Redressal Commission"
    assert rows[2]["forum_consumer_level"] == "state"
    # Ambiguous input must NOT guess a bench: three Delhi DRTs match "DRT Delhi".
    assert rows[0]["forum_catalog_entry_id"] is None


def test_ambiguous_court_does_not_silently_pick_a_bench(client: TestClient) -> None:
    """Failing open must not become guessing: keep free text, drop lineage."""
    token = str(bootstrap_company(client)["access_token"])
    rows = _dry_run_rows(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
        b"Ambiguous DRT,RAM814-AMB,Commercial,DRAT / DRT,DRT\n",
    )
    assert rows[0]["status"] == "valid"
    assert rows[0]["forum_level"] == "tribunal"
    assert rows[0]["court_name"] == "DRT"
    assert rows[0]["forum_catalog_entry_id"] is None
    assert rows[0]["forum_state"] is None


def test_exact_catalog_selection_still_enriches_and_mismatch_still_fails(
    client: TestClient,
) -> None:
    """Failing open must not weaken an explicit catalog ID selection."""
    token = str(bootstrap_company(client)["access_token"])
    rows = _dry_run_rows(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Court,ForumCatalogEntryId\n"
        b"Exact catalog pick,RAM814-EXACT,Commercial,DRAT / DRT,DRT-2,drt:delhi:drt-2\n"
        b"Wrong court for entry,RAM814-WRONG,Commercial,DRAT / DRT,DRT-3,drt:delhi:drt-2\n"
        b"Dead catalog id,RAM814-DEAD,Commercial,DRAT / DRT,DRT-2,drt:delhi:nope\n",
    )
    assert rows[0]["status"] == "valid"
    assert rows[0]["forum_catalog_entry_id"] == "drt:delhi:drt-2"
    assert rows[1]["status"] == "invalid"
    assert "Court does not match the selected forum catalog entry." in rows[1]["errors"]
    assert rows[2]["status"] == "invalid"
    assert "Forum catalog selection is inactive or does not exist." in rows[2]["errors"]


def test_unsupported_forum_gives_actionable_message_not_enum_dump(
    client: TestClient,
) -> None:
    """BUG-001: the reported failure was a raw pydantic Literal error."""
    token = str(bootstrap_company(client)["access_token"])
    rows = _dry_run_rows(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
        b"Unknown forum,RAM814-UNK,Commercial,Interplanetary Court,Somewhere\n"
        b"Family court,RAM814-FAM,Commercial,Family Court,Saket Family Court\n"
        b"Green tribunal,RAM814-NGT,Commercial,National Green Tribunal,NGT Delhi\n",
    )
    assert rows[0]["status"] == "invalid"
    joined = " ".join(rows[0]["errors"])
    # The old message leaked the backend enum to a legal-ops user.
    assert "Input should be" not in joined
    assert "lower_court" not in joined
    assert "Interplanetary Court" in joined
    assert "DRAT / DRT" in joined
    # Real forum families now map onto canonical levels instead of erroring.
    assert rows[1]["status"] == "valid"
    assert rows[1]["forum_level"] == "lower_court"
    assert rows[2]["status"] == "valid"
    assert rows[2]["forum_level"] == "tribunal"


def test_blank_forum_still_reports_required_not_unsupported(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    rows = _dry_run_rows(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
        b"No forum,RAM814-BLANK,Commercial,,\n",
    )
    assert rows[0]["status"] == "invalid"
    assert "Forum level is required." in rows[0]["errors"]
    assert not any("not a supported forum" in error for error in rows[0]["errors"])


def test_duplicates_are_skipped_and_the_original_still_imports(
    client: TestClient,
) -> None:
    """BUG-003: duplicates must be excluded from the submission, not block it.

    The dangerous shape is the in-file duplicate: flagging every copy would
    drop the original too, so the first occurrence must survive.
    """
    token = str(bootstrap_company(client)["access_token"])
    # Bound to a name rather than passed inline: a quoted literal directly
    # after a `token` argument trips the gitleaks generic-api-key heuristic.
    existing_code = "RAM814-EXISTS"
    _create_matter(client, token, existing_code, "Already in the tenant")
    csv_body = (
        b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
        b"Keeper,RAM814-KEEP,Commercial,High Court,Delhi High Court\n"
        b"Keeper,RAM814-KEEP,Commercial,High Court,Delhi High Court\n"
        b"Already in the tenant,RAM814-EXISTS,Commercial,High Court,Delhi High Court\n"
        b"Clean row,RAM814-CLEAN,Commercial,High Court,Delhi High Court\n"
    )

    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={"file": ("dupes.csv", csv_body, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()

    assert [row["status"] for row in job["rows"]] == [
        "valid",
        "duplicate",
        "duplicate",
        "valid",
    ]
    assert job["valid_rows"] == 2
    assert job["duplicate_rows"] == 2
    # Skipped duplicates are not corrections the user has to make.
    assert job["invalid_rows"] == 0
    assert job["validation_error_count"] == 0

    committed = client.post(
        f"/api/matters/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert committed.status_code == 200, committed.text
    result = committed.json()
    assert len(result["created_matter_ids"]) == 2
    assert result["job"]["status"] == "completed"

    with get_session_factory()() as session:
        for code in ("RAM814-KEEP", "RAM814-EXISTS"):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Matter)
                    .where(Matter.matter_code == code)
                )
                == 1
            ), code


def test_duplicate_plus_real_error_stays_invalid(client: TestClient) -> None:
    """A duplicate row with a genuine defect must still demand correction."""
    token = str(bootstrap_company(client)["access_token"])
    rows = _dry_run_rows(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
        b"First,RAM814-MIX,Commercial,High Court,Delhi High Court\n"
        b"First,RAM814-MIX,,High Court,Delhi High Court\n",
    )
    assert rows[0]["status"] == "valid"
    assert rows[1]["status"] == "invalid"
    assert "Practice area is required." in rows[1]["errors"]


def test_all_duplicate_file_reports_nothing_to_create(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    existing_code = "RAM814-ALLDUP"
    _create_matter(client, token, existing_code, "Everything already exists")
    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={
            "file": (
                "dupes.csv",
                b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
                b"Everything already exists,RAM814-ALLDUP,Commercial,High Court,"
                b"Delhi High Court\n",
                "text/csv",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["duplicate_rows"] == 1
    commit = client.post(
        f"/api/matters/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert commit.status_code == 400
    assert "already exists as a matter" in commit.json()["detail"]


def test_owner_and_lawyer_resolve_by_full_name(client: TestClient) -> None:
    """BUG-004: the header aliases accept a name, so resolution must too."""
    token = str(bootstrap_company(client)["access_token"])
    _invite_user(client, token, email="ram-lawyer@asterlegal.in", role="member")
    rows = _dry_run_rows(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Matter Owner,Responsible Lawyer\n"
        b"By full name,RAM814-NAME,Commercial,High Court,Import member,Import member\n"
        b"By work email,RAM814-MAIL,Commercial,High Court,ram-lawyer@asterlegal.in,\n"
        b"Unknown person,RAM814-GHOST,Commercial,High Court,Nobody Here,\n",
    )
    assert rows[0]["status"] == "valid", rows[0]["errors"]
    assert rows[0]["owner_membership_id"]
    assert rows[0]["owner_membership_id"] == rows[0]["responsible_lawyer_membership_id"]
    assert rows[1]["status"] == "valid", rows[1]["errors"]
    assert rows[1]["owner_membership_id"] == rows[0]["owner_membership_id"]
    # An unresolvable reference still fails, naming the value and both forms.
    assert rows[2]["status"] == "invalid"
    message = " ".join(rows[2]["errors"])
    assert "Nobody Here" in message
    assert "work email or full name" in message


def test_ambiguous_person_name_is_rejected_not_guessed(client: TestClient) -> None:
    """Two active users sharing a name must never be silently disambiguated."""
    token = str(bootstrap_company(client)["access_token"])
    for email in ("twin-one@asterlegal.in", "twin-two@asterlegal.in"):
        create = client.post(
            "/api/companies/current/users",
            headers=auth_headers(token),
            json={
                "full_name": "Priya Sharma",
                "email": email,
                "role": "member",
                "password": "ImportPass123!",
            },
        )
        assert create.status_code == 200, create.text

    rows = _dry_run_rows(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Matter Owner\n"
        b"Ambiguous owner,RAM814-TWIN,Commercial,High Court,Priya Sharma\n",
    )
    assert rows[0]["status"] == "invalid"
    assert rows[0]["owner_membership_id"] is None
    message = " ".join(rows[0]["errors"])
    assert "more than one active user" in message
    assert "work email" in message


def test_inactive_user_is_still_rejected_by_name(client: TestClient) -> None:
    """Name resolution must honour the same active filter as email resolution.

    The membership flag is set directly: the employee PATCH route deliberately
    has no ``is_active`` field, and this asserts the resolver's filter rather
    than the offboarding workflow.
    """
    token = str(bootstrap_company(client)["access_token"])
    membership_id, _ = _invite_user(
        client,
        token,
        email="ram-leaver@asterlegal.in",
        role="member",
    )
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.is_active = False
        session.commit()

    rows = _dry_run_rows(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Matter Owner\n"
        b"Offboarded owner,RAM814-GONE,Commercial,High Court,Import member\n",
    )
    assert rows[0]["status"] == "invalid"
    assert rows[0]["owner_membership_id"] is None


# ---------------------------------------------------------------------------
# Structural guards.
#
# These exist because the 2026-08-11 fix created the 2026-08-14 bugs. That fix
# gave the forum hierarchy one server-owned master and made bulk import reject
# "ambiguous/invented" values — but nothing asserted the other direction, so
# bulk import silently became stricter than the manual create path and the
# template's own dropdown started offering values the importer refused.
#
# Parity is a two-way property. Assert it as one.
# ---------------------------------------------------------------------------


def test_every_forum_the_template_offers_can_actually_be_imported(
    client: TestClient,
) -> None:
    """The product must never offer a Forum its own importer rejects."""
    token = str(bootstrap_company(client)["access_token"])

    header = b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
    lines = [
        (
            f"Forum probe {index},TPL-{index:02d},Commercial,{forum},"
            # A plausible hand-typed court that is deliberately NOT a catalog
            # value, which is how a practitioner outside Delhi must file.
            f"{forum} Bench Mumbai\n"
        ).encode()
        for index, forum in enumerate(MATTER_IMPORT_TEMPLATE_FORUMS)
    ]
    rows = _dry_run_rows(client, token, header + b"".join(lines))

    assert len(rows) == len(MATTER_IMPORT_TEMPLATE_FORUMS)
    offending = {
        forum: row["errors"]
        for forum, row in zip(MATTER_IMPORT_TEMPLATE_FORUMS, rows, strict=True)
        if row["status"] != "valid"
    }
    assert not offending, f"template offers unimportable Forum values: {offending}"
    # Each one resolves to a real canonical level, never None.
    assert all(row["forum_level"] for row in rows)


def test_bulk_import_is_never_stricter_than_manual_creation(
    client: TestClient,
) -> None:
    """Whatever POST /api/matters/ accepts, the importer must accept too.

    This is the exact drift that produced BUG-001 and BUG-002: manual creation
    stored ``forum_level=tribunal`` with a free-text court while the importer
    refused the identical payload.
    """
    token = str(bootstrap_company(client)["access_token"])
    probes = [
        ("tribunal", "DRT Delhi"),
        ("tribunal", "Recovery Officer Mumbai"),
        ("lower_court", "Saket District Court"),
        ("high_court", "Bombay High Court, Nagpur Bench"),
        ("supreme_court", "Supreme Court of India"),
        ("arbitration", "SIAC Tribunal"),
        ("advisory", ""),
    ]

    for index, (forum_level, court_name) in enumerate(probes):
        manual = client.post(
            "/api/matters/",
            headers=auth_headers(token),
            json={
                "title": f"Manual parity {index}",
                "matter_code": f"PARITY-M-{index:02d}",
                "practice_area": "Commercial",
                "forum_level": forum_level,
                "court_name": court_name or None,
                "status": "intake",
            },
        )
        assert manual.status_code == 200, (
            f"manual create rejected {forum_level}/{court_name!r}: {manual.text}"
        )

    header = b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
    lines = [
        f"Bulk parity {index},PARITY-B-{index:02d},Commercial,{level},{court}\n".encode()
        for index, (level, court) in enumerate(probes)
    ]
    rows = _dry_run_rows(client, token, header + b"".join(lines))

    rejected = {
        f"{level}/{court}": row["errors"]
        for (level, court), row in zip(probes, rows, strict=True)
        if row["status"] != "valid"
    }
    assert not rejected, f"bulk import is stricter than manual creation: {rejected}"
    assert [row["forum_level"] for row in rows] == [level for level, _ in probes]
