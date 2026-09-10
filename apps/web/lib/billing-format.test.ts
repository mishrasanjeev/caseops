import { describe, expect, it } from "vitest";

import { formatMoneyMinor } from "./billing-format";

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
