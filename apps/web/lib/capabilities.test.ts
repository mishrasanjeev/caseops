import { describe, expect, it } from "vitest";

import { can, type Capability, type Role } from "./capabilities";

const canonicalIpCapabilities: Capability[] = [
  "ip:read",
  "ip:write",
  "ip:import",
  "ip:approve",
  "ip:filing_prepare",
  "ip:filing_confirm",
  "ip:fees_view",
  "ip:fees_manage",
  "ip:rules_propose",
  "ip:rules_activate",
  "ip:taxonomy_admin",
  "ip:registry_sync",
  "ip:watch_manage",
];

describe("IP capability catalogue", () => {
  it("gives owner and admin every canonical IP capability", () => {
    for (const role of ["owner", "admin"] satisfies Role[]) {
      for (const capability of canonicalIpCapabilities) {
        expect(can(role, capability)).toBe(true);
      }
    }
  });

  it("keeps approval and rules activation at the partner tier", () => {
    expect(can("partner", "ip:approve")).toBe(true);
    expect(can("partner", "ip:filing_confirm")).toBe(true);
    expect(can("partner", "ip:fees_view")).toBe(true);
    expect(can("partner", "ip:rules_activate")).toBe(true);
    expect(can("partner", "ip:import")).toBe(false);
    expect(can("partner", "ip:fees_manage")).toBe(false);
    expect(can("partner", "ip:registry_sync")).toBe(false);
  });

  it("allows operational work but not approval for member and paralegal", () => {
    for (const role of ["member", "paralegal"] satisfies Role[]) {
      expect(can(role, "ip:read")).toBe(true);
      expect(can(role, "ip:write")).toBe(true);
      expect(can(role, "ip:filing_prepare")).toBe(true);
      expect(can(role, "ip:approve")).toBe(false);
      expect(can(role, "ip:filing_confirm")).toBe(false);
    }
  });

  it("keeps viewers read-only and preserves bounded-tail aliases", () => {
    expect(can("viewer", "ip:read")).toBe(true);
    expect(can("viewer", "ip:write")).toBe(false);
    expect(can("viewer", "ip:import")).toBe(false);
    expect(can("viewer", "ip:view")).toBe(can("viewer", "ip:read"));
    expect(can("partner", "ip:review")).toBe(can("partner", "ip:approve"));
    expect(can("partner", "ip:finance")).toBe(can("partner", "ip:fees_view"));
  });
});
