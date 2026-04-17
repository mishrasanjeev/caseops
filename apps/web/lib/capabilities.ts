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
export type Capability =
  | "matters:create"
  | "matters:archive"
  | "invoices:issue"
  | "invoices:send_payment_link"
  | "invoices:void"
  | "company:manage_profile"
  | "company:manage_users"
  | "contracts:create"
  | "contracts:delete"
  | "outside_counsel:manage"
  | "recommendations:generate"
  | "workspace:admin"
  | "audit:export";

const OWNER_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  "matters:create",
  "matters:archive",
  "invoices:issue",
  "invoices:send_payment_link",
  "invoices:void",
  "company:manage_profile",
  "company:manage_users",
  "contracts:create",
  "contracts:delete",
  "outside_counsel:manage",
  "recommendations:generate",
  "workspace:admin",
  "audit:export",
]);

const ADMIN_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  "matters:create",
  "matters:archive",
  "invoices:issue",
  "invoices:send_payment_link",
  "company:manage_profile",
  "company:manage_users",
  "contracts:create",
  "contracts:delete",
  "outside_counsel:manage",
  "recommendations:generate",
  "workspace:admin",
]);

const MEMBER_CAPS: ReadonlySet<Capability> = new Set<Capability>([
  "matters:create",
  "contracts:create",
  "recommendations:generate",
]);

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
