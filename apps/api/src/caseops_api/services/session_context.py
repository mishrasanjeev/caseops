from __future__ import annotations

from dataclasses import dataclass

from caseops_api.db.models import Company, CompanyMembership, User


@dataclass
class SessionContext:
    company: Company
    user: User
    membership: CompanyMembership
    # Present for request-authenticated contexts. Refresh must re-check this
    # original token timestamp inside the final Membership -> User mint fence;
    # otherwise a password reset can revoke the caller and still lose to a
    # stale refresh that mints a newer, usable token after the cutoff.
    token_issued_at: float | None = None
