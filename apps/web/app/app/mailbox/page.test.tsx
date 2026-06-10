import { describe, expect, it } from "vitest";

import MailboxPage from "./page";

describe("MailboxPage", () => {
  it("exports the mailbox review queue page", () => {
    expect(MailboxPage).toBeTypeOf("function");
  });
});
