import { describe, expect, it } from "vitest";

import Microsoft365AdminPage from "./page";

describe("Microsoft365AdminPage", () => {
  it("exports the Microsoft 365 tenant setup page", () => {
    expect(Microsoft365AdminPage).toBeTypeOf("function");
  });
});
