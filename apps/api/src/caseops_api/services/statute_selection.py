"""The one definition of a statutory provision that may be cited or attached.

Routes, drafting, strategy and research all read this module so a provision
is never offered, attached or quoted on a looser test than the write path.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, or_

from caseops_api.db.models import StatuteSection


def selectable_statute_section_sql() -> ColumnElement[bool]:
    """One server-owned definition of an attachable statutory provision."""
    return and_(
        StatuteSection.is_active.is_(True),
        StatuteSection.section_text != "",
        or_(
            StatuteSection.legal_status == "enacted",
            and_(
                StatuteSection.legal_status == "repealed",
                StatuteSection.verification_status == "verified_official",
                StatuteSection.source_policy_json["edition_scope"].as_string()
                == "historical_repealed_law",
            ),
        ),
        StatuteSection.verification_status.in_({"verified_official", "verified_licensed"}),
        StatuteSection.source_sha256 != "",
        StatuteSection.source_publisher != "",
        StatuteSection.issuing_body != "",
        StatuteSection.section_text_fetched_at.is_not(None),
        StatuteSection.exact_source_version != "",
        StatuteSection.source_locator_type == "section_deep_link",
        StatuteSection.link_health_status == "available",
    )


def is_selectable_statute_section(section: StatuteSection) -> bool:
    return bool(
        section.is_active
        and (
            section.legal_status == "enacted"
            or (
                section.legal_status == "repealed"
                and section.verification_status == "verified_official"
                and (section.source_policy_json or {}).get("edition_scope")
                == "historical_repealed_law"
            )
        )
        and section.section_text
        and section.verification_status in {"verified_official", "verified_licensed"}
        and section.source_sha256
        and section.source_publisher
        and section.issuing_body
        and section.section_text_fetched_at
        and section.exact_source_version
        and section.source_locator_type == "section_deep_link"
        and section.link_health_status == "available"
    )
