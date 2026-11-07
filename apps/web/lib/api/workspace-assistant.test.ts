import { beforeEach, describe, expect, it, vi } from "vitest";

const request = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiRequest: request }));

import { listAssistantTurns, openAssistantCitation, safeAssistantCitationHref } from "@/lib/api/workspace-assistant";
import { ApiError } from "@/lib/api/config";

describe("assistant history and citation contracts", () => {
  beforeEach(() => {
    request.mockReset();
  });

  it("preserves bounded page arguments and returned continuation metadata", async () => {
    const page = { items: [], limit: 25, offset: 50, has_more: true };
    request.mockResolvedValue(page);
    expect(await listAssistantTurns("session-1", { limit: 25, offset: 50 })).toBe(page);
    expect(request).toHaveBeenCalledExactlyOnceWith("/api/workspace-assistant/sessions/session-1/turns?limit=25&offset=50");
  });

  it("keeps the first-page defaults", async () => {
    await listAssistantTurns("session-1");
    expect(request).toHaveBeenCalledExactlyOnceWith("/api/workspace-assistant/sessions/session-1/turns?limit=50&offset=0");
  });

  it.each([{ limit: 51 }, { limit: 0 }, { limit: 1.5 }, { offset: -1 }, { offset: 10001 }, { offset: NaN }])(
    "rejects invalid page arguments before requesting: %j", (options) => {
      expect(() => listAssistantTurns("session-1", options)).toThrow("Invalid assistant history page.");
      expect(request).not.toHaveBeenCalled();
    },
  );

  it("uses the authenticated citation-open POST and returns the original destination unchanged", async () => {
    const result = { citation_id: "citation-1", source_url: "/app/matters/matter-1?version=exact%2Fretained#source" };
    request.mockResolvedValue(result);
    expect(await openAssistantCitation("session-1", "citation-1")).toBe(result);
    expect(request).toHaveBeenCalledExactlyOnceWith(
      "/api/workspace-assistant/sessions/session-1/citations/citation-1/open", { method: "POST" },
    );
  });

  it.each([
    "/app",
    "/app/clients",
    "/app/matters",
    "/app/matters/12345678-1234-1234-1234-123456789abc",
    "/app/matters/matter-1?version=exact%2Fretained#source",
    "/app/ip?docket=docket-1&view=overview",
    "/app/ip?docket=docket-1&view=proceedings",
    "/app/ip/documents",
  ])("preserves the current backend workspace destination unchanged: %s", async (source_url) => {
    expect(safeAssistantCitationHref(source_url)).toBe(source_url);
    const result = { citation_id: "citation-1", source_url };
    request.mockResolvedValue(result);
    expect(await openAssistantCitation("session-1", "citation-1")).toBe(result);
  });

  it.each([
    null, undefined, {}, "", " /app", "/app ",
    "javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,unsafe",
    "blob:https://caseops.ai/unsafe", "file:///app/matters/matter-1",
    "https://attacker.example/app", "https://caseops.ai/app/matters/matter-1",
    "//attacker.example/app", "///attacker.example/app", "/\\attacker.example/app",
    "/app\n/matters/matter-1", "/app\u0000/matters/matter-1",
    "/app/%2f%2fattacker.example", "/app/%5c%5cattacker.example",
    "/app/../admin", "/app/%2e%2e/admin", "/app/matters/../clients",
    "/native/sign-in", "/app/unknown-route", "/application", "/app/" + "x".repeat(2048),
  ])("refuses malformed or out-of-contract destinations without fallback: %j", async (source_url) => {
    expect(() => safeAssistantCitationHref(source_url)).toThrow(
      "The citation destination is unavailable. Reopen the conversation and try again.",
    );
    request.mockResolvedValue({ citation_id: "citation-1", source_url });
    await expect(openAssistantCitation("session-1", "citation-1")).rejects.toThrow(
      "The citation destination is unavailable. Reopen the conversation and try again.",
    );
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("propagates the exact source-revocation error without fallback or retry", async () => {
    const error = new ApiError(409, "Citation access or source version changed. Ask again before opening it.", null);
    request.mockRejectedValue(error);
    await expect(openAssistantCitation("session-1", "citation-1")).rejects.toBe(error);
    expect(request).toHaveBeenCalledExactlyOnceWith(
      "/api/workspace-assistant/sessions/session-1/citations/citation-1/open", { method: "POST" },
    );
  });

  it.each([null, {}, { citation_id: "wrong", source_url: "/app/matters/other" },
    { citation_id: "citation-1", source_url: null }, { citation_id: "citation-1", source_url: " " }])(
    "refuses a malformed successful open response: %j", async (response) => {
      request.mockResolvedValue(response);
      await expect(openAssistantCitation("session-1", "citation-1")).rejects.toThrow(
        "The citation destination is unavailable. Reopen the conversation and try again.",
      );
      expect(request).toHaveBeenCalledTimes(1);
    },
  );
});
