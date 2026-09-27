"""Server-owned provider verification fixtures and fresh-evidence replay rules.

Automated production verification may not spend provider credits, so it cannot
repeat a live eCourts lookup. Instead, a small checked-in set of verification
fixtures is refreshed by the scheduled case-tracking job at most once per
Asia/Kolkata calendar day (one paid detail call), and an automated request that
explicitly opts in may be answered from the newest integrity-verified snapshot
of such a fixture - but only while that snapshot is fresh.

Freshness is CaseOps's own rule for tracked cases: provider data retrieved more
than 24 hours ago is stale and is never served. A later provider answer that
contradicts the stored lookup (the case is no longer found, or its data could
not be read) supersedes it. Missing, stale, superseded, tampered or non-fixture
evidence fails closed; nothing here can trigger a provider call. Tenants cannot
add fixtures: the registry is code, reviewed with the release.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from caseops_api.services.case_tracking_providers import ProviderCaseEvent, ProviderCaseSnapshot
from caseops_api.services.hearing_matching import HearingIdentity, normalized

# The same boundary CaseOps uses to label tracked-case provider data fresh/stale.
PROVIDER_EVIDENCE_MAX_AGE = timedelta(hours=24)
# Paid provider calls per fixture per Asia/Kolkata calendar day, failures included.
VERIFICATION_FIXTURE_DAILY_CALL_CAP = 1
VERIFICATION_FIXTURE_OPERATION_TYPE = "verification_fixture"
# Newest fixture operations inspected for a replay decision. One call per day
# means this spans more than a week, and anything older is stale regardless.
REPLAY_HISTORY_LIMIT = 8
# Provider answers about the case itself. A newer one of these means the stored
# lookup no longer reflects what the provider says, so it must not be replayed.
# Availability failures (timeouts, rate limits, billing, outages) say nothing
# about the case and do not supersede earlier evidence.
REPLAY_SUPERSEDING_RESPONSE_CLASSES = frozenset({"case_not_found", "parse_error"})
REPLAY_SERVED = "served"


@dataclass(frozen=True, slots=True)
class ProviderVerificationFixture:
    key: str
    company_slug: str
    provider: str
    cnr: str


PROVIDER_VERIFICATION_FIXTURES: tuple[ProviderVerificationFixture, ...] = (
    # Ram workbook (IV) BUG-032: the Matter's own case reported as "Does not
    # match this Matter". Replayed by the production tester suite, which signs
    # in to the dedicated QA workspace.
    ProviderVerificationFixture(
        key="ram-20260926-bug-032",
        company_slug="caseops-qa",
        provider="ecourtsindia",
        cnr="DLHC010317282019",
    ),
)


def verification_fixture_for(
    *, company_slug: str, provider: str, cnr: str | None
) -> ProviderVerificationFixture | None:
    wanted = normalized(cnr)
    if not wanted:
        return None
    for fixture in PROVIDER_VERIFICATION_FIXTURES:
        if (
            fixture.company_slug == company_slug
            and fixture.provider == provider
            and normalized(fixture.cnr) == wanted
        ):
            return fixture
    return None


def fixtures_for_company(*, company_slug: str, provider: str) -> list[ProviderVerificationFixture]:
    return [
        fixture
        for fixture in PROVIDER_VERIFICATION_FIXTURES
        if fixture.company_slug == company_slug and fixture.provider == provider
    ]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evidence_age(*, captured_at: datetime, now: datetime) -> timedelta:
    return _utc(now) - _utc(captured_at)


def evidence_is_fresh(*, captured_at: datetime, now: datetime) -> bool:
    """Fresh means retrieved at most 24 hours ago, and not in the future."""

    age = evidence_age(captured_at=captured_at, now=now)
    return timedelta(0) <= age <= PROVIDER_EVIDENCE_MAX_AGE


def local_day_start_utc(local_now: datetime) -> datetime:
    """UTC instant at which the caller's local calendar day began."""

    if local_now.tzinfo is None:
        raise ValueError("The daily cap needs a timezone-aware local time.")
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _date(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def _events(rows: object) -> list[ProviderCaseEvent]:
    events: list[ProviderCaseEvent] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            raise ValueError("Stored provider event is malformed.")
        events.append(
            ProviderCaseEvent(
                source_record_key=str(row["source_record_key"]),
                title=str(row["title"]),
                event_date=_date(row.get("event_date")),
                source_url=row.get("source_url"),
                text=row.get("text"),
                # Stored evidence keeps a bounded text preview; say so honestly.
                text_truncated=bool(
                    row.get("text_truncated") or row.get("snapshot_text_preview_truncated")
                ),
                provider_summary=row.get("provider_summary"),
                metadata=dict(row.get("metadata") or {}),
            )
        )
    return events


def snapshot_from_evidence(raw: dict) -> ProviderCaseSnapshot:
    """Rebuild the provider snapshot exactly as the live lookup produced it."""

    identity = raw.get("matching_identity")
    if identity is not None and not isinstance(identity, dict):
        raise ValueError("Stored provider matching identity is malformed.")
    return ProviderCaseSnapshot(
        provider=str(raw["provider"]),
        cnr_number=raw.get("cnr_number"),
        case_number=raw.get("case_number"),
        court_code=raw.get("court_code"),
        court_name=raw.get("court_name"),
        case_title=str(raw["case_title"]),
        party_names=[str(name) for name in raw.get("party_names") or []],
        current_status=raw.get("current_status"),
        current_stage=raw.get("current_stage"),
        next_hearing_on=_date(raw.get("next_hearing_on")),
        orders=_events(raw.get("orders")),
        judgments=_events(raw.get("judgments")),
        hearings=_events(raw.get("hearings")),
        source_url=raw.get("source_url"),
        metadata=dict(raw.get("metadata") or {}),
        matching_identity=(
            HearingIdentity(
                **{
                    key: tuple(value) if key in {"parties", "advocates"} else value
                    for key, value in identity.items()
                }
            )
            if identity is not None
            else None
        ),
    )


__all__ = [
    "PROVIDER_EVIDENCE_MAX_AGE",
    "PROVIDER_VERIFICATION_FIXTURES",
    "REPLAY_HISTORY_LIMIT",
    "REPLAY_SERVED",
    "REPLAY_SUPERSEDING_RESPONSE_CLASSES",
    "VERIFICATION_FIXTURE_DAILY_CALL_CAP",
    "VERIFICATION_FIXTURE_OPERATION_TYPE",
    "ProviderVerificationFixture",
    "evidence_age",
    "evidence_is_fresh",
    "fixtures_for_company",
    "local_day_start_utc",
    "snapshot_from_evidence",
    "verification_fixture_for",
]
