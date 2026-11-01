import { describe, expect, it } from "vitest";

import { parseReminderOffsetsHours } from "./reminder-offsets";

describe("parseReminderOffsetsHours (B4-ADJ-19)", () => {
  it("keeps the documented forms instead of dropping them", () => {
    expect(parseReminderOffsetsHours("48, 24")).toEqual({ ok: true, hours: [48, 24] });
    expect(parseReminderOffsetsHours("48h, 24")).toEqual({ ok: true, hours: [48, 24] });
    expect(parseReminderOffsetsHours("72 hours; 2d\n1w, 0")).toEqual({ ok: true, hours: [72, 48, 168, 0] });
  });

  it("rejects a 2d/48h duplicate rather than collapsing it", () => {
    const result = parseReminderOffsetsHours("48h, 2d");
    expect(result.ok).toBe(false);
    expect(!result.ok && result.error).toContain('"2d" repeats an offset of 48 hours');
  });

  it("names the token it cannot read; nothing is silently dropped", () => {
    for (const input of ["48h, soon", "1.5", "-2", "48 24", "2 months"]) {
      const result = parseReminderOffsetsHours(input);
      expect(result.ok, input).toBe(false);
      expect(!result.ok && result.error, input).toMatch(/is not a reminder offset/);
    }
  });

  it("enforces the API bounds before submit", () => {
    expect(parseReminderOffsetsHours("8761")).toMatchObject({ ok: false });
    expect(parseReminderOffsetsHours("8760")).toEqual({ ok: true, hours: [8760] });
    expect(parseReminderOffsetsHours("53w")).toMatchObject({ ok: false });
    expect(parseReminderOffsetsHours(Array.from({ length: 13 }, (_, i) => String(i + 1)).join(","))).toMatchObject({ ok: false });
    expect(parseReminderOffsetsHours(" , ")).toMatchObject({ ok: false });
  });

  it("applies a caller's API bounds and names them", () => {
    expect(parseReminderOffsetsHours("30d", { maxHours: 720, maxCount: 10 })).toEqual({ ok: true, hours: [720] });
    expect(parseReminderOffsetsHours("31d", { maxHours: 720, maxCount: 10 })).toEqual({
      ok: false, error: '"31d" is 744 hours; the most allowed is 720 hours.',
    });
    expect(parseReminderOffsetsHours(Array.from({ length: 11 }, (_, i) => String(i)).join(","), { maxHours: 720, maxCount: 10 }))
      .toEqual({ ok: false, error: "Enter at most 10 reminder offsets; 11 were entered." });
  });
});
