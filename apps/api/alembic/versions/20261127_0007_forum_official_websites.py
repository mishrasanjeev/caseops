"""Official websites for catalogued courts and tribunals.

Revision ID: 20261127_0007
Revises: 20261127_0006
DATA-GOVERNANCE-MAP: updated
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before any DDL, like the
heads below it. The two columns are nullable public reference data on the
shared forum catalogue; to withdraw a link, set its official_website_url to
null in a later revision.

Every court badge (matter overview, matter list, hearings, client and counsel
portals) opens the forum's official website, resolved through the matter's
canonical catalogue identity. This revision adds the address and the source
that confirmed it to the shared ``forum_catalog_entries`` table (no tenant
data; the table has no company_id by design).

Sources, all fetched on 2026-11-27:

* Supreme Court and High Courts: the eCourts High Courts directory
  ``https://ecourts.gov.in/ecourts2.0/?p=about_us/highcourts`` (Government of
  India e-Committee). Where the court's own home page loaded, its title was
  checked as well. Two exceptions are recorded per row: Bombay High Court has
  moved to ``bombayhighcourt.gov.in`` (its own home page, title "Bombay High
  Court - Home Page"; the directory still lists the retired nic.in host), and
  Himachal Pradesh is confirmed by the eCourts services list
  ``https://hcservices.ecourts.gov.in/hcservices/static/highcourts.php``.
* Allahabad High Court is deliberately left unmapped: its official site
  (allahabadhighcourt.in) is not on a government domain, and only government
  domains are linked. It renders as plain text until the owner decides.
* NCLAT, NCLT, TDSAT, the Appellate Tribunal under SAFEMA (which also hears
  NDPS, PMLA and FEMA appeals, per its About page) and NCDRC: each tribunal's
  own home page.
* DRT/DRAT and the Delhi recovery forums: the Department of Financial Services
  DRT/DRAT page ``https://financialservices.gov.in/drt-drat``, which links the
  DRT portal.
* District courts: the per-court site that the India.gov.in District Courts
  Contact Directory lists, already stored as each row's ``source_url`` by
  revision 20260624_0001; only https addresses on ``*.dcourts.gov.in`` are
  copied.

State and district consumer commissions are not mapped: their catalogue
sources are e-Jagriti API endpoints, not commission websites.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

import sqlalchemy as sa

from alembic import op

revision = "20261127_0007"
down_revision = "20261127_0006"
branch_labels = None
depends_on = None

_ECOURTS_HIGH_COURTS = "https://ecourts.gov.in/ecourts2.0/?p=about_us/highcourts"
_HCSERVICES_HIGH_COURTS = "https://hcservices.ecourts.gov.in/hcservices/static/highcourts.php"
_DFS_DRT = "https://financialservices.gov.in/drt-drat"
_INDIA_GOV_DISTRICT_COURTS = "https://www.india.gov.in/directory/contact-directory/district-courts"

# catalogue id -> (official website, source that confirmed it)
OFFICIAL_WEBSITES: dict[str, tuple[str, str]] = {
    "sc:india": ("https://www.sci.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:andhra-pradesh": ("https://aphc.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:bihar": ("https://patnahighcourt.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:bombay": ("https://bombayhighcourt.gov.in/", "https://bombayhighcourt.gov.in/bhc/"),
    "hc:chhattisgarh": ("https://highcourt.cg.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:delhi": ("https://delhihighcourt.nic.in/", _ECOURTS_HIGH_COURTS),
    "hc:gujarat": ("https://gujarathighcourt.nic.in/", _ECOURTS_HIGH_COURTS),
    "hc:himachal-pradesh": ("https://highcourt.hp.gov.in/", _HCSERVICES_HIGH_COURTS),
    "hc:jammu-kashmir-ladakh": ("https://jkhighcourt.nic.in/", _ECOURTS_HIGH_COURTS),
    "hc:jharkhand": ("https://jharkhandhighcourt.nic.in/", _ECOURTS_HIGH_COURTS),
    "hc:karnataka": ("https://judiciary.karnataka.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:kerala": ("https://highcourt.kerala.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:madhya-pradesh": ("https://mphc.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:madras": ("https://hcmadras.tn.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:manipur": ("https://hcmimphal.nic.in/", _ECOURTS_HIGH_COURTS),
    "hc:meghalaya": ("https://meghalayahighcourt.nic.in/", _ECOURTS_HIGH_COURTS),
    "hc:orissa": ("https://www.orissahighcourt.nic.in/", _ECOURTS_HIGH_COURTS),
    "hc:punjab-haryana": ("https://highcourtchd.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:rajasthan": ("https://hcraj.nic.in/", _ECOURTS_HIGH_COURTS),
    "hc:sikkim": ("https://hcs.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:telangana": ("https://tshc.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:tripura": ("https://thc.nic.in/", _ECOURTS_HIGH_COURTS),
    "hc:uttarakhand": ("https://highcourtofuttarakhand.gov.in/", _ECOURTS_HIGH_COURTS),
    "hc:calcutta": ("https://www.calcuttahighcourt.gov.in/", _ECOURTS_HIGH_COURTS),
    "company-law:nclat": ("https://nclat.nic.in/", "https://nclat.nic.in/"),
    "company-law:nclt": ("https://nclt.gov.in/", "https://nclt.gov.in/"),
    "tdsat:delhi": ("https://tdsat.gov.in/", "https://tdsat.gov.in/"),
    "appellate-tribunal:ed": ("https://atfp.gov.in/", "https://atfp.gov.in/about.html"),
    "appellate-tribunal:fema": ("https://atfp.gov.in/", "https://atfp.gov.in/about.html"),
    "appellate-tribunal:ndps": ("https://atfp.gov.in/", "https://atfp.gov.in/about.html"),
    "consumer:ncdrc": ("https://ncdrc.nic.in/", "https://ncdrc.nic.in/"),
    "drt:delhi:drat": ("https://drt.gov.in/", _DFS_DRT),
    "drt:delhi:drt-1": ("https://drt.gov.in/", _DFS_DRT),
    "drt:delhi:drt-2": ("https://drt.gov.in/", _DFS_DRT),
    "drt:delhi:drt-3": ("https://drt.gov.in/", _DFS_DRT),
    "recovery:delhi:po-court": ("https://drt.gov.in/", _DFS_DRT),
    "recovery:delhi:registrar-court": ("https://drt.gov.in/", _DFS_DRT),
    "recovery:delhi:recovery-officer-court": ("https://drt.gov.in/", _DFS_DRT),
}


def _catalog_table() -> sa.Table:
    return sa.table(
        "forum_catalog_entries",
        sa.column("id", sa.String),
        sa.column("source_url", sa.String),
        sa.column("official_website_url", sa.String),
        sa.column("official_website_source_url", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _is_district_court_site(value: str | None) -> bool:
    if not value:
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and host.endswith(".dcourts.gov.in")
        and not parts.query
        and not parts.fragment
        and not parts.username
    )


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    with op.batch_alter_table("forum_catalog_entries") as batch:
        batch.add_column(sa.Column("official_website_url", sa.String(length=500), nullable=True))
        batch.add_column(
            sa.Column("official_website_source_url", sa.String(length=500), nullable=True)
        )

    conn = op.get_bind()
    table = _catalog_table()
    now = datetime.now(UTC)
    for entry_id, (url, source) in OFFICIAL_WEBSITES.items():
        conn.execute(
            table.update()
            .where(table.c.id == entry_id)
            .values(official_website_url=url, official_website_source_url=source, updated_at=now)
        )
    rows = conn.execute(
        sa.select(table.c.id, table.c.source_url).where(table.c.id.like("district:india-gov:%"))
    ).all()
    for entry_id, source_url in rows:
        if _is_district_court_site(source_url):
            conn.execute(
                table.update()
                .where(table.c.id == entry_id)
                .values(
                    official_website_url=source_url,
                    official_website_source_url=_INDIA_GOV_DISTRICT_COURTS,
                    updated_at=now,
                )
            )


def downgrade() -> None:
    raise RuntimeError("Forum official websites are public reference data; restore-forward only.")
