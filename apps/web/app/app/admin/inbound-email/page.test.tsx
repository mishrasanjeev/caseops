import { describe, expect, it } from "vitest";

import InboundEmailAdminPage from "./page";

describe("InboundEmailAdminPage", () => {
  it("exports the inbound email alias administration page", () => {
    expect(InboundEmailAdminPage).toBeTypeOf("function");
  });
});
