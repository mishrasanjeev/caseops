from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import joinedload

from caseops_api.core.settings import get_settings
from caseops_api.db.migrations import run_migrations
from caseops_api.db.models import AuthorityDocument, CompanyMembership, MembershipRole
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.authorities import AuthorityIngestionRequest
from caseops_api.schemas.companies import BootstrapCompanyRequest
from caseops_api.services.authorities import ingest_authority_source
from caseops_api.services.authority_sources import list_supported_authority_sources
from caseops_api.services.identity import SessionContext, register_company_owner

DEFAULT_SOURCES = [
    "supreme_court_latest_orders",
    "delhi_high_court_recent_judgments",
    "bombay_high_court_recent_orders_judgments",
    "karnataka_high_court_latest_judgments",
    "telangana_high_court_judgments",
    "madras_high_court_operational_orders",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Populate the local CaseOps authority corpus from official public sources."
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        default=DEFAULT_SOURCES,
        help="Authority sources to ingest. Defaults to the priority launch courts.",
    )
    parser.add_argument(
        "--max-documents",
        type=int,
        default=8,
        help="Maximum documents to pull per source.",
    )
    parser.add_argument(
        "--company-slug",
        default="caseops-seed",
        help="Slug for the local seed company used to authorize ingestion.",
    )
    parser.add_argument(
        "--company-name",
        default="CaseOps Seed Company",
        help="Display name for the local seed company.",
    )
    parser.add_argument(
        "--owner-name",
        default="CaseOps Seed Owner",
        help="Owner full name for the local seed company.",
    )
    parser.add_argument(
        "--owner-email",
        default="seed-owner@caseops.ai",
        help="Owner email for the local seed company.",
    )
    parser.add_argument(
        "--owner-password",
        default="SeedOwnerPass!2026",
        help="Owner password for the local seed company.",
    )
    return parser.parse_args()


def build_context(
    *,
    company_slug: str,
    company_name: str,
    owner_name: str,
    owner_email: str,
    owner_password: str,
) -> SessionContext:
    session_factory = get_session_factory()
    with session_factory() as session:
        membership = session.scalar(
            select(CompanyMembership)
            .options(
                joinedload(CompanyMembership.company),
                joinedload(CompanyMembership.user),
            )
            .where(
                CompanyMembership.role == MembershipRole.OWNER,
                CompanyMembership.company.has(slug=company_slug),
            )
        )

        if membership is None:
            register_company_owner(
                session,
                BootstrapCompanyRequest(
                    company_name=company_name,
                    company_slug=company_slug,
                    company_type="law_firm",
                    owner_full_name=owner_name,
                    owner_email=owner_email,
                    owner_password=owner_password,
                ),
            )
            membership = session.scalar(
                select(CompanyMembership)
                .options(
                    joinedload(CompanyMembership.company),
                    joinedload(CompanyMembership.user),
                )
                .where(
                    CompanyMembership.role == MembershipRole.OWNER,
                    CompanyMembership.company.has(slug=company_slug),
                )
            )

        if membership is None:
            raise RuntimeError("Could not establish a local owner context for authority ingestion.")

        session.expunge(membership.company)
        session.expunge(membership.user)
        session.expunge(membership)
        return SessionContext(
            company=membership.company,
            user=membership.user,
            membership=membership,
        )


def summarize_corpus() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        documents = list(session.scalars(select(AuthorityDocument)))
        print(f"\nAuthority corpus contains {len(documents)} document(s).")
        by_source = Counter(document.source for document in documents)
        by_court = Counter(document.court_name for document in documents)
        if by_source:
            print("By source:")
            for source, count in sorted(by_source.items()):
                print(f"  - {source}: {count}")
        if by_court:
            print("By court:")
            for court_name, count in sorted(by_court.items()):
                print(f"  - {court_name}: {count}")


def _resolve_sqlite_path(database_url: str) -> Path | None:
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("sqlite"):
        return None
    database = parsed.database
    if not database:
        return None
    path = Path(database)
    return path if path.is_absolute() else Path.cwd() / path


def _is_legacy_local_database(db_path: Path) -> bool:
    if not db_path.exists():
        return False

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table'"
            ).fetchall()
        }
        if "companies" not in tables:
            return False

        company_columns = {
            row[1]
            for row in connection.execute("pragma table_info(companies)").fetchall()
        }
        required_company_columns = {
            "primary_contact_email",
            "billing_contact_name",
            "billing_contact_email",
            "headquarters",
            "practice_summary",
        }
        if not required_company_columns.issubset(company_columns):
            return True

        return "authority_documents" not in tables


def prepare_database_for_population(database_url: str) -> Path | None:
    db_path = _resolve_sqlite_path(database_url)
    if db_path is None or not _is_legacy_local_database(db_path):
        return None

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}.legacy-{timestamp}{db_path.suffix}")
    db_path.replace(backup_path)
    return backup_path


def main() -> None:
    args = parse_args()
    supported_sources = {adapter.source for adapter in list_supported_authority_sources()}
    unsupported_sources = sorted(set(args.sources) - supported_sources)
    if unsupported_sources:
        raise SystemExit(
            "Unsupported authority source(s): "
            + ", ".join(unsupported_sources)
        )

    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        raise SystemExit(
            "CaseOps local authority population must target PostgreSQL/pgvector-aligned storage. "
            "Set CASEOPS_DATABASE_URL to your local Postgres DSN before running this command."
        )
    print(f"Using database: {settings.database_url}")
    backup_path = prepare_database_for_population(settings.database_url)
    if backup_path is not None:
        print(f"Backed up legacy local database to: {backup_path}")
    run_migrations()
    context = build_context(
        company_slug=args.company_slug,
        company_name=args.company_name,
        owner_name=args.owner_name,
        owner_email=args.owner_email,
        owner_password=args.owner_password,
    )

    session_factory = get_session_factory()
    with session_factory() as session:
        for source in args.sources:
            print(f"\nPulling {source}...")
            run = ingest_authority_source(
                session,
                context=context,
                payload=AuthorityIngestionRequest(
                    source=source,
                    max_documents=args.max_documents,
                ),
            )
            print(
                f"  status={run.status} imported={run.imported_document_count} "
                f"adapter={run.adapter_name}"
            )
            if run.summary:
                print(f"  summary={run.summary}")

    summarize_corpus()


if __name__ == "__main__":
    main()
