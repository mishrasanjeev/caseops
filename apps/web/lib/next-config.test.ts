import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";

describe("next dev server config", () => {
  it("allows the loopback origins used by local Playwright runs", () => {
    expect(nextConfig.allowedDevOrigins).toEqual(
      expect.arrayContaining(["127.0.0.1", "localhost"]),
    );
  });
});
