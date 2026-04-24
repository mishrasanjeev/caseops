"use client";

import { useSession } from "@/lib/use-session";

/** Role IDs come from the API's `MembershipRole` enum. Sprint 8b
 * widened this taxonomy from 3 to 6; the capability rows below match
 * apps/api/src/caseops_api/api/dependencies.py CAPABILITY_ROLES.
 */
export type Role =
  | "owner"
  | "admin"
  | "partner"
  | "member"
  | "paralegal"
  | "viewer";

/**
 * Capabilities are a finite, enumerated set. Anything rendered in the app
 * shell gates on one of these. The server is still the source of truth — we
 * do not trust the client to enforce authorization. This map exists so the
 * UI does not dangle actions that the backend would immediately refuse.
 *
 * The names align roughly with the backend role checks in
 * `apps/api/src/caseops_api/services/*`. When the capability grid in the
 * API changes, update this map in the same PR.
 */
// Mirror of apps/api/src/caseops_api/api/dependencies.py CAPABILITY_ROLES.
// Keep these in sync — the backend is the source of truth, but a
// drifted UI table shows actions the server will refuse. The Python
// role-guard lint walks the live OpenAPI shape, so the API side is
// policed automatically; this file is hand-maintained.
export type Capability =
  // matter + workspace
  | "matters:create"
  | "matters:edit"
  | "matters:archive"
  | "matters:write"
  // money
  | "invoices:issue"
  | "invoices:send_payment_link"
  | "invoices:void"
  | "payments:sync"
  | "time_entries:write"
  // company / IAM
  | "company:manage_profile"
  | "company:manage_users"
  // documents
  | "documents:upload"
  | "documents:manage"
  // contracts
  | "contracts:create"
  | "contracts:edit"
  | "contracts:delete"
  | "contracts:manage_rules"
  // outside counsel
  | "outside_counsel:manage"
  | "outside_counsel:recommend"
  // drafting
  | "drafts:create"
  | "drafts:generate"
  | "drafts:review"
  | "drafts:finalize"
  // hearing packs
  | "hearing_packs:generate"
  | "hearing_packs:review"
  // court sync
  | "court_sync:run"
  // recommendations + AI
  | "recommendations:generate"
  | "recommendations:decide"
  | "ai:generate"
  // authority corpus
  | "authorities:search"
  | "authorities:ingest"
  | "authorities:annotate"
  // governance
  | "workspace:admin"
  | "audit:export"
  | "matter_access:manage"
  // intake (Sprint 8b BG-025)
  | "intake:submit"
  | "intake:triage"
  | "intake:promote"
  // teams (Sprint 8c BG-026)
  | "teams:manage"
  // clients (Sprint S1 — MOD-TS-009)
  | "clients:view"
  | "clients:create"
  | "clients:edit"
  | "clients:archive"
  // communications log (Phase B / J12 / M11)
  | "communications:view"
  | "communications:write"
  // email templates admin (Phase B M11 slice 2)
  | "email_templates:manage"
  // KYC lifecycle (Phase B M11 slice 3 — US-037)
  | "clients:kyc_submit"
  | "clients:kyc_review"
  // Phase C-1 (2026-04-24, MOD-TS-014) — portal admin
  | "portal:invite"
  | "portal:manage_grants";

// Baseline caps for a fee-earner (owner / admin / partner / member).
// Paralegals inherit most of these but lose a small, explicit set.
const FEE_EARNER: Capability[] = [
  "matters:edit",
  "matters:write",
  "time_entries:write",
  "documents:upload",
  "contracts:edit",
  "outside_counsel:recommend",
  "hearing_packs:generate",
  "ai:generate",
  "authorities:search",
  "authorities:annotate",
  // clients (Sprint S1 MOD-TS-009) — everyone who can touch matters
  // can manage clients; archive is staff-only.
  "clients:view",
  "clients:create",
  "clients:edit",
  // communications (Phase B M11 slice 1) — fee-earners can log a
  // call/email/meeting against a matter. Read access is widened
  // to viewers via VIEWER_CAPS below.
  "communications:view",
  "communications:write",
  // KYC submit (Phase B M11 slice 3) — any fee-earner can submit
  // a KYC pack for a client they know. Reviewing (verify/reject)
  // is staff-only — see STAFF below for kyc_review.
  "clients:kyc_submit",
];

// Creator caps — paralegals can NOT create matters/contracts or run
// recommendations end-to-end.
const CREATOR_ONLY: Capability[] = [
  "matters:create",
  "contracts:create",
  "recommendations:generate",
];

// Drafter caps — paralegals CAN draft but not finalize.
const DRAFTER: Capability[] = ["drafts:create", "drafts:generate"];

// Ops-lead caps — owner / admin / partner only.
const STAFF: Capability[] = [
  "matters:archive",
  "invoices:issue",
  "invoices:send_payment_link",
  "payments:sync",
  "documents:manage",
  "contracts:delete",
  "contracts:manage_rules",
  "outside_counsel:manage",
  "drafts:review",
  "drafts:finalize",
  "hearing_packs:review",
  "court_sync:run",
  "authorities:ingest",
  "recommendations:decide",
  "intake:triage",
  "intake:promote",
  "clients:archive",
  // KYC review — staff only (four-eyes between collector and approver).
  "clients:kyc_review",
];

// Governance caps — owner / admin only.
const GOVERNANCE: Capability[] = [
  "company:manage_profile",
  "company:manage_users",
  "workspace:admin",
  "matter_access:manage",
  "teams:manage",
  // Email templates editor sits next to Teams admin.
  "email_templates:manage",
  // Phase C-1 (2026-04-24, MOD-TS-014) — invite + manage portal users.
  // Owner/admin only — same gate as company:manage_users.
  "portal:invite",
  "portal:manage_grants",
];

// Owner-only caps.
const OWNER_ONLY: Capability[] = ["invoices:void", "audit:export"];

const VIEWER_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  "authorities:search",
  "intake:submit",
  "clients:view",
  "communications:view",
]);

const PARALEGAL_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  ...FEE_EARNER,
  ...DRAFTER,
  "intake:submit",
]);

const MEMBER_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  ...FEE_EARNER,
  ...CREATOR_ONLY,
  ...DRAFTER,
  "intake:submit",
]);

const PARTNER_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  ...FEE_EARNER,
  ...CREATOR_ONLY,
  ...DRAFTER,
  ...STAFF,
  "intake:submit",
]);

const ADMIN_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  ...FEE_EARNER,
  ...CREATOR_ONLY,
  ...DRAFTER,
  ...STAFF,
  ...GOVERNANCE,
  "intake:submit",
]);

const OWNER_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  ...FEE_EARNER,
  ...CREATOR_ONLY,
  ...DRAFTER,
  ...STAFF,
  ...GOVERNANCE,
  ...OWNER_ONLY,
  "intake:submit",
]);

const TABLE: Record<Role, ReadonlySet<Capability>> = {
  owner: OWNER_CAPS,
  admin: ADMIN_CAPS,
  partner: PARTNER_CAPS,
  member: MEMBER_CAPS,
  paralegal: PARALEGAL_CAPS,
  viewer: VIEWER_CAPS,
};

export function can(role: Role | null | undefined, capability: Capability): boolean {
  if (!role) return false;
  return TABLE[role]?.has(capability) ?? false;
}

export function useCapability(capability: Capability): boolean {
  const session = useSession();
  const role = (session.context?.membership.role ?? null) as Role | null;
  return can(role, capability);
}

export function useRole(): Role | null {
  const session = useSession();
  return (session.context?.membership.role ?? null) as Role | null;
}
