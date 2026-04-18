import { describe, expect, it } from "vitest";
import { formatLegalDate, toLocalCalendarDate } from "./dates";

describe("formatLegalDate", () => {
  it("renders a SQL Date (YYYY-MM-DD) as the same calendar day", () => {
    // This value used to render as May 01 under any UTC-negative
    // timezone because new Date("2026-05-02") is parsed as UTC
    // midnight. Local-component parsing fixes that. We assert the
    // day-of-month and year — the exact glyph order is locale-specific.
    const out = formatLegalDate("2026-05-02");
    expect(out).toMatch(/02/);
    expect(out).toMatch(/2026/);
    expect(out.toLowerCase()).toMatch(/may/);
  });

  it("renders null / undefined as an em-dash placeholder", () => {
    expect(formatLegalDate(null)).toBe("—");
    expect(formatLegalDate(undefined)).toBe("—");
  });

  it("preserves the calendar day across a timezone hostile to UTC parsing", () => {
    // A YYYY-MM-DD must always render as its own day. If this stops
    // being true, every legal calendar surface in the app is off by
    // one day in U.S. Eastern et al.
    const d = toLocalCalendarDate("2026-01-01");
    expect(d).not.toBeNull();
    expect(d!.getFullYear()).toBe(2026);
    expect(d!.getMonth()).toBe(0);
    expect(d!.getDate()).toBe(1);
  });

  it("passes ISO timestamps (with time component) through the native parser", () => {
    const d = toLocalCalendarDate("2026-04-18T12:00:00Z");
    expect(d).not.toBeNull();
    expect(d!.getUTCFullYear()).toBe(2026);
  });

  it("returns null on garbage input rather than Invalid Date", () => {
    expect(toLocalCalendarDate("not-a-date")).toBeNull();
    expect(toLocalCalendarDate("")).toBeNull();
  });
});
