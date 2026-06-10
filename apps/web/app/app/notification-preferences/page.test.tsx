import { describe, expect, it } from "vitest";

import NotificationPreferencesPage from "./page";

describe("NotificationPreferencesPage", () => {
  it("exports the notification preferences page", () => {
    expect(NotificationPreferencesPage).toBeTypeOf("function");
  });
});
