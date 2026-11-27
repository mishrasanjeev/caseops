"""Seed the canonical bench catalogue from official court sources.

Revision ID: 20261127_0006
Revises: 20261127_0002
DATA-GOVERNANCE-MAP: updated (benches purpose and change note; rows only,
no table or column change).
MIGRATION-ROLLBACK: restore-forward. Downgrade removes only the rows this
revision inserted and only while no bench alias points at them; an alias is
curated legal-source lineage and is never deleted to make a downgrade pass.

The ``benches`` table has existed since 20260418_0003 and gained provenance in
20260826_0002, but no migration, seed job or route ever wrote a row. The
curator "Canonical bench" picker therefore had nothing to offer in any
environment, and a bench alias could not be created.

Every seat of a catalogued High Court is a bench row, the principal seat
included: ``bench_aliases.bench_id`` is a required foreign key and nothing
treats "no bench" as the principal seat, so a court that sits only at its
principal seat gets exactly one row, its principal seat.

Sources (only government domains or the court's own official domain):

* Bombay, Rajasthan and Jammu & Kashmir and Ladakh: the court's own website,
  read on 2026-11-27; page wording quoted per row.
* Every other catalogued High Court: the public case-status service of the
  eCourts High Court Services (``hcservices.ecourts.gov.in``, Government of
  India e-Committee), read on 2026-11-28. Choosing a High Court there fills
  its "Bench" select (``cases_qry/index_qry.php`` with
  ``action_code=fillHCBench``); that list is quoted verbatim per row with the
  service's state code. The canonical name normalises the listed wording to
  "Principal Seat [at <city>]" or "Bench at <city>", using only a city the
  list itself names; a court whose list has a single entry has only its
  principal seat.

Courts deliberately not seeded, because no migration creates their
``courts`` row (20260427_0001 says Allahabad and Calcutta were "added later"
by manual seeds, and 20260505_0004 records both as "not yet present as Court
rows in every environment"; Gauhati is in no court seed at all):
Allahabad (eCourts lists "Allahabad High Court" and "Allahabad High Court
Lucknow Bench"), Calcutta ("Original Side", "Appellate side", "Circuit Bench
At Jalpaiguri", "Circuit Bench At Port Blair") and Gauhati ("Principal Seat at
Guwahati", "Kohima Bench", "Aizawl Bench", "Itanagar Bench"). Adding those
parent courts is a court-catalogue decision; until then the curator picker
names any such court as having no catalogued benches. Bombay's "Appellate
Side", "Original Side" and "Special Court (TORTS)" entries are sides of the
principal seat, not seats, and are not benches here.

The parent court of every row must exist: a missing court fails the upgrade
instead of silently dropping its benches. An existing (court, name) row is
left untouched, so the revision is idempotent and never overwrites a reviewed
record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "20261127_0006"
down_revision = "20261127_0002"
branch_labels = None
depends_on = None

_RETRIEVED = "retrieved 2026-11-27"
_BOMBAY = (
    "High Court of Bombay official website",
    "https://bombayhighcourt.gov.in/bhc/",
)
_RAJASTHAN = ("Rajasthan High Court official website", "https://hcraj.nic.in/")
_JAMMU_KASHMIR = (
    "High Court of Jammu & Kashmir and Ladakh official website",
    "https://jkhighcourt.nic.in/",
)
_ECOURTS = (
    "eCourts High Court Services, Government of India",
    "https://hcservices.ecourts.gov.in/hcservices/main.php",
)


def _ecourts_reference(court: str, state_code: int, listed: str, entry: str) -> str:
    return (
        f"Case-status Bench list for '{court}' (state code {state_code}) is "
        f"{listed}; this row is '{entry}'; retrieved 2026-11-28"
    )


# (court_id, eCourts court label, state code, verbatim bench list,
#  ((listed entry, canonical name, seat city or None), ...))
_ECOURTS_LISTS: tuple[
    tuple[str, str, int, str, tuple[tuple[str, str, str | None], ...]], ...
] = (
    (
        "andhra-pradesh-hc", "High Court of Andhra Pradesh", 2,
        "'Principal Bench at Andhra Pradesh' only",
        (("Principal Bench at Andhra Pradesh", "Principal Seat", None),),
    ),
    (
        "chhattisgarh-hc", "High Court of Chhattisgarh", 18,
        "'Principal Bench Chhattisgarh' only",
        (("Principal Bench Chhattisgarh", "Principal Seat", None),),
    ),
    (
        "delhi-hc", "High Court of Delhi", 26,
        "'Principal Bench at Delhi' only",
        (("Principal Bench at Delhi", "Principal Seat at Delhi", "Delhi"),),
    ),
    (
        "gujarat-hc", "High Court of Gujarat", 17,
        "'Gujarat High Court' only",
        (("Gujarat High Court", "Principal Seat", None),),
    ),
    (
        "himachal-hc", "High Court of Himachal Pradesh", 5,
        "'High Court of Himachal Pradesh' only",
        (("High Court of Himachal Pradesh", "Principal Seat", None),),
    ),
    (
        "jharkhand-hc", "High Court of Jharkhand", 7,
        "'Principal Bench Jharkhand' only",
        (("Principal Bench Jharkhand", "Principal Seat", None),),
    ),
    (
        "karnataka-hc", "High Court of Karnataka", 3,
        "'Principal Bench at Bengaluru', 'Bench at Dharwad', 'Bench at Kalburagi'",
        (
            ("Principal Bench at Bengaluru", "Principal Seat at Bengaluru", "Bengaluru"),
            ("Bench at Dharwad", "Bench at Dharwad", "Dharwad"),
            ("Bench at Kalburagi", "Bench at Kalburagi", "Kalburagi"),
        ),
    ),
    (
        "kerala-hc", "High Court of Kerala", 4,
        "'High Court of Kerala' only",
        (("High Court of Kerala", "Principal Seat", None),),
    ),
    (
        "madhya-pradesh-hc", "High Court of Madhya Pradesh", 23,
        "'High Court Of Madhya Pradesh Jabalpur', 'High Court Of Madhya Pradesh "
        "Indore', 'High Court Of Madhya Pradesh Gwalior'",
        (
            ("High Court Of Madhya Pradesh Jabalpur", "Bench at Jabalpur", "Jabalpur"),
            ("High Court Of Madhya Pradesh Indore", "Bench at Indore", "Indore"),
            ("High Court Of Madhya Pradesh Gwalior", "Bench at Gwalior", "Gwalior"),
        ),
    ),
    (
        "madras-hc", "Madras High Court", 10,
        "'Principal Bench of Madras High Court', 'Madurai Bench of Madras High Court'",
        (
            ("Principal Bench of Madras High Court", "Principal Seat", None),
            ("Madurai Bench of Madras High Court", "Bench at Madurai", "Madurai"),
        ),
    ),
    (
        "manipur-hc", "High Court of Manipur", 25,
        "'High Court of Manipur' only",
        (("High Court of Manipur", "Principal Seat", None),),
    ),
    (
        "meghalaya-hc", "High Court of Meghalaya", 21,
        "'High Court of Meghalaya' only",
        (("High Court of Meghalaya", "Principal Seat", None),),
    ),
    (
        "orissa-hc", "High Court of Orissa", 11,
        "'High Court of Orissa' only",
        (("High Court of Orissa", "Principal Seat", None),),
    ),
    (
        "patna-hc", "Patna High Court", 8,
        "'Principal Bench Patna' only",
        (("Principal Bench Patna", "Principal Seat at Patna", "Patna"),),
    ),
    (
        "punjab-hc", "High Court of Punjab and Haryana", 22,
        "'High Court of Punjab and Haryana' only",
        (("High Court of Punjab and Haryana", "Principal Seat", None),),
    ),
    (
        "sikkim-hc", "High Court of Sikkim", 24,
        "'High Court of Sikkim' only",
        (("High Court of Sikkim", "Principal Seat", None),),
    ),
    (
        "telangana-hc", "High Court  for State of Telangana", 29,
        "'Principal Bench at Hyderabad' only",
        (("Principal Bench at Hyderabad", "Principal Seat at Hyderabad", "Hyderabad"),),
    ),
    (
        "tripura-hc", "High Court of Tripura", 20,
        "'High Court of Tripura' only",
        (("High Court of Tripura", "Principal Seat", None),),
    ),
    (
        "uttarakhand-hc", "High Court of Uttarakhand", 15,
        "'High Court of Uttarakhand' only",
        (("High Court of Uttarakhand", "Principal Seat", None),),
    ),
)

# (court_id, bench name, seat city or None when the source does not state it,
#  (source name, source url), source reference)
OFFICIAL_BENCHES: tuple[tuple[str, str, str | None, tuple[str, str], str], ...] = (
    (
        "bombay-hc",
        "Principal Seat at Bombay",
        "Mumbai",
        _BOMBAY,
        "Home-page notice: 'Principal Seat at Bombay and it's Benches at Nagpur and "
        f"Aurangabad'; {_RETRIEVED}",
    ),
    (
        "bombay-hc",
        "Bench at Nagpur",
        "Nagpur",
        _BOMBAY,
        "Home-page notice names the Bench at Nagpur and the bench switcher lists "
        f"Nagpur; {_RETRIEVED}",
    ),
    (
        "bombay-hc",
        "Bench at Aurangabad",
        "Aurangabad",
        _BOMBAY,
        "Home-page notice names the Bench at Aurangabad and the bench switcher lists "
        f"Aurangabad; {_RETRIEVED}",
    ),
    (
        "bombay-hc",
        "High Court of Bombay at Goa",
        None,
        _BOMBAY,
        f"Bench switcher lists Goa; Other Links lists 'High Court of Bombay at Goa'; {_RETRIEVED}",
    ),
    (
        "bombay-hc",
        "Bench at Kolhapur",
        "Kolhapur",
        _BOMBAY,
        f"Bench switcher lists Kolhapur; {_RETRIEVED}",
    ),
    (
        "rajasthan-hc",
        "Principal Seat at Jodhpur",
        "Jodhpur",
        _RAJASTHAN,
        f"Get in Touch: 'Rajasthan High Court Principal Seat Jodhpur'; {_RETRIEVED}",
    ),
    (
        "rajasthan-hc",
        "Bench at Jaipur",
        "Jaipur",
        _RAJASTHAN,
        f"Get in Touch: 'Rajasthan High Court Bench Jaipur'; {_RETRIEVED}",
    ),
    (
        "jammu-kashmir-hc",
        "Jammu Wing",
        "Jammu",
        _JAMMU_KASHMIR,
        f"Case-status menu lists 'Jammu Wing'; {_RETRIEVED}",
    ),
    (
        "jammu-kashmir-hc",
        "Srinagar Wing",
        "Srinagar",
        _JAMMU_KASHMIR,
        f"Case-status menu lists 'Srinagar Wing'; {_RETRIEVED}",
    ),
    (
        "jammu-kashmir-hc",
        "Ladakh Bench",
        None,
        _JAMMU_KASHMIR,
        f"Case-status menu lists 'Ladakh Bench'; {_RETRIEVED}",
    ),
    *(
        (
            court_id,
            name,
            seat_city,
            _ECOURTS,
            _ecourts_reference(label, state_code, listed, entry),
        )
        for court_id, label, state_code, listed, entries in _ECOURTS_LISTS
        for entry, name, seat_city in entries
    ),
)


def bench_id(court_id: str, name: str) -> str:
    """Stable across environments so a replay never duplicates a bench."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"caseops:official-bench:{court_id}:{name}"))


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC)
    court_ids = sorted({court_id for court_id, *_ in OFFICIAL_BENCHES})
    present = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT id FROM courts WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": court_ids},
        )
    }
    missing = [court_id for court_id in court_ids if court_id not in present]
    if missing:
        raise RuntimeError(
            "Bench catalogue parent courts are missing; refusing to drop their "
            f"benches silently: {', '.join(missing)}"
        )
    for court_id, name, seat_city, (source_name, source_url), reference in OFFICIAL_BENCHES:
        existing = bind.execute(
            sa.text("SELECT 1 FROM benches WHERE court_id = :court_id AND name = :name"),
            {"court_id": court_id, "name": name},
        ).first()
        if existing is not None:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO benches (id, court_id, name, seat_city, source_name, "
                "source_url, source_reference, record_version, created_at, updated_at) "
                "VALUES (:id, :court_id, :name, :seat_city, :source_name, :source_url, "
                ":source_reference, 0, :now, :now)"
            ),
            {
                "id": bench_id(court_id, name),
                "court_id": court_id,
                "name": name,
                "seat_city": seat_city,
                "source_name": source_name,
                "source_url": source_url,
                "source_reference": reference,
                "now": now,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for court_id, name, *_ in OFFICIAL_BENCHES:
        bind.execute(
            sa.text(
                "DELETE FROM benches WHERE id = :id AND NOT EXISTS "
                "(SELECT 1 FROM bench_aliases WHERE bench_aliases.bench_id = benches.id)"
            ),
            {"id": bench_id(court_id, name)},
        )
