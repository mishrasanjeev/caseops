import { describe, expect, it } from "vitest";

import { displayCell, displayValue, fieldLabel, isInternalIdKey, looksLikeInternalId, readableColumns } from "@/lib/display-value";

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

describe("internal identifiers", () => {
  it("recognises id fields and id-shaped values", () => {
    expect(["id", "docket_id", "recipient_membership_ids", "content_sha256"].every(isInternalIdKey)).toBe(true);
    expect(["docket_title", "identifier_kind", "paid"].some(isInternalIdKey)).toBe(false);
    expect(looksLikeInternalId("0b9c4c1e-6f1d-4a3e-9d55-2f1f6c1e7a10")).toBe(true);
    expect(looksLikeInternalId("a".repeat(64))).toBe(true);
    expect(looksLikeInternalId("TM-421")).toBe(false);
  });

  it("drops id columns by name and by value", () => {
    const rows = [{ docket_id: "d", owner: "0b9c4c1e-6f1d-4a3e-9d55-2f1f6c1e7a10", docket_title: "ASTER" }];
    expect(readableColumns(rows, 10)).toEqual(["docket_title"]);
  });

  it("reads stored codes as words without touching free text", () => {
    expect(displayCell("filing_in_progress")).toBe("Filing in progress");
    expect(displayCell(["word_mark", "TM / 2026 / 1"])).toBe("Word mark, TM / 2026 / 1");
    expect(displayCell("Downloadable legal software")).toBe("Downloadable legal software");
  });
});
