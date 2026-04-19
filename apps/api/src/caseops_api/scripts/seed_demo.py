"""CLI: seed a demo tenant with representative matters + supporting data.

Customer demos shouldn't start from a blank screen — open the
matter list and you should see real-looking work in flight.
This script populates an *existing* tenant (you bootstrapped it
via the sign-in flow already) with:

- 5 matters across practice areas (criminal-bail, commercial
  contract dispute, employment 498A defense, real-estate
  specific-performance, IP trademark opposition)
- 1-2 hearings per matter
- 1 outside counsel profile
- 2 GC intake requests
- A pinned note on each matter

Idempotent: re-running skips matters / counsel / intakes that
already exist by their natural key. Safe to run multiple times.

NO drafts are seeded — they require LLM calls and burn budget.
The demo can generate a fresh draft live to show the AI surface.

Usage::

    uv run caseops-seed-demo --tenant sanjeev-demo
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Matter,
    MatterHearing,
    MatterIntakeRequest,
    MatterNote,
    OutsideCounsel,
    User,
)
from caseops_api.db.session import get_session_factory

logger = logging.getLogger("caseops.seed_demo")


# Five matters chosen to span the practice-area surface a real Indian
# firm would carry. Each has enough texture to demo against without
# asking the lawyer to fabricate context on the fly.
@dataclass(frozen=True)
class _MatterSeed:
    code: str
    title: str
    client_name: str
    opposing_party: str
    practice_area: str
    forum_level: str
    court_name: str
    description: str
    note: str
    hearings: tuple[tuple[int, str, str], ...]  # (days_offset, forum_name, purpose)


_MATTER_SEEDS: tuple[_MatterSeed, ...] = (
    _MatterSeed(
        code="DEMO-BAIL-001",
        title="Regular bail — Rahul Verma — cheating under BNS",
        client_name="Rahul Verma",
        opposing_party="State of NCT of Delhi",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "FIR No. 145/2025 P.S. Connaught Place. Offences under BNS "
            "ss.318, 319, 336, 340. Applicant in judicial custody for "
            "65 days; chargesheet not yet filed. Co-accused Ajay Gupta "
            "already on bail on identical footing."
        ),
        note=(
            "Brief partner before Friday — triple-test arguments need "
            "the Sushila Aggarwal angle on prolonged custody."
        ),
        hearings=(
            (3, "Delhi High Court — Court 12", "Listing for arguments"),
            (10, "Delhi High Court — Court 12", "Continuation"),
        ),
    ),
    _MatterSeed(
        code="DEMO-COMM-002",
        title="Specific performance — sale agreement — Kapoor Estates",
        client_name="Kapoor Estates Pvt Ltd",
        opposing_party="Saraswati Builders",
        practice_area="commercial",
        forum_level="high_court",
        court_name="Bombay High Court",
        description=(
            "Suit for specific performance under SRA s.10/16. Sale "
            "agreement dated 12 March 2024 for plot at Andheri West. "
            "Defendant failed to execute conveyance despite full "
            "consideration paid. Limitation expires 11 March 2027."
        ),
        note="Pre-suit notice already issued; readiness-and-willingness affidavit drafted.",
        hearings=(
            (14, "Bombay High Court — Original Side", "First hearing"),
        ),
    ),
    _MatterSeed(
        code="DEMO-EMP-003",
        title="Section 498A defence — Mehta family",
        client_name="Vikas Mehta (and family)",
        opposing_party="Priya Mehta",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Delhi High Court",
        description=(
            "Quashing under BNSS s.528 / Article 226 against FIR No. "
            "92/2025 P.S. Hauz Khas. Allegations under BNS ss.85/86, "
            "former IPC s.498A. Settlement attempted; complainant has "
            "filed an affidavit of no objection."
        ),
        note="Get the Preeti Gupta v State of Jharkhand passage into the petition.",
        hearings=(
            (5, "Delhi High Court — Court 7", "Mention for early listing"),
        ),
    ),
    _MatterSeed(
        code="DEMO-IP-004",
        title="Trademark opposition — Aster vs Astro Foods",
        client_name="Aster Beverages Pvt Ltd",
        opposing_party="Astro Foods Pvt Ltd",
        practice_area="intellectual_property",
        forum_level="tribunal",
        court_name="Trade Marks Registry — Mumbai",
        description=(
            "Opposition to TM application 4892173 in Class 32 (non-"
            "alcoholic beverages). Confusion likely with our prior "
            "registered mark ASTER (TM 3214567) since 2018. Counter-"
            "statement filed; evidence-in-support due."
        ),
        note="Compile sales + advertising evidence by month-end.",
        hearings=(),
    ),
    _MatterSeed(
        code="DEMO-CIV-005",
        title="Recovery suit — outstanding professional fees",
        client_name="Iyer & Co. Chartered Accountants",
        opposing_party="Helios Tech Pvt Ltd",
        practice_area="commercial",
        forum_level="lower_court",
        court_name="District Court, Bangalore Urban",
        description=(
            "Money suit under Order XXXVII for ₹14.6L due against "
            "audit + advisory engagements FY 2023-24. Books of account "
            "and signed statements of account on record. Defendant has "
            "applied for leave to defend."
        ),
        note="File rejoinder to leave-to-defend application — facts are uncontested.",
        hearings=(
            (7, "District Court — Court 3", "Leave to defend hearing"),
        ),
    ),
)


def _resolve_tenant(
    session: Session, *, slug: str
) -> tuple[Company, CompanyMembership, User]:
    company = session.scalar(select(Company).where(Company.slug == slug))
    if company is None:
        raise SystemExit(
            f"no company with slug={slug!r}; bootstrap it first via /sign-in"
        )
    membership = session.scalar(
        select(CompanyMembership)
        .where(CompanyMembership.company_id == company.id)
        .where(CompanyMembership.is_active)
        .order_by(CompanyMembership.created_at.asc())
    )
    if membership is None:
        raise SystemExit(f"no active membership in company {slug!r}")
    user = session.get(User, membership.user_id)
    return company, membership, user


def _seed_matter(
    session: Session,
    *,
    company: Company,
    membership: CompanyMembership,
    seed: _MatterSeed,
) -> tuple[Matter, bool]:
    """Insert the matter (or fetch existing). Returns (matter, created)."""
    existing = session.scalar(
        select(Matter).where(
            Matter.company_id == company.id,
            Matter.matter_code == seed.code,
        )
    )
    if existing is not None:
        return existing, False
    matter = Matter(
        company_id=company.id,
        assignee_membership_id=membership.id,
        matter_code=seed.code,
        title=seed.title,
        client_name=seed.client_name,
        opposing_party=seed.opposing_party,
        practice_area=seed.practice_area,
        forum_level=seed.forum_level,
        court_name=seed.court_name,
        description=seed.description,
        status="active",
    )
    session.add(matter)
    session.flush()
    return matter, True


def _seed_hearings(
    session: Session, *, matter: Matter, seed: _MatterSeed
) -> int:
    """Idempotent — match by (matter, hearing_on, purpose)."""
    today = date.today()
    inserted = 0
    for days, forum_name, purpose in seed.hearings:
        hearing_on = today + timedelta(days=days)
        existing = session.scalar(
            select(MatterHearing).where(
                MatterHearing.matter_id == matter.id,
                MatterHearing.hearing_on == hearing_on,
                MatterHearing.purpose == purpose,
            )
        )
        if existing is not None:
            continue
        session.add(
            MatterHearing(
                matter_id=matter.id,
                hearing_on=hearing_on,
                forum_name=forum_name,
                purpose=purpose,
            )
        )
        # Bump matter.next_hearing_on to the soonest scheduled hearing.
        if matter.next_hearing_on is None or hearing_on < matter.next_hearing_on:
            matter.next_hearing_on = hearing_on
        inserted += 1
    if inserted:
        session.flush()
    return inserted


def _seed_note(
    session: Session,
    *,
    matter: Matter,
    membership: CompanyMembership,
    body: str,
) -> bool:
    """Insert one note if no note with this exact body exists."""
    existing = session.scalar(
        select(MatterNote).where(
            MatterNote.matter_id == matter.id,
            MatterNote.body == body,
        )
    )
    if existing is not None:
        return False
    session.add(
        MatterNote(
            matter_id=matter.id,
            author_membership_id=membership.id,
            body=body,
        )
    )
    session.flush()
    return True


def _seed_outside_counsel(
    session: Session, *, company: Company
) -> bool:
    name = "Anjali Rao & Partners"
    existing = session.scalar(
        select(OutsideCounsel).where(
            OutsideCounsel.company_id == company.id,
            OutsideCounsel.name == name,
        )
    )
    if existing is not None:
        return False
    import json as _json
    session.add(
        OutsideCounsel(
            company_id=company.id,
            name=name,
            primary_contact_name="Anjali Rao",
            primary_contact_email="anjali@raoandpartners.in",
            firm_city="New Delhi",
            jurisdictions_json=_json.dumps(["delhi", "punjab"]),
            practice_areas_json=_json.dumps(["criminal", "constitutional"]),
            panel_status="preferred",
            internal_notes="Fee-cap 8L per matter — pre-approved for bail / quashing work.",
        )
    )
    session.flush()
    return True


def _seed_intakes(
    session: Session,
    *,
    company: Company,
    membership: CompanyMembership,
) -> int:
    seeds = (
        {
            "title": "Review supplier MSA — Helios payment terms",
            "category": "contract_review",
            "priority": "medium",
            "requester_name": "Sunita Iyer",
            "requester_email": "sunita.iyer@example.in",
            "business_unit": "Finance",
            "description": (
                "Helios Tech is renewing the MSA. Need legal sign-off on payment "
                "schedule (Net 60 vs 30) and the new IP-assignment clause."
            ),
        },
        {
            "title": "Employee stock-option scheme — 2026 grant cycle",
            "category": "policy_question",
            "priority": "high",
            "requester_name": "Rajesh Kumar",
            "requester_email": "rajesh.kumar@example.in",
            "business_unit": "People",
            "description": (
                "We're rolling out a fresh ESOP grant. Need vesting + cliff "
                "guidance for India + Singapore residents, and the trustee "
                "communication package."
            ),
        },
    )
    inserted = 0
    for s in seeds:
        existing = session.scalar(
            select(MatterIntakeRequest).where(
                MatterIntakeRequest.company_id == company.id,
                MatterIntakeRequest.title == s["title"],
            )
        )
        if existing is not None:
            continue
        session.add(
            MatterIntakeRequest(
                company_id=company.id,
                submitted_by_membership_id=membership.id,
                title=s["title"],
                category=s["category"],
                priority=s["priority"],
                status="new",
                requester_name=s["requester_name"],
                requester_email=s["requester_email"],
                business_unit=s["business_unit"],
                description=s["description"],
            )
        )
        inserted += 1
    if inserted:
        session.flush()
    return inserted


def run(*, tenant_slug: str) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        company, membership, user = _resolve_tenant(session, slug=tenant_slug)
        del user  # acknowledged but unused in seed

        matters_created = 0
        hearings_created = 0
        notes_created = 0
        for seed in _MATTER_SEEDS:
            matter, was_new = _seed_matter(
                session, company=company, membership=membership, seed=seed,
            )
            matters_created += int(was_new)
            hearings_created += _seed_hearings(session, matter=matter, seed=seed)
            if _seed_note(
                session, matter=matter, membership=membership, body=seed.note,
            ):
                notes_created += 1

        counsel_added = _seed_outside_counsel(session, company=company)
        intake_count = _seed_intakes(session, company=company, membership=membership)

        session.commit()

    sys.stdout.write(
        f"seed-demo into tenant {tenant_slug!r}: "
        f"matters_created={matters_created} "
        f"hearings_created={hearings_created} "
        f"notes_created={notes_created} "
        f"outside_counsel_added={int(counsel_added)} "
        f"intake_requests_created={intake_count}\n"
    )
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-seed-demo")
    parser.add_argument(
        "--tenant", required=True,
        help="Slug of the tenant to seed. Bootstrap it first via /sign-in.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(tenant_slug=args.tenant)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
