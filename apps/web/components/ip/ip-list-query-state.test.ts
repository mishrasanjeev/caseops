import { describe, expect, it } from "vitest";

import { showIpListError } from "@/components/ip/ip-list-query-state";
import { ApiError, NetworkError } from "@/lib/api/config";

const cached = {
  pages: [{ items: [{ id: "cached-private-row" }], total: 2, limit: 100, offset: 0 }],
  pageParams: [0],
};

const transientErrors = [
  ...[408, 429, 500, 502, 503, 504].map((status) => ({
    name: `HTTP ${status}`,
    error: new ApiError(status, "Temporarily unavailable", {}),
  })),
  { name: "network failure", error: new NetworkError("Connection lost", new TypeError("Failed to fetch")) },
];

const blockingErrors = [
  ...[401, 403, 404, 409, 422, 501].map((status) => ({
    name: `HTTP ${status}`,
    error: new ApiError(status, "Read refused", {}),
  })),
  { name: "unknown Error", error: new Error("Unexpected response") },
  { name: "unknown object", error: { status: 503, detail: "Not an identified ApiError" } },
  { name: "malformed ApiError", error: { name: "ApiError", status: "503", detail: "Bad status type" } },
  { name: "unclassified string", error: "Service unavailable" },
  { name: "missing error", error: null },
];

describe("showIpListError", () => {
  it.each(transientErrors)("retains cached pages only for a next-page $name", ({ error }) => {
    expect(showIpListError({ isError: true, isFetchNextPageError: true, data: cached, error })).toBe(false);
  });

  it.each(blockingErrors)("blocks cached private pages for $name", ({ error }) => {
    expect(showIpListError({ isError: true, isFetchNextPageError: true, data: cached, error })).toBe(true);
  });

  it.each([...transientErrors, ...blockingErrors])("blocks a first-page/refetch $name even with cached data", ({ error }) => {
    expect(showIpListError({ isError: true, isFetchNextPageError: false, data: cached, error })).toBe(true);
    expect(showIpListError({ isError: true, isFetchNextPageError: false, data: undefined, error })).toBe(true);
  });

  it.each(transientErrors)("cannot retain absent data after a next-page $name", ({ error }) => {
    for (const data of [undefined, null]) {
      expect(showIpListError({ isError: true, isFetchNextPageError: true, data, error })).toBe(true);
    }
  });

  it.each([503, 401, 403, 404, 409])("classifies an HTTP %i ApiError from another module copy without instanceof", (status) => {
    const error = Object.assign(new Error("Read failed"), {
      ...new ApiError(status, "Read failed", {}, "https://caseops.ai/problems/read-failed"),
    });
    expect(error).not.toBeInstanceOf(ApiError);
    expect(showIpListError({ isError: true, isFetchNextPageError: true, data: cached, error })).toBe(status !== 503);
  });

  it.each([false, true])("does not block a non-error query (next-page error flag: %s)", (isFetchNextPageError) => {
    expect(showIpListError({ isError: false, isFetchNextPageError, data: cached, error: new ApiError(403, "Old error", {}) })).toBe(false);
    expect(showIpListError({ isError: false, isFetchNextPageError, data: undefined, error: null })).toBe(false);
  });
});
