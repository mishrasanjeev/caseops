import { describe, expect, it } from "vitest";

import { addOnAvailability, addOnAvailableOn, formatMoneyMinor } from "./billing-format";

describe("formatMoneyMinor", () => {
  it("preserves the existing whole-unit default", () => {
    expect(formatMoneyMinor(155, "INR")).toBe("₹2");
    expect(formatMoneyMinor(null, "INR")).toBe("Custom");
  });

  it("retains provider minor units without adding unnecessary decimals", () => {
    expect(formatMoneyMinor(15, "INR", 2)).toBe("₹0.15");
    expect(formatMoneyMinor(7, "INR", 2)).toBe("₹0.07");
    expect(formatMoneyMinor(2500, "INR", 2)).toBe("₹25");
    expect(formatMoneyMinor(99978, "INR", 2)).toBe("₹999.78");
    expect(formatMoneyMinor(0, "INR", 2)).toBe("₹0");
  });
});

describe("add-on availability", () => {
  const ipWorkspace = { eligible_segments: ["firm", "gc"] };

  it("offers a segment-restricted add-on only on the listed segments", () => {
    expect(addOnAvailableOn(ipWorkspace, "firm")).toBe(true);
    expect(addOnAvailableOn(ipWorkspace, "gc")).toBe(true);
    expect(addOnAvailableOn(ipWorkspace, "solo")).toBe(false);
    expect(addOnAvailableOn(ipWorkspace, "trial")).toBe(false);
    expect(addOnAvailableOn(ipWorkspace, undefined)).toBe(false);
    expect(addOnAvailability(ipWorkspace)).toBe("Firm and GC plans only");
  });

  it("treats an add-on without a rule as available on every plan", () => {
    expect(addOnAvailableOn({ eligible_segments: null }, "solo")).toBe(true);
    expect(addOnAvailableOn({}, undefined)).toBe(true);
    expect(addOnAvailability({})).toBe("Every plan");
  });
});
