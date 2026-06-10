import { describe, expect, it } from "vitest";

import CalendarConflictsPage from "./page";

describe("CalendarConflictsPage", () => {
  it("exports the calendar conflict review page", () => {
    expect(CalendarConflictsPage).toBeTypeOf("function");
  });
});
