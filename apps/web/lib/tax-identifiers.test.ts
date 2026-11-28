import { describe, expect, it } from "vitest";

import {
  GSTIN_FORMAT_MESSAGE,
  GSTIN_STATE_MESSAGE,
  PAN_FORMAT_MESSAGE,
  PAN_GSTIN_MISMATCH_MESSAGE,
  gstinError,
  panError,
} from "./tax-identifiers";

describe("counsel GSTIN / PAN checks (mirror of the portal API)", () => {
  it("accepts blank and well-formed identifiers, ignoring case and spaces", () => {
    expect(gstinError("")).toBeNull();
    expect(gstinError(" 07 aaafk1234q 1z2 ")).toBeNull();
    expect(gstinError("99AAAFK1234Q1Z2")).toBeNull();
    expect(panError("aaafk 1234q", "07AAAFK1234Q1Z2")).toBeNull();
    expect(panError("AAAFK1234Q", "")).toBeNull();
  });

  it.each([
    ["07AAAFK1234Q1Z", GSTIN_FORMAT_MESSAGE],
    ["Not registered", GSTIN_FORMAT_MESSAGE],
    ["07AAAFK1234Q1A2", GSTIN_FORMAT_MESSAGE],
    ["45AAAFK1234Q1Z2", GSTIN_STATE_MESSAGE],
    ["00AAAFK1234Q1Z2", GSTIN_STATE_MESSAGE],
    ["25AAAFK1234Q1Z2", GSTIN_STATE_MESSAGE],
  ])("rejects GSTIN %s", (value, message) => {
    expect(gstinError(value)).toBe(message);
  });

  it("rejects a malformed PAN and a PAN that is not the GSTIN's", () => {
    expect(panError("AAAF1234Q", "")).toBe(PAN_FORMAT_MESSAGE);
    expect(panError("12345ABCDE", "")).toBe(PAN_FORMAT_MESSAGE);
    expect(panError("BBBFK1234Q", "07AAAFK1234Q1Z2")).toBe(PAN_GSTIN_MISMATCH_MESSAGE);
    // An invalid GSTIN is reported on the GSTIN, not as a PAN mismatch.
    expect(panError("BBBFK1234Q", "07AAAFK")).toBeNull();
  });
});
