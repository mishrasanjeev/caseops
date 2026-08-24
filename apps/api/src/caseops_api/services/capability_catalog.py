from __future__ import annotations

from caseops_api.db.models import MembershipRole

_OWNER = MembershipRole.OWNER
_ADMIN = MembershipRole.ADMIN
_PARTNER = MembershipRole.PARTNER
_MEMBER = MembershipRole.MEMBER
_PARALEGAL = MembershipRole.PARALEGAL
_VIEWER = MembershipRole.VIEWER

_ALL_FEE_EARNERS = frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL})
_STAFF = frozenset({_OWNER, _ADMIN, _PARTNER})
_OWNER_ADMIN = frozenset({_OWNER, _ADMIN})
_OWNER_ONLY = frozenset({_OWNER})
_ALL_AUTHENTICATED = frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL, _VIEWER})
CAPABILITY_ROLES: dict[str, frozenset[MembershipRole]] = {
    # --- matter and workspace core ---
    "matters:create": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER}),
    # Bulk import can create hundreds of tenant records and expose import
    # history. Owner/Admin receive it by default; a tenant may delegate this
    # single capability to a custom "Matter Manager" role without granting
    # workspace administration.
    "matters:bulk_import": _OWNER_ADMIN,
    "matters:edit": _ALL_FEE_EARNERS,  # paralegals can edit matter metadata
    "matters:archive": _STAFF,
    "matters:write": _ALL_FEE_EARNERS,
    # --- conflicts (PG-001) --- every fee-earner can run, only staff resolve
    "conflicts:run": _ALL_FEE_EARNERS,
    "conflicts:resolve": _STAFF,
    # --- money --- paralegals + viewers stay out of finance
    "invoices:issue": _STAFF,
    "invoices:send_payment_link": _STAFF,
    "invoices:void": _OWNER_ONLY,
    "payments:sync": _STAFF,
    "time_entries:write": _ALL_FEE_EARNERS,
    # --- company / IAM --- workspace admin stays narrow
    "company:manage_profile": _OWNER_ADMIN,
    "company:manage_users": _OWNER_ADMIN,
    # --- documents + processing ---
    "documents:upload": _ALL_FEE_EARNERS,
    "documents:manage": _STAFF,
    # --- contracts ---
    "contracts:create": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER}),
    "contracts:edit": _ALL_FEE_EARNERS,
    "contracts:delete": _STAFF,
    "contracts:manage_rules": _STAFF,
    # --- outside counsel ---
    "outside_counsel:manage": _STAFF,
    "outside_counsel:recommend": _ALL_FEE_EARNERS,
    # --- drafting --- paralegals can draft but not review/finalize
    "drafts:create": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL}),
    "drafts:edit": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL}),
    "drafts:generate": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL}),
    "drafts:review": _STAFF,
    "drafts:finalize": _STAFF,
    # --- hearing packs ---
    "hearing_packs:generate": _ALL_FEE_EARNERS,
    "hearing_packs:review": _STAFF,
    # --- calendar + notifications (LW-S10) ---
    "calendar:view": _ALL_AUTHENTICATED,
    "calendar:sync": _ALL_FEE_EARNERS,
    "notifications:manage": _OWNER_ADMIN,
    # --- intellectual property operations (PRD Section 2.2) ---
    "ip:read": _ALL_AUTHENTICATED,
    "ip:write": _ALL_FEE_EARNERS,
    "ip:import": _OWNER_ADMIN,
    "ip:approve": _STAFF,
    "ip:filing_prepare": _ALL_FEE_EARNERS,
    "ip:filing_confirm": _STAFF,
    "ip:fees_view": _STAFF,
    "ip:fees_manage": _OWNER_ADMIN,
    "ip:rules_propose": _OWNER_ADMIN,
    "ip:rules_activate": _STAFF,
    "ip:taxonomy_admin": _OWNER_ADMIN,
    "ip:registry_sync": _OWNER_ADMIN,
    "ip:watch_manage": _OWNER_ADMIN,
    # Compatibility aliases for the bounded pre-PRD IP tail. New routes and
    # role templates use the canonical names above; these remain until custom
    # role backfill and mixed-revision proof allow their explicit retirement.
    "ip:view": _ALL_AUTHENTICATED,
    "ip:review": _STAFF,
    "ip:finance": _STAFF,
    # --- court sync --- ops action, not for paralegals
    "court_sync:run": _STAFF,
    # --- recommendations + AI ---
    "recommendations:generate": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER}),
    "recommendations:decide": _STAFF,
    "ai:generate": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL}),
    # MOD-LSE Round-2 P2 #7 (2026-05-03) - dedicated capabilities for the
    # litigation strategy planner. Keep them additive: the recommendations
    # gates above still cover the four classical kinds; the two below
    # gate strategy generation + approval specifically. Roles match the
    # existing recommendations:* pattern (generate is fee-earner, approve
    # is staff) so the role-graph stays coherent.
    "strategy:generate": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER}),
    "strategy:approve": _STAFF,
    # --- authority corpus + tenant overlay --- viewer can read-search only
    "authorities:search": _ALL_AUTHENTICATED,
    "authorities:ingest": _STAFF,
    "authorities:annotate": _ALL_FEE_EARNERS,
    # --- governance ---
    "workspace:admin": _OWNER_ADMIN,
    "audit:export": _OWNER_ONLY,
    "matter_access:manage": _OWNER_ADMIN,
    # --- intake (Sprint 8b BG-025) ---
    # Submit: anyone authenticated so a business-unit manager with
    # only a viewer role can still file a request. Triage + assign:
    # staff (owner/admin/partner). Promote to matter: staff.
    "intake:submit": _ALL_AUTHENTICATED,
    "intake:triage": _STAFF,
    "intake:promote": _STAFF,
    # --- teams (Sprint 8c BG-026) ---
    # Create/edit teams + toggle team_scoping is governance work;
    # everyone authenticated can read who's on what team so staffing
    # and assignment flows don't need a separate gate.
    "teams:manage": _OWNER_ADMIN,
    # --- clients (Sprint S1 MOD-TS-009) ---
    # Anyone authenticated can view the client list (same bar as
    # matters). Create / edit / archive is a fee-earner action -
    # paralegals included; viewers stay read-only.
    "clients:view": _ALL_AUTHENTICATED,
    "clients:create": _ALL_FEE_EARNERS,
    "clients:edit": _ALL_FEE_EARNERS,
    "clients:archive": _STAFF,
    # --- communications log (Phase B / J12 / M11) ---
    # Anyone authenticated can read a matter's communication history
    # (same bar as matters themselves). Write access is fee-earner-
    # gated - paralegals included so they can log a client call -
    # but viewers stay read-only. Slice 2 will keep the same gate
    # for the SendGrid send action.
    "communications:view": _ALL_AUTHENTICATED,
    "communications:write": _ALL_FEE_EARNERS,
    # Email template catalogue is workspace-admin work - same gate
    # as company:manage_users etc. The Compose & send action itself
    # rides on communications:write so any fee-earner can SEND
    # using the templates an admin created.
    "email_templates:manage": _OWNER_ADMIN,
    # KYC lifecycle (Phase B M11 slice 3 - US-037 / FT-049).
    # Submit: any fee-earner can collect docs from a client they
    # know. Review (verify / reject): staff only - partner / admin /
    # owner - to keep a four-eyes pattern between the lawyer who
    # collected the pack and the reviewer who approves it.
    "clients:kyc_submit": _ALL_FEE_EARNERS,
    "clients:kyc_review": _STAFF,
    # Phase C-1 (2026-04-24, MOD-TS-014). Inviting an external party
    # into the workspace is a workspace-admin act - same gate as
    # company:manage_users. Listing/revoking grants follows the same.
    "portal:invite": _OWNER_ADMIN,
    "portal:manage_grants": _OWNER_ADMIN,
}
