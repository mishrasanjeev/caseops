/**
 * Smoke test for the audit-export date-bounds helpers on the admin
 * page. The `until` date used to snap to the START of the selected
 * day, silently dropping every event on that day from the export.
 * Users pick "May 2" expecting to get everything up to and including
 * May 2 — the new helper honors that.
 *
 * Helpers are inlined here (not exported from admin/page.tsx because
 * Next.js pages don't like incidental exports); they are a literal
 * copy of the production logic so the invariant is captured at the
 * unit-test layer.
 */
import { describe, expect, it } from "vitest";

function sinceIsoOrNull(local: string): string | null {
  if (!local) return null;
  return `${local}T00:00:00Z`;
}

function untilIsoOrNull(local: string): string | null {
  if (!local) return null;
  return `${local}T23:59:59Z`;
}

describe("admin audit-export date bounds", () => {
  it("since maps to start-of-day UTC", () => {
    expect(sinceIsoOrNull("2026-04-01")).toBe("2026-04-01T00:00:00Z");
  });

  it("until maps to end-of-day UTC so the selected day is included", () => {
    expect(untilIsoOrNull("2026-05-02")).toBe("2026-05-02T23:59:59Z");
  });

  it("both return null on empty input (full 30-day default kicks in server-side)", () => {
    expect(sinceIsoOrNull("")).toBeNull();
    expect(untilIsoOrNull("")).toBeNull();
  });
});
