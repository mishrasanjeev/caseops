import { describe, expect, it, vi } from "vitest";

import { ApiError, apiErrorMessage, isApiErrorShape } from "./config";

describe("isApiErrorShape (BUG-020 hardening)", () => {
  it("accepts a real ApiError instance", () => {
    const err = new ApiError(422, "Boom", { type: "x" }, "x");
    expect(isApiErrorShape(err)).toBe(true);
  });

  it("accepts a duck-typed object that mimics the ApiError shape", () => {
    // Production scenario this guards: Next.js / Turbopack ships two
    // copies of the ApiError class via different module-resolution
    // paths. The thrown object IS an ApiError, but `instanceof` on the
    // imported class symbol fails because the constructor identity
    // differs. The duck-typed check survives that.
    const looksLikeApiError = {
      name: "ApiError",
      detail: "Backend says no",
      status: 422,
      problemType: null,
      data: null,
    };
    expect(isApiErrorShape(looksLikeApiError)).toBe(true);
  });

  it("rejects a plain Error", () => {
    expect(isApiErrorShape(new Error("nope"))).toBe(false);
  });

  it("rejects null and undefined", () => {
    expect(isApiErrorShape(null)).toBe(false);
    expect(isApiErrorShape(undefined)).toBe(false);
  });

  it("rejects an object missing the detail field", () => {
    expect(isApiErrorShape({ name: "ApiError", status: 422 })).toBe(false);
  });
});

describe("apiErrorMessage", () => {
  it("returns ApiError.detail when present", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const err = new ApiError(
      422,
      "The model returned citations, but none matched verified authorities.",
      null,
      null,
    );
    expect(apiErrorMessage(err, "fallback")).toBe(
      "The model returned citations, but none matched verified authorities.",
    );
  });

  it("returns the duck-typed detail even when instanceof would fail", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    // Simulate the "two copies of ApiError" production scenario.
    const looksLikeApiError = {
      name: "ApiError",
      detail: "Detail from the other class identity",
      status: 422,
      problemType: null,
      data: null,
    };
    expect(apiErrorMessage(looksLikeApiError, "generic")).toBe(
      "Detail from the other class identity",
    );
  });

  it("falls back to Error.message when err is a plain Error", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(apiErrorMessage(new Error("Zod parse failed"), "fallback")).toBe(
      "Zod parse failed",
    );
  });

  it("returns the fallback for unknown error shapes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(apiErrorMessage(null, "Could not generate a recommendation.")).toBe(
      "Could not generate a recommendation.",
    );
    expect(apiErrorMessage(42, "Could not generate a recommendation.")).toBe(
      "Could not generate a recommendation.",
    );
    expect(apiErrorMessage("string-thrown", "Could not generate a recommendation.")).toBe(
      "Could not generate a recommendation.",
    );
  });

  it("falls back when ApiError.detail is empty/whitespace", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const err = new ApiError(500, "   ", null, null);
    // Empty detail must not be shown to the user — the layered fallback
    // kicks in.
    expect(apiErrorMessage(err, "Server error.")).toBe("Server error.");
  });

  it("always logs the raw error so a regression to fallback-only is debuggable", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const err = new Error("boom");
    apiErrorMessage(err, "fallback");
    expect(spy).toHaveBeenCalledWith("[apiErrorMessage]", err);
  });
});
