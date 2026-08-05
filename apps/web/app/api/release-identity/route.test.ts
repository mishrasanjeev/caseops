import { describe, expect, it } from "vitest";

import { releaseIdentity } from "./route";

describe("web release identity", () => {
  it("returns the exact injected revision", () => {
    expect(
      releaseIdentity({
        CASEOPS_RELEASE_SHA: "B".repeat(40),
        K_REVISION: "caseops-web-00999-xyz",
      }),
    ).toEqual({
      service: "web",
      release_sha: "b".repeat(40),
      revision: "caseops-web-00999-xyz",
    });
  });

  it("fails closed for an abbreviated tag", () => {
    expect(releaseIdentity({ CASEOPS_RELEASE_SHA: "abcdef1" })).toEqual({
      service: "web",
      release_sha: "unavailable",
      revision: "local",
    });
  });
});
