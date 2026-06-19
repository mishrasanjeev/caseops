from __future__ import annotations

from dataclasses import dataclass

from caseops_api.db.models import Company, CompanyMembership, User


@dataclass
class SessionContext:
    company: Company
    user: User
    membership: CompanyMembership
