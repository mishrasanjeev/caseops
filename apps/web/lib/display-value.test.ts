import { describe, expect, it } from "vitest";

import { displayValue, fieldLabel } from "@/lib/display-value";

describe("displayValue", () => {
  it("never renders raw JSON for nested values", () => {
    const text = displayValue({ next_deadline: { due_on: "2026-11-20", certainty: "certain" }, classes: [9, 42] });
    expect(text).toBe("Next deadline: Due on: 2026-11-20; Certainty: certain; Classes: 9, 42");
    expect(text).not.toMatch(/[{}"]/);
  });

  it("names empty and boolean values in words", () => {
    expect(displayValue(null)).toBe("Not available");
    expect(displayValue("")).toBe("Not available");
    expect(displayValue([])).toBe("None");
    expect(displayValue({})).toBe("None");
    expect(displayValue(true)).toBe("Yes");
    expect(displayValue(0)).toBe("0");
  });

  it("turns snake_case keys into labels", () => {
    expect(fieldLabel("registration_number")).toBe("Registration number");
  });
});
