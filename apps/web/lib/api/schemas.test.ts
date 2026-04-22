import { describe, expect, it } from "vitest";

import {
  outsideCounselAssignmentStatus,
  outsideCounselSpendStatus,
  panelStatus,
} from "@/lib/api/schemas";

// All three enums below MUST match
// apps/api/src/caseops_api/db/models.py (OutsideCounselPanelStatus,
// OutsideCounselAssignmentStatus, OutsideCounselSpendStatus). The
// 2026-04-22 audit found three independent drifts that each broke
// the Outside Counsel module by failing Zod parse on real backend
// rows. These tests pin every canonical value as accepted and every
// previously-incorrect value as rejected, so the drift cannot
// silently recur even one enum at a time.

describe("panelStatus", () => {
  it.each([["active"], ["preferred"], ["inactive"]])(
    "accepts the canonical backend value %s",
    (value) => {
      expect(panelStatus.parse(value)).toBe(value);
    },
  );

  it.each([
    ["approved"], ["trial"], ["blocked"], ["archived"], ["on_hold"],
  ])(
    "rejects the previously-incorrect value %s so the drift cannot recur",
    (value) => {
      expect(() => panelStatus.parse(value)).toThrow();
    },
  );
});

describe("outsideCounselAssignmentStatus", () => {
  it.each([["proposed"], ["approved"], ["active"], ["closed"]])(
    "accepts the canonical backend value %s",
    (value) => {
      expect(outsideCounselAssignmentStatus.parse(value)).toBe(value);
    },
  );

  it.each([["declined"], ["completed"]])(
    "rejects the previously-incorrect value %s",
    (value) => {
      expect(() => outsideCounselAssignmentStatus.parse(value)).toThrow();
    },
  );
});

describe("outsideCounselSpendStatus", () => {
  it.each([
    ["submitted"], ["approved"], ["partially_approved"],
    ["disputed"], ["paid"],
  ])(
    "accepts the canonical backend value %s",
    (value) => {
      expect(outsideCounselSpendStatus.parse(value)).toBe(value);
    },
  );

  it("accepts partially_approved (the value missing from the prior enum)", () => {
    expect(outsideCounselSpendStatus.parse("partially_approved")).toBe(
      "partially_approved",
    );
  });

  it.each([["rejected"], ["cancelled"]])(
    "rejects the previously-incorrect value %s",
    (value) => {
      expect(() => outsideCounselSpendStatus.parse(value)).toThrow();
    },
  );
});
