"use client";

import { useSession } from "@/lib/use-session";

/** Role IDs come from the API's `MembershipRole` enum. */
export type Role = "owner" | "admin" | "member";

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
  | "matter_access:manage";

const ALL_ROLES: Capability[] = [
  "matters:create",
  "matters:edit",
  "matters:write",
  "time_entries:write",
  "documents:upload",
  "contracts:create",
  "contracts:edit",
  "outside_counsel:recommend",
  "drafts:create",
  "drafts:generate",
  "hearing_packs:generate",
  "recommendations:generate",
  "recommendations:decide",
  "ai:generate",
  "authorities:search",
  "authorities:annotate",
];

const STAFF: Capability[] = [
  "matters:archive",
  "invoices:issue",
  "invoices:send_payment_link",
  "payments:sync",
  "company:manage_profile",
  "company:manage_users",
  "documents:manage",
  "contracts:delete",
  "contracts:manage_rules",
  "outside_counsel:manage",
  "drafts:review",
  "drafts:finalize",
  "hearing_packs:review",
  "court_sync:run",
  "authorities:ingest",
  "workspace:admin",
  "matter_access:manage",
];

const OWNER_ONLY: Capability[] = ["invoices:void", "audit:export"];

const OWNER_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  ...ALL_ROLES,
  ...STAFF,
  ...OWNER_ONLY,
]);

const ADMIN_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  ...ALL_ROLES,
  ...STAFF,
]);

const MEMBER_CAPS: ReadonlySet<Capability> = new Set<Capability>(ALL_ROLES);

const TABLE: Record<Role, ReadonlySet<Capability>> = {
  owner: OWNER_CAPS,
  admin: ADMIN_CAPS,
  member: MEMBER_CAPS,
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
