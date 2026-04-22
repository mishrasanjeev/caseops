import { describe, expect, it } from "vitest";

import { panelStatus } from "@/lib/api/schemas";

describe("panelStatus", () => {
  // Hari-BUG-023 (2026-04-22): the previous Zod enum
  // (preferred|approved|trial|inactive|blocked) didn't match
  // db.models.OutsideCounselPanelStatus (active|preferred|inactive),
  // so every Outside Counsel workspace load threw a Zod parse error
  // on the first profile and the page rendered as "unimplemented"
  // (Hari-BUG-018). This regression pins the enum to the backend
  // contract — if anyone widens or edits OutsideCounselPanelStatus
  // server-side, this test fails first.
  it.each([["active"], ["preferred"], ["inactive"]])(
    "accepts the canonical backend value %s",
    (value) => {
      expect(panelStatus.parse(value)).toBe(value);
    },
  );

  it.each([["approved"], ["trial"], ["blocked"], ["archived"]])(
    "rejects the previously-incorrect value %s so the drift cannot recur",
    (value) => {
      expect(() => panelStatus.parse(value)).toThrow();
    },
  );
});
