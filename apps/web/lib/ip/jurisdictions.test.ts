import { describe, expect, it } from "vitest";

import { ISO_3166_ALPHA_2, canonicalJurisdiction, parseJurisdictions } from "./jurisdictions";

describe("jurisdiction vocabulary (BUG-014)", () => {
  it("normalises typed names to the code a journal entry carries", () => {
    expect(ISO_3166_ALPHA_2).toHaveLength(249);
    expect(canonicalJurisdiction("India")).toBe("IN");
    expect(canonicalJurisdiction(" united  kingdom ")).toBe("GB");
    expect(canonicalJurisdiction("EU")).toBe("EM");
    expect(canonicalJurisdiction("Narnia")).toBeNull();
  });

  it("names every unknown token instead of saving a profile that never matches", () => {
    expect(parseJurisdictions("India, in; WIPO")).toEqual({ codes: ["IN", "WO"], error: null });
    const parsed = parseJurisdictions("India, Narnia, Atlantis");
    expect(parsed.codes).toEqual(["IN"]);
    expect(parsed.error).toMatch(/^"Narnia", "Atlantis" are not recognised jurisdictions\./);
  });
});
