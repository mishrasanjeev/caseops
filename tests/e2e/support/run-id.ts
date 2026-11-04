import { randomBytes } from "node:crypto";

/**
 * Identifier for the names a journey writes into a tenant. Production tenants
 * retain every run, and a UUID-shaped name reads as a leaked internal id to
 * every later screen check (2026-11-03: retained "IP18 <uuid> missing 50"
 * docket titles failed BUG-014's hit-screen check). Clock plus random hex stays
 * unique across workers and runs, slug-safe and visibly synthetic.
 */
export const RUN_ID = /^\d{8}-\d{6}-[0-9a-f]{6}$/;

export function runId(): string {
  const clock = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  return `${clock.slice(0, 8)}-${clock.slice(8)}-${randomBytes(3).toString("hex")}`;
}
