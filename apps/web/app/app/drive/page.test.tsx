import { describe, expect, it } from "vitest";

import DrivePage from "./page";

describe("DrivePage", () => {
  it("exports the Drive review queue page", () => {
    expect(DrivePage).toBeTypeOf("function");
  });
});
