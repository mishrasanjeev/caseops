import { describe, expect, it, vi } from "vitest";

import {
  API_FORM_ERROR_KEY,
  ApiError,
  apiErrorMessage,
  apiFieldErrors,
  describeStructuredProblem,
  describeValidationIssues,
  humanizeApiFieldPath,
  isApiErrorShape,
} from "./config";

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

// The real 422 body production returned to Ram on 2026-10-30 (BUG-014,
// request 4610d09266ce42aea5400ab3295be9fe), plus two model-level failures.
const JOURNAL_422 = {
  type: "https://httpstatuses.com/422",
  title: "Unprocessable content",
  status: 422,
  detail: "List should have at least 1 item after validation, not 0; Input should be a valid list",
  errors: [
    {
      loc: ["body", "publications", 0, "class_numbers"],
      msg: "List should have at least 1 item after validation, not 0",
      type: "too_short",
    },
    {
      loc: ["body", "publications", 0, "goods_services", "45"],
      msg: "Input should be a valid list",
      type: "list_type",
    },
    {
      loc: ["body", "publications", 0],
      msg: "Value error, Goods/services scope must belong to a published class.",
      type: "value_error",
    },
    { loc: ["body"], msg: "Value error, Choose exactly one journal.", type: "value_error" },
  ],
};

describe("field-anchored validation errors (BUG-014)", () => {
  it("humanizes a field path like the API detail does", () => {
    expect(humanizeApiFieldPath(["body", "publications", 0, "class_numbers"])).toBe(
      "Publications \u203a Class numbers",
    );
    expect(humanizeApiFieldPath(["body", "source_url"])).toBe("Source URL");
    expect(humanizeApiFieldPath(["query", "matter_id"])).toBe("Matter ID");
    expect(humanizeApiFieldPath(["body", "payload", "function-after[check(), str]", "[key]"])).toBe(
      "Payload",
    );
    expect(humanizeApiFieldPath(["body"])).toBe("");
  });

  it("words every failure with its field and without the pydantic prefix", () => {
    expect(describeValidationIssues(JOURNAL_422.errors)).toBe(
      "Publications \u203a Class numbers: List should have at least 1 item after validation, not 0; "
        + "Publications \u203a Goods services \u203a 45: Input should be a valid list; "
        + "Publications: Goods/services scope must belong to a published class.; "
        + "Choose exactly one journal.",
    );
  });

  it("maps errors[].loc to form control ids, most specific key first", () => {
    const err = new ApiError(422, "x", JOURNAL_422);
    expect(apiFieldErrors(err, {
      class_numbers: "publication-classes",
      goods_services: "goods-services",
      "goods_services.45": "goods-class-45",
      publications: "publication",
    })).toEqual({
      "publication-classes": "List should have at least 1 item after validation, not 0",
      "goods-class-45": "Input should be a valid list",
      publication: "Goods/services scope must belong to a published class.",
      [API_FORM_ERROR_KEY]: "Choose exactly one journal.",
    });
    // A key naming a middle segment maps every failure beneath it.
    expect(apiFieldErrors(err, { goods_services: "goods-services" })).toMatchObject({
      "goods-services": "Input should be a valid list",
    });
    // Without a map, every failure keeps its own dotted field path.
    expect(apiFieldErrors(err)).toEqual({
      "publications.class_numbers": "List should have at least 1 item after validation, not 0",
      "publications.goods_services.45": "Input should be a valid list",
      publications: "Goods/services scope must belong to a published class.",
      [API_FORM_ERROR_KEY]: "Choose exactly one journal.",
    });
  });

  it("joins several failures on one field and ignores errors without a validation body", () => {
    const err = new ApiError(422, "x", {
      errors: [
        { loc: ["body", "title"], msg: "Field required", type: "missing" },
        { loc: ["body", "title"], msg: "String should have at least 2 characters", type: "string_too_short" },
        { loc: "not-a-list", msg: "ignored" },
      ],
    });
    expect(apiFieldErrors(err, { title: "matter-title" })).toEqual({
      "matter-title": "Field required; String should have at least 2 characters",
    });
    expect(apiFieldErrors(new ApiError(409, "Conflict", { detail: "Conflict" }))).toEqual({});
    expect(apiFieldErrors(new Error("network"))).toEqual({});
  });
});

describe("structured refusals (code/gaps)", () => {
  it("replaces a bare status title with the refusal code and its gaps", () => {
    expect(describeStructuredProblem({
      code: "ip_opposition_opponent_not_ready",
      gaps: ["linked_application_required", "forum_required", "confirmed_client_instruction_required"],
    }, "Conflict")).toBe(
      "IP opposition opponent not ready. Missing: linked application; forum; confirmed client instruction.",
    );
    expect(describeStructuredProblem({ code: "ip_document_locked" }, "Conflict")).toBe(
      "IP document locked.",
    );
  });

  it("keeps a specific message and adds the gaps to it", () => {
    expect(describeStructuredProblem({ code: "stale_write" }, "The record changed.")).toBe(
      "The record changed.",
    );
    expect(describeStructuredProblem({ gaps: ["forum_required"] }, "Opposition is not ready to file.")).toBe(
      "Opposition is not ready to file. Missing: forum.",
    );
    expect(describeStructuredProblem({ detail: "Conflict" }, "Conflict")).toBeNull();
  });
});
