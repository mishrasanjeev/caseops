"""Types for the runtime data-class projection.

Kept separate from both the generated module and the façade so the generated
file can be pure data: a code generator that also emits class definitions
invites hand-editing of the definitions, and the whole control depends on the
generated file being byte-reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Three states, and the distinction between the last two is the point.
#
#   admitted            reviewed by IPLF-028A and usable in a dry run
#   reviewed_elsewhere  reviewed by another slice (IPLF-027A) but not admitted here
#   unreviewed          inventoried by the repository-wide map, never reviewed
#
# "Unreviewed" must never be reported as "unknown". A caller naming a real table
# that nobody has classified deserves a different answer from one naming a table
# that does not exist, because the remedies differ: review it, versus fix the
# request.
ReviewState = Literal["admitted", "reviewed_elsewhere", "unreviewed"]

# ``stale`` and ``unavailable`` are likewise not the same. Stale means the
# projection was read and disagrees with this build; unavailable means it could
# not be read at all. Neither may ever be reported as ``current``.
ProjectionStatus = Literal["current", "stale", "unavailable"]


@dataclass(frozen=True, slots=True)
class ReviewedDataClass:
    """A data class a human actually classified, with its provenance.

    Only fields with a runtime consumer are carried. The reviewed registries
    hold more (legal_policy_basis, default_retention, the five dispositions);
    projecting all of them would imply the runtime honours them, and it does
    not. What is carried is what the dry run reads.
    """

    id: str
    table_name: str
    source_slice: str
    company_scope: str
    company_key: str | None
    storage: str
    confidentiality: str
    legal_hold_disposition: str


@dataclass(frozen=True, slots=True)
class ProjectionState:
    """Whether the projection can be trusted for this process, and why not."""

    status: ProjectionStatus
    reason: str | None
    detail: str
    observed: tuple[str, ...] = ()

    @property
    def is_current(self) -> bool:
        return self.status == "current"


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    """How much of the inventoried estate has actually been reviewed.

    Exists so "we reviewed 6 of 271" is a number someone can read, rather than
    an absence. A control that silently omits the 265 it never looked at is the
    same reassuring zero this codebase refuses everywhere else.
    """

    admitted: int
    reviewed_elsewhere: int
    unreviewed: int
    unreviewed_ids: tuple[str, ...]
    undeclared_deployed_tables: tuple[str, ...]

    @property
    def reviewed(self) -> int:
        return self.admitted + self.reviewed_elsewhere

    @property
    def total(self) -> int:
        return self.reviewed + self.unreviewed
